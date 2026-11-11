"""Draft and verify changed and new NPCs from selected evidence (spec 039 T050, T051; FR-005, FR-012).

A changed NPC keeps its published history **byte for byte**: ``History with the Party`` and
``Notable Quotes`` are copied from the baseline *draft* (the reviewed file the publication was made
from) and the model only contributes new blocks that cite chapters after the baseline horizon. A new
NPC is drafted from its new evidence alone. Drafting input is built from four things and no others:

* the baseline draft's exact blocks (``npc_baseline`` names the file; never a published dossier,
  which carries Secrets),
* the selected new evidence spans from the census,
* the numbered Manual edits, read only through ``npc_authored.load_manual`` (inside
  ``npc_draft.run_draft``; this module never opens an authored file),
* associations the GM approved (``associations.approved_associations``).

The model call, resume, dispatch, outline check, draft files and GM composition are
``npc_draft.run_draft``'s own (reached through its ``delta=`` hook). This module makes no model call
itself. Verification is the existing ``npc_verify.verify`` run over ``SparseEvidence``: the spans are
the selected new spans plus the baseline's own evidence for the history it reuses. No function here
takes a verdict from its caller; ``verify.md`` is always recomputed.

Layout under ``<campaign>/docs/summaries/delta/<plan_id>/npc/``: ``members.json`` (the run's inputs and
range), ``<stem>.spans.json`` (the exact spans verification uses), ``<stem>.verify.json``,
``freshness.json`` (the per-item dependency graph) and ``receipts/`` (publication receipts). Drafts,
evidence packs and the GM composition are in the usual NPC range folder ``ch<since>-<until>``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from campaignlib.registry import find_registry, load_registry
from campaignlib.util import atomic_write_text
from pipelines.summary_native import npc_authored, npc_check, npc_compose, npc_draft, npc_link, npc_slug, npc_verify, parse, schema
from pipelines.summary_native.freshness import DepNode, DependencyGraph

from . import associations, npc_baseline
from .census import Census, CensusEntry, load_census
from .errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .evidence import EvidenceKindError, EvidenceSpan, SparseEvidence, require_full
from .plan import DELTA_ROOT_REL, DeltaPlan
from .records_io import read_json, write_json

NPC_STATE_DIR = "npc"
REUSED_HEADINGS = ("## History with the Party", "## Notable Quotes")
HISTORY, QUOTES = REUSED_HEADINGS
AUDIENCES = ("gm", "player")
MEMBER_DISPOSITIONS = ("changed", "new")
#: Authority files an NPC sign-off silently depends on (absent files record "absent").
RULE_NODE_FILES = ("config/players.yaml", "docs/thread_registry.yaml", "docs/canon.yaml")


# ── paths and small helpers ─────────────────────────────────────────────────


def delta_dir(campaign_dir: Path | str, plan_id: str) -> Path:
    return Path(campaign_dir) / DELTA_ROOT_REL / plan_id / NPC_STATE_DIR


def receipts_dir(campaign_dir: Path | str, plan_id: str) -> Path:
    return delta_dir(campaign_dir, plan_id) / "receipts"


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str | None:
    return _sha_bytes(path.read_bytes()) if Path(path).is_file() else None


def _rel(root: Path, path: Path) -> str:
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


HISTORICAL_PARSE_MARKER_REL = f"{DELTA_ROOT_REL}/historical_parse.allowed"


def allow_historical_parse(campaign_dir: Path | str, reason: str = "baseline has no kept evidence pack") -> Path:
    """The GM's explicit, durable opt-in to read the historical chapters a baseline's draft cites when no
    evidence pack was kept (SC-001 otherwise forbids it). Reported as ``parsed_historical`` in read counts."""
    p = Path(campaign_dir) / HISTORICAL_PARSE_MARKER_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, f"{reason}\n")
    return p


def historical_parse_allowed(campaign_dir: Path | str) -> bool:
    return (Path(campaign_dir) / HISTORICAL_PARSE_MARKER_REL).is_file()


def range_name(since: int, until: int) -> str:
    return f"ch{since:03d}-{until:03d}"


# ── audience (FR-012) ───────────────────────────────────────────────────────


def check_audience(audience: str, *, has_unclassified_inputs: bool = True) -> None:
    """Refuse a non-GM audience before any evidence is read.

    NPC drafting inputs (summaries, baseline drafts, manual edits) carry no audience
    classification; unclassified legacy evidence is GM-only until someone classifies it
    (spec FR-012). The published dossier also carries Secrets. So a ``player`` request is
    refused here, at the boundary, before a single input file is opened.
    """
    if audience not in AUDIENCES:
        raise DeltaRefusal(f"--audience must be one of {', '.join(AUDIENCES)}", EXIT_USAGE)
    if audience != "gm" and has_unclassified_inputs:
        raise DeltaRefusal(
            f"audience {audience!r} refused: NPC evidence is GM-only until it is classified, and no "
            "evidence was read to answer this request", EXIT_REFUSAL)


# ── members ─────────────────────────────────────────────────────────────────


@dataclass
class Member:
    entry: CensusEntry
    baseline: npc_baseline.NpcBaseline | None
    stem: str
    prior_text: str | None = None  # baseline draft, comment line removed
    spans: list[EvidenceSpan] = field(default_factory=list)
    missing_scope: list[str] = field(default_factory=list)
    assocs: list = field(default_factory=list)
    reads: dict = field(default_factory=lambda: {"parsed_historical": 0, "reused_artifact": 0})

    @property
    def subject(self) -> str:
        return self.entry.subject

    @property
    def slug(self) -> str:
        return self.entry.slug

    @property
    def horizon(self) -> int | None:
        return self.baseline.horizon if self.baseline else None


def select_members(census: Census, subjects: Iterable[str] | None = None) -> list[CensusEntry]:
    """Census entries to draft: ``changed`` and ``new`` only (a mention is attested, not drafted)."""
    wanted = {s.casefold() for s in subjects} if subjects is not None else None
    out = [e for e in census.entries if e.disposition in MEMBER_DISPOSITIONS]
    if wanted is not None:
        out = [e for e in out if e.subject.casefold() in wanted or e.slug in wanted]
    return out


def _fold(s: str) -> str:
    return " ".join(s.split()).casefold()


def _forms(root: Path, subject: str, withheld: Iterable[str] = ()) -> set[str]:
    """The subject's own name forms, minus every form the census withheld (generic, or owned by more
    than one entity): such a form never selects evidence for this subject (FR-002)."""
    held = {_fold(f) for f in withheld}
    forms = {_fold(subject)}
    rpath = find_registry(root)
    if rpath is not None:
        for e in load_registry(rpath).entities:
            if e.name == subject:
                forms.update(_fold(a) for a in e.aliases)
    return {f for f in forms if f and f not in held}


def _mentions(text: str, forms: set[str]) -> bool:
    """Word-bounded, never substring: ``Ash`` does not select a moment about ``Ashen``."""
    return any(re.search(r"(?<!\w)" + re.escape(f) + r"(?!\w)", text, re.IGNORECASE) for f in forms)


# ── prior (baseline) dossier ────────────────────────────────────────────────


def split_sections(text: str) -> list[tuple[str, str]]:
    """``[(heading, raw)]`` where ``raw`` is the exact text of the section from its heading line."""
    out: list[tuple[str, list[str]]] = []
    for ln in text.splitlines(keepends=True):
        if ln.startswith("## "):
            out.append((ln.rstrip(), [ln]))
        elif out:
            out[-1][1].append(ln)
    return [(h, "".join(lines)) for h, lines in out]


def _baseline_draft_path(root: Path, baseline: npc_baseline.NpcBaseline) -> Path:
    rng = baseline.publication.get("range")
    stem = npc_slug.stem_for("npc", baseline.subject)
    return npc_baseline.npc_root_for(root) / str(rng) / "draft" / f"{stem}.md"


def _read_prior(root: Path, baseline: npc_baseline.NpcBaseline) -> str:
    text = _baseline_draft_path(root, baseline).read_text(encoding="utf-8")
    return re.sub(r"\A<!--.*?-->[ \t]*\n", "", text, count=1, flags=re.DOTALL)


# ── evidence spans ──────────────────────────────────────────────────────────


def _new_spans(root: Path, plan: DeltaPlan, entry: CensusEntry, forms: set[str],
               horizon: int | None) -> list[EvidenceSpan]:
    """Full text of the selected new items this subject is *present* in (entry or event, never a
    prose-only mention), after the baseline horizon."""
    wanted: dict[int, set[tuple[str, str]]] = {}
    for sp in entry.evidence:
        if sp.strength == "prose" or (horizon is not None and sp.chapter <= horizon):
            continue
        wanted.setdefault(sp.chapter, set()).add((sp.kind, sp.id))
    spans: list[EvidenceSpan] = []
    approved = {a.id: (a, src) for a, src in associations.selected_approved(root, plan)
                if a.canonical_id == entry.subject}
    for sp in entry.evidence:
        if sp.kind != "association" or (horizon is not None and sp.chapter <= horizon):
            continue
        if sp.id not in approved:
            raise DeltaRefusal(f"{entry.subject}: association {sp.id} is no longer approved")
        a, src = approved[sp.id]
        target = a.source.scene
        if target in ("moment", "moments"):
            kind = "moment"
        elif target == "entry" or target.startswith("npcs/"):
            kind = "entry"
        else:
            kind = "scene"
        spans.append(EvidenceSpan(src.chapter, kind, target if kind == "scene" else kind,
                                  a.relationship_support, _rel(root, Path(src.path)), src.sha256, "new"))
    for src in plan.sources:
        if src.chapter not in wanted:
            continue
        path = Path(src.path)
        if _sha_file(path) != src.sha256:
            raise DeltaRefusal(f"{path}: changed since the plan was made; re-plan", EXIT_STALE)
        pf = parse.parse_file(path, root)
        rel = _rel(root, path)
        items = npc_link.iter_items(pf)
        for kind, uid in sorted(wanted[src.chapter]):
            if kind == "entry":
                for ee in pf.entities:
                    if ee.category == "npc" and f"npcs/{ee.heading}" == uid and ee.body.strip():
                        spans.append(EvidenceSpan(src.chapter, "entry", "entry", ee.body.strip(), rel, src.sha256, "new"))
            elif kind == "scene":
                for it in items:
                    if it.kind == "scene" and it.scene_id == uid and it.text.strip():
                        spans.append(EvidenceSpan(src.chapter, "scene", uid, it.text.strip(), rel, src.sha256, "new"))
            elif kind == "moment":
                for it in items:
                    if it.kind == "moment" and any(f in it.text.casefold() for f in forms):
                        spans.append(EvidenceSpan(src.chapter, "moment", "moment", it.text.strip(), rel, src.sha256, "new"))
    return spans


def _pack_items(pack_text: str) -> list[npc_check.Item]:
    _head, body = npc_link.split_frontmatter(pack_text)
    return [i for c in npc_check.split_chapters(body) for i in c.items]


def _inherited_spans(root: Path, member: Member, forms: set[str]) -> list[EvidenceSpan]:
    """Spans for the history the draft reuses.

    From the baseline's own evidence pack when one was kept; otherwise only the targets the
    baseline draft cites, each read from its one historical chapter file (never a campaign scan).
    A target that cannot be resolved goes to ``missing_scope`` and its citation will fail.
    """
    bl = member.baseline
    assert bl is not None and member.prior_text is not None
    nroot = npc_baseline.npc_root_for(root)
    stem = npc_slug.stem_for("npc", bl.subject)
    pack = nroot / str(bl.publication.get("range")) / "evidence" / f"{stem}.md"
    if pack.is_file():
        member.reads["reused_artifact"] += 1
        rel, sha = _rel(root, pack), _sha_file(pack)
        return [EvidenceSpan(i.chapter, i.kind, i.target if i.kind == "scene" else i.kind, i.text, rel, sha, "inherited")
                for i in _pack_items(pack.read_text(encoding="utf-8")) if i.text.strip()]
    if not historical_parse_allowed(root):
        raise DeltaRefusal(
            f"{bl.subject}: the baseline has no kept evidence pack ({_rel(root, pack)}), so reusing its history "
            "would mean re-parsing historical chapters, which a delta does not do (FR-004, SC-001). Restore the "
            "pack from the range it was published from, or pass --allow-historical-parse to `delta npc draft` "
            "to read only the chapters the baseline draft cites (counted as parsed_historical)", EXIT_REFUSAL)
    cited: set[tuple[int, str]] = set()
    for line in member.prior_text.splitlines():
        for _b, (ch, tgt) in npc_check.citation_parts(line):
            if ch >= 0:
                cited.add((ch, tgt))
    spans: list[EvidenceSpan] = []
    by_chapter: dict[int, list[str]] = {}
    for ch, tgt in sorted(cited):
        by_chapter.setdefault(ch, []).append(tgt)
    sdir = root / "docs" / "summaries"
    for ch, targets in by_chapter.items():
        files = sorted(sdir.glob(f"{ch:03d}-*.md"))
        if len(files) != 1:
            member.missing_scope += [f"ch {ch:03d} / {t}: no single historical chapter file" for t in targets]
            continue
        member.reads["parsed_historical"] += 1
        pf = parse.parse_file(files[0], root)
        rel, sha = _rel(root, files[0]), _sha_file(files[0])
        items = npc_link.iter_items(pf)
        for tgt in targets:
            text = ""
            if tgt == "entry":
                text = "\n".join(e.body.strip() for e in pf.entities
                                 if e.category == "npc" and _fold(e.heading) in forms)
            elif tgt == "moment":
                text = "\n\n".join(i.text.strip() for i in items
                                   if i.kind == "moment" and _mentions(i.text, forms))
            else:
                text = "\n".join(i.text.strip() for i in items if i.kind == "scene" and i.scene_id == tgt)
            if text.strip():
                kind = "scene" if tgt not in ("entry", "moment") else tgt
                spans.append(EvidenceSpan(ch, kind, tgt, text.strip(), rel, sha, "inherited"))
            else:
                member.missing_scope.append(f"ch {ch:03d} / {tgt}: not found in {rel}")
    return spans


def render_pack(subject: str, spans: list[EvidenceSpan], since: int, until: int) -> str:
    """An evidence dossier in the format ``npc_link`` writes and ``npc_check`` reads."""
    by: dict[int, list[EvidenceSpan]] = {}
    for sp in spans:
        by.setdefault(sp.chapter, []).append(sp)
    chapters = sorted(by)
    n_entries = len({sp.target for sp in spans if sp.kind == "entry"})
    n_scenes = len({sp.target for sp in spans if sp.kind == "scene"})
    n_moments = len({sp.target for sp in spans if sp.kind == "moment"})
    fm = {"subject": subject, "type": "npc", "global": True, "exclusion": None, "aliases_used": [],
          "first_seen": chapters[0] if chapters else 0, "last_seen": chapters[-1] if chapters else 0,
          "chapters": chapters, "n_entries": n_entries, "n_scenes": n_scenes, "n_moments": n_moments,
          "range": range_name(since, until), "source_kind": "delta"}
    head = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, default_flow_style=None, width=10**6)
    parts = [f"---\n{head}---\n\n# NPC — {subject}\n"]
    for ch in chapters:
        parts.append(f"\n## Chapter {ch:03d}\n")
        group: dict[str, list[str]] = {}
        for sp in by[ch]:
            group.setdefault(sp.id, []).append(sp.span)
        order = ["entry"] + sorted(k for k in group if k not in ("entry", "moment")) + ["moment"]
        for key in order:
            if key not in group:
                continue
            text = "\n\n".join(dict.fromkeys(group[key]))
            if key == "entry":
                head_line = f"### Entry — {subject}"
            elif key == "moment":
                head_line = "### Moment (mentioned)"
            else:
                head_line = f"### Scene {key} — (mentioned)"
            parts.append(f"\n{head_line}\n- Source: selected evidence\n\n{text}\n")
    return "".join(parts)


def spans_to_json(spans: list[EvidenceSpan], missing: list[str]) -> dict:
    return {"spans": [dict(chapter=s.chapter, kind=s.kind, id=s.id, span=s.span, source_path=s.source_path,
                           source_sha256=s.source_sha256, origin=s.origin) for s in spans],
            "missing_scope": list(missing)}


def sparse_from_json(rec: dict) -> SparseEvidence:
    spans = [EvidenceSpan(**s) for s in rec.get("spans", [])]
    return SparseEvidence(spans, missing_scope=tuple(rec.get("missing_scope", ())))


# ── building the run's inputs ───────────────────────────────────────────────


def build_members(root: Path, plan: DeltaPlan, census: Census, subjects: Iterable[str] | None = None) -> list[Member]:
    members: list[Member] = []
    for entry in select_members(census, subjects):
        bl = npc_baseline.baseline_for(root, entry.slug)
        if entry.disposition == "changed":
            if bl is None:
                raise DeltaRefusal(f"{entry.subject}: census says changed but the publish log has no entry", EXIT_REFUSAL)
            if not bl.ok:
                raise DeltaRefusal(f"{entry.subject}: baseline is {bl.status}; repair it before drafting", EXIT_REFUSAL)
        m = Member(entry=entry, baseline=bl if entry.disposition == "changed" else None,
                   stem=npc_slug.stem_for("npc", entry.subject))
        forms = _forms(root, entry.subject, (w.get("form", "") for w in census.withheld_forms))
        if m.baseline is not None:
            m.prior_text = _read_prior(root, m.baseline)
            m.spans += _inherited_spans(root, m, forms)
        m.spans += _new_spans(root, plan, entry, forms, m.horizon)
        if not any(s.origin == "new" for s in m.spans):
            raise DeltaRefusal(f"{entry.subject}: no new evidence after the baseline horizon; attest it instead", EXIT_REFUSAL)
        m.assocs = associations.approved_associations(root, plan.plan_id, canonical_id=entry.subject)
        members.append(m)
    return members


def compute_range(plan: DeltaPlan, members: list[Member]) -> tuple[int, int]:
    """One range for the run: from the earliest covered chapter to the last selected one."""
    chapters = [s.chapter for s in plan.sources]
    sinces = [min(chapters)] + [_since_of(m.baseline) for m in members if m.baseline]
    untils = chapters + [m.horizon for m in members if m.horizon]
    return min(sinces), max(untils)


def _since_of(bl: npc_baseline.NpcBaseline) -> int:
    m = re.match(r"^ch(\d+)-(\d+)$", str(bl.publication.get("range") or ""))
    return int(m.group(1)) if m else 1


# ── the hook npc_draft.run_draft calls ──────────────────────────────────────


class DeltaDraftSpec:
    """What ``npc_draft.run_draft(delta=...)`` needs (see that function's docstring)."""

    def __init__(self, root: Path, plan: DeltaPlan, members: list[Member], evidence: list[npc_link.EvidenceFile],
                 since: int, until: int) -> None:
        self.root, self.plan = root, plan
        self.members = {m.stem: m for m in members}
        self.evidence, self.since, self.until = evidence, since, until
        self.drops: dict[str, list[str]] = {}
        self.record = {"plan_id": plan.plan_id,
                       "members": {m.stem: {"subject": m.subject, "disposition": m.entry.disposition,
                                            "horizon": m.horizon,
                                            "new_targets": sorted(f"{s.chapter}/{s.id}" for s in m.spans if s.origin == "new"),
                                            "inherited_targets": sorted(f"{s.chapter}/{s.id}" for s in m.spans if s.origin == "inherited"),
                                            "associations": [a.id for a in m.assocs]}
                                   for m in members}}

    # prompt ---------------------------------------------------------------
    def prompt(self, stem: str, subject: str, ev, manual: list[str], headings: list[str]) -> tuple[str, str]:
        m = self.members[stem]
        system, user = npc_draft.build_prompt(ev.body, ev.header, manual, headings)
        if m.prior_text is not None:
            horizon = m.horizon
            user += (
                f"\nPRIOR DOSSIER (published through chapter {horizon:03d}). The host copies its "
                f"`{HISTORY[3:]}` and `{QUOTES[3:]}` sections into the result unchanged, so DO NOT restate them. "
                f"In those two sections write ONLY new items drawn from chapters after {horizon:03d}, each cited. "
                "Update the other sections from the whole evidence; do not contradict the prior dossier "
                "except where newer evidence changes it.\n\n" + m.prior_text.rstrip("\n") + "\n"
            )
        if m.assocs:
            lines = [f"- {a.name} -> {a.canonical_id} (scope: {a.scope}). Support: \"{a.relationship_support}\" "
                     f"[{a.source.scene}]" for a in m.assocs]
            user += ("\nAPPROVED ASSOCIATIONS (the GM approved each; state a claim only within its scope, never "
                     "as a general alias):\n" + "\n".join(lines) + "\n")
        return system, user

    # code that restores reused bytes --------------------------------------
    def postprocess(self, stem: str, body: str) -> str:
        m = self.members[stem]
        if m.prior_text is None:
            return body
        text, drops = assemble(m.prior_text, body, m.horizon or 0, npc_draft.synth.load_outline(schema.NPC_OUTLINE))
        self.drops[stem] = drops
        return text

    # sparse verification ---------------------------------------------------
    def verify_draft(self, draft_dir: Path, stem: str, subject: str, ev, manual: list[str]):
        m = self.members[stem]
        return verify_text(Path(draft_dir), stem, subject, m.spans, m.missing_scope, ev.header + ev.body, manual)


def _blocks(section_raw: str, per_bullet: bool) -> list[str]:
    lines = section_raw.splitlines()[1:]
    blocks: list[list[str]] = []
    prev_blank = True
    for ln in lines:
        if not ln.strip():
            prev_blank = True
            continue
        if prev_blank or (per_bullet and ln.startswith("- ")):
            blocks.append([ln])
        else:
            blocks[-1].append(ln)
        prev_blank = False
    return ["\n".join(b) for b in blocks]


def _is_new_block(block: str, horizon: int, prior_text: str) -> bool:
    chapters = {ch for line in block.splitlines() for _b, (ch, _t) in npc_check.citation_parts(line)}
    has_manual = bool(schema.MANUAL_CITATION_RE.search(block))
    if -1 in chapters or (not chapters and not has_manual):
        return False
    return all(ch > horizon for ch in chapters) and block.strip() not in prior_text


def assemble(prior_text: str, model_body: str, horizon: int, headings: list[str]) -> tuple[str, list[str]]:
    """The final draft body: reused sections exact, everything the model adds beyond them new.

    ``History with the Party`` and ``Notable Quotes`` are the prior dossier's bytes followed by the
    model's blocks that cite only chapters after ``horizon``; any other model block in those two
    sections is dropped and reported. The remaining sections are the model's.
    """
    prior = dict(split_sections(prior_text))
    model = dict(split_sections(model_body))
    drops: list[str] = []
    out: list[str] = []
    for h in headings:
        raw = model.get(h)
        if h in REUSED_HEADINGS and (h in prior or raw is not None):
            per_bullet = h == HISTORY
            new: list[str] = []
            for b in _blocks(raw, per_bullet) if raw else []:
                (new if _is_new_block(b, horizon, prior_text) else drops).append(b)
            sep = "\n" if per_bullet else "\n\n"
            if h in prior:
                section = prior[h].rstrip("\n") + "\n"
                if new:
                    section += ("\n" if not per_bullet else "") + sep.join(new) + "\n"
            else:
                section = f"{h}\n\n" + (sep.join(new) + "\n" if new else (raw.split("\n", 1)[1].lstrip("\n") if raw else ""))
            out.append(section.rstrip("\n") + "\n")
        elif raw is not None:
            out.append(raw.rstrip("\n") + "\n")
        elif h in prior:
            out.append(prior[h].rstrip("\n") + "\n")
    return "\n".join(out), [f"dropped (not new evidence): {d}" for d in drops]


# ── verification ────────────────────────────────────────────────────────────


def _sparse_banner(sparse: SparseEvidence) -> str:
    inh = sum(1 for s in sparse.spans if s.origin == "inherited")
    new = sum(1 for s in sparse.spans if s.origin == "new")
    return (f"\n- Evidence: SPARSE ({new} new spans, {inh} inherited spans). This is not a full-corpus "
            f"verification. Missing scope: {list(sparse.missing_scope) or 'none'}. "
            f"Unexamined scope: {list(sparse.unexamined_scope) or 'none'}.\n")


def verify_text(draft_dir: Path, stem: str, subject: str, spans: list[EvidenceSpan], missing: list[str],
                evidence_dossier: str, manual: list[str], *, full: bool = False):
    """Run the real ``npc_verify.verify`` over sparse evidence and write ``<stem>.verify.md``.

    There is no verdict parameter: the result comes from the verifier. ``full=True`` asks for a
    full-corpus verification and is refused for sparse evidence (``require_full``).
    """
    sparse = SparseEvidence(spans, missing_scope=tuple(missing))
    if full:
        try:
            require_full(sparse)
        except EvidenceKindError as e:
            raise DeltaRefusal(str(e), EXIT_REFUSAL) from None
    text = (Path(draft_dir) / f"{stem}.md").read_text(encoding="utf-8")
    summaries = "\n".join(s.span for s in spans)
    result = npc_verify.verify(text, evidence_dossier, sparse, summaries, manual)
    md = npc_verify.render_verify_md(result, subject)
    head, sep, rest = md.partition("\n\n## Totals")
    md = head + "\n" + _sparse_banner(sparse) + sep + rest if sep else md
    atomic_write_text(Path(draft_dir) / f"{stem}.verify.md", md)
    return result


# ── freshness graph ─────────────────────────────────────────────────────────


def _assoc_digest(a) -> str:
    return _sha_bytes(json.dumps(a.model_dump(mode="json"), sort_keys=True).encode("utf-8"))


def graph_path(campaign_dir: Path | str, plan_id: str) -> Path:
    return delta_dir(campaign_dir, plan_id) / "freshness.json"


def record_freshness(root: Path, plan: DeltaPlan, members: list[Member], range_dir: Path,
                     stems: Iterable[str] | None = None) -> DependencyGraph:
    """Record, per item (keyed by draft stem), what its sign-off depends on and the digests now.

    Nodes are keyed by campaign-relative path so a review's custody sources can be matched to them
    (``npc_publish._current_draft_signoff``). Shared sources list every consumer.
    """
    path = graph_path(root, plan.plan_id)
    graph = DependencyGraph.from_dict(read_json(path)) if path.is_file() else DependencyGraph()
    registry = find_registry(root)
    for m in members:
        if stems is not None and m.stem not in stems:
            continue
        deps: list[tuple[DepNode, str | None]] = []
        deps.append((DepNode("draft", _rel(root, range_dir / "draft" / f"{m.stem}.md")),
                     _sha_file(range_dir / "draft" / f"{m.stem}.md")))
        deps.append((DepNode("evidence", _rel(root, range_dir / "evidence" / f"{m.stem}.md")),
                     _sha_file(range_dir / "evidence" / f"{m.stem}.md")))
        deps.append((DepNode("composition", _rel(root, range_dir / "gm" / f"{m.stem}.md")),
                     _sha_file(range_dir / "gm" / f"{m.stem}.md")))
        authored = root / schema.AUTHORED_DIR / f"{m.slug}.authored.yaml"
        if authored.is_file():
            deps.append((DepNode("composition", _rel(root, authored)), _sha_file(authored)))
        for s in sorted({(s.source_path, s.source_sha256) for s in m.spans}):
            deps.append((DepNode("shared_source", s[0]), s[1]))
        if registry is not None:
            deps.append((DepNode("identity_ruling", _rel(root, registry)), _sha_file(registry)))
        for rel in RULE_NODE_FILES:  # players / thread / canon rulings: a change to one stales the sign-off
            deps.append((DepNode("rule", rel), _sha_file(root / rel) or "absent"))
        for a in m.assocs:
            deps.append((DepNode("association", f"assoc:{a.id}"), _assoc_digest(a)))
        graph._deps.pop(m.stem, None)  # re-record: the digests now are the ones the GM will review
        for node, digest in deps:
            graph.add(m.stem, node, digest or "absent")
    write_json(path, graph.to_dict())
    return graph


def load_graph(campaign_dir: Path | str, plan_id: str) -> DependencyGraph:
    p = graph_path(campaign_dir, plan_id)
    if not p.is_file():
        raise DeltaRefusal(f"no freshness record for plan {plan_id}; run `delta npc draft` first", EXIT_USAGE)
    return DependencyGraph.from_dict(read_json(p))


def current_digests(campaign_dir: Path | str, plan_id: str, graph: DependencyGraph) -> dict[DepNode, str]:
    """The digest of every node's artifact as it is on disk now (a missing one is simply absent)."""
    root = Path(campaign_dir)
    assoc = {a.id: a for a in associations.load_store(root, plan_id).associations if a.decision == "approved"}
    out: dict[DepNode, str] = {}
    for item in graph.items():
        for node in graph.dependencies(item):
            if node.kind == "association":
                a = assoc.get(node.key.removeprefix("assoc:"))
                if a is not None:
                    out[node] = _assoc_digest(a)
            else:
                d = _sha_file(root / node.key)
                if d is not None:
                    out[node] = d
                elif node.kind == "rule":
                    out[node] = "absent"
    return out


# ── operations ──────────────────────────────────────────────────────────────


@dataclass
class DraftOutcome:
    exit_code: int
    range_dir: Path
    since: int
    until: int
    members: list[str]
    verify: dict[str, dict] = field(default_factory=dict)
    reads: dict = field(default_factory=dict)


def _state_path(root: Path, plan_id: str) -> Path:
    return delta_dir(root, plan_id) / "members.json"


def draft(campaign_dir: Path | str, plan: DeltaPlan, *, backend: str | None = None, model: str | None = None,
          audience: str = "gm", subjects: Iterable[str] | None = None, dump_only: bool = False,
          resume: str | None = None, force: bool = False, max_tokens: int | None = None, now=None) -> DraftOutcome:
    """Draft the census' changed and new NPCs through ``npc_draft.run_draft``.

    Order: audience gate (before any input is read) -> census -> baselines -> drafting inputs ->
    evidence packs -> ``run_draft`` (model call, outline check, sparse verify, compose). Nothing is
    published and nothing is signed off here.
    """
    check_audience(audience)
    root = Path(campaign_dir)
    census = load_census(root, plan.plan_id)
    members = build_members(root, plan, census, subjects)
    if not members:
        raise DeltaRefusal("no changed or new NPCs to draft in this census", EXIT_USAGE)
    since, until = compute_range(plan, members)
    rdir = npc_baseline.npc_root_for(root) / range_name(since, until)
    if (rdir / npc_link.LINK_MANIFEST).exists():
        raise DeltaRefusal(f"{range_name(since, until)} already holds a full-corpus build; refusing to mix "
                           "delta drafts into it", EXIT_REFUSAL)
    for m in members:
        if m.missing_scope:
            raise DeltaRefusal(f"{m.subject}: history it would reuse cannot be resolved to evidence "
                               f"({'; '.join(m.missing_scope)}); repair the baseline", EXIT_REFUSAL)
        pack = rdir / "evidence" / f"{m.stem}.md"
        pack.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(pack, render_pack(m.subject, m.spans, since, until))
        write_json(delta_dir(root, plan.plan_id) / f"{m.stem}.spans.json", spans_to_json(m.spans, m.missing_scope))
    stems = {m.stem for m in members}
    evidence = [e for e in npc_link.read_evidence_files(rdir) if e.stem in stems]
    spec = DeltaDraftSpec(root, plan, members, evidence, since, until)

    choice = plan.models.generation
    args = _draft_args([m.subject for m in members], backend or choice.backend, model or choice.model,
                       dump_only=dump_only, resume=resume, force=force, max_tokens=max_tokens)
    code = npc_draft.run_draft(
        args, root=root, range_dir=rdir, npc_range_dir=rdir, report=None, registry_path=None, canon_path=None,
        recent_chapters=None, recurring_min=None, now=now, delta=spec)

    reads = {k: sum(m.reads[k] for m in members) for k in ("parsed_historical", "reused_artifact")}
    write_json(_state_path(root, plan.plan_id), {
        "plan_id": plan.plan_id, "range": range_name(since, until), "since": since, "until": until,
        "members": [{"subject": m.subject, "slug": m.slug, "stem": m.stem, "disposition": m.entry.disposition,
                     "horizon": m.horizon,
                     "associations": [a.id for a in m.assocs]} for m in members],
        "read_counts": reads, "drops": spec.drops, "exit_code": code})
    verify: dict[str, dict] = {}
    if not dump_only:
        if code in (0, npc_draft.EXIT_INCOMPLETE):
            record_freshness(root, plan, members, rdir, stems={m.stem for m in members if (rdir / "draft" / f"{m.stem}.md").is_file()})
        for m in members:
            vj = rdir / "draft" / f"{m.stem}.verify.md"
            if vj.is_file():
                verify[m.subject] = {"verdict": npc_publish_verdict(rdir, m.stem)}
    return DraftOutcome(code, rdir, since, until, [m.subject for m in members], verify, reads)


def npc_publish_verdict(range_dir: Path, stem: str) -> str | None:
    from pipelines.summary_native import npc_publish
    return npc_publish.read_verdict(range_dir, stem)


def _draft_args(names: list[str], backend: str, model: str, *, dump_only: bool, resume: str | None,
                force: bool, max_tokens: int | None):
    import argparse
    return argparse.Namespace(
        name=names, all=False, recent_chapters=None, recurring_min=None, dump_only=dump_only, force=force,
        model=model, backend=backend, max_tokens=max_tokens or schema.DEFAULT_MAX_TOKENS, mode="one-shot",
        chunk_chars=None, endpoints=None, parallel=None, resume=resume)


def load_state(campaign_dir: Path | str, plan_id: str) -> dict:
    p = _state_path(Path(campaign_dir), plan_id)
    if not p.is_file():
        raise DeltaRefusal(f"no NPC drafts recorded for plan {plan_id}; run `delta npc draft` first", EXIT_USAGE)
    return read_json(p)


def verify(campaign_dir: Path | str, plan: DeltaPlan, *, subjects: Iterable[str] | None = None) -> dict[str, dict]:
    """Recompute sparse verification for the drafted members.

    It NEVER records the freshness graph: re-recording from the files as they are now would let a
    change made after a sign-off pass as current. The graph is recorded when a draft is made and when
    a review is handed off (``rerecord_freshness``).

    The result is always computed here from the draft and the recorded spans; there is no way to
    pass a verdict in, and a hand-written ``verify.md`` is overwritten. Returns
    ``{subject: {verdict, counts, evidence_kind, missing_scope, ...}}``.
    """
    root = Path(campaign_dir)
    state = load_state(root, plan.plan_id)
    rdir = npc_baseline.npc_root_for(root) / state["range"]
    want = {s.casefold() for s in subjects} if subjects is not None else None
    out: dict[str, dict] = {}
    for mem in state["members"]:
        subject, stem = mem["subject"], mem["stem"]
        if want is not None and subject.casefold() not in want and mem["slug"] not in want:
            continue
        draft_path = rdir / "draft" / f"{stem}.md"
        if not draft_path.is_file():
            out[subject] = {"verdict": None, "reason": "no draft"}
            continue
        rec = read_json(delta_dir(root, plan.plan_id) / f"{stem}.spans.json")
        sparse = sparse_from_json(rec)
        pack = rdir / "evidence" / f"{stem}.md"
        if not pack.is_file():
            raise DeltaRefusal(f"{subject}: evidence pack is missing; re-run `delta npc draft`", EXIT_STALE)
        manual = npc_authored.load_manual(npc_compose.authored_path_for(root, subject), subject)
        result = verify_text(draft_path.parent, stem, subject, list(sparse.spans), list(sparse.missing_scope),
                             pack.read_text(encoding="utf-8"), manual)
        record = result.to_dict()
        record.update({"evidence_kind": sparse.kind, "missing_scope": list(sparse.missing_scope),
                       "unexamined_scope": list(sparse.unexamined_scope),
                       "inherited_targets": sorted(f"{c}/{i}" for c, i in sparse.inherited_targets),
                       "new_targets": sorted(f"{c}/{i}" for c, i in sparse.new_targets),
                       "draft_sha256": _sha_file(draft_path)})
        write_json(delta_dir(root, plan.plan_id) / f"{stem}.verify.json", record)
        out[subject] = record
    return out


def rerecord_freshness(campaign_dir: Path | str, plan: DeltaPlan, slugs: Iterable[str]) -> list[str]:
    """Record the dependency digests as they are now for the named members (the state the GM is about
    to review). Used at review handoff, only for members that have no current approval, so a member
    changed after its sign-off stays stale. Returns the slugs recorded."""
    root = Path(campaign_dir)
    wanted = set(slugs)
    state = load_state(root, plan.plan_id)
    rdir = npc_baseline.npc_root_for(root) / state["range"]
    store = associations.load_store(root, plan.plan_id)
    members: list[Member] = []
    for mem in state["members"]:
        if mem["slug"] not in wanted:
            continue
        rec_path = delta_dir(root, plan.plan_id) / f"{mem['stem']}.spans.json"
        if not rec_path.is_file() or not (rdir / "draft" / f"{mem['stem']}.md").is_file():
            continue
        sparse = sparse_from_json(read_json(rec_path))
        stub = CensusEntry(subject=mem["subject"], slug=mem["slug"], disposition=mem["disposition"])
        assocs = [a for a in store.associations if a.id in set(mem.get("associations", ())) and a.decision == "approved"]
        members.append(Member(entry=stub, baseline=None, stem=mem["stem"], spans=list(sparse.spans), assocs=assocs))
    if members:
        record_freshness(root, plan, members, rdir)
    return [m.slug for m in members]


def graph_recorded(campaign_dir: Path | str, plan_id: str) -> set[str]:
    """Draft stems that have a recorded dependency set."""
    p = graph_path(campaign_dir, plan_id)
    return set(DependencyGraph.from_dict(read_json(p)).items()) if p.is_file() else set()


# ── publication ─────────────────────────────────────────────────────────────


def _members_for(root: Path, plan: DeltaPlan, subjects: Iterable[str]) -> tuple[dict, list[dict]]:
    names = [s for s in subjects if s and s.strip()]
    if not names:
        raise DeltaRefusal("no members selected; name each NPC with --member (there is no 'all')", EXIT_USAGE)
    state = load_state(root, plan.plan_id)
    by = {}
    for m in state["members"]:
        by[m["subject"].casefold()] = m
        by[m["slug"]] = m
    chosen, unknown = [], []
    for n in names:
        m = by.get(n.strip().casefold()) or by.get(npc_slug.slug_for(n))
        (chosen if m else unknown).append(m or n)
    if unknown:
        raise DeltaRefusal(f"not drafted in this plan: {', '.join(unknown)}", EXIT_USAGE)
    return state, list({m["slug"]: m for m in chosen}.values())


def publish_preview(campaign_dir: Path | str, plan: DeltaPlan, subjects: Iterable[str]) -> dict:
    """The digest a publication is bound to: the plan, and per member the exact draft, composition,
    evidence pack, current target and publish-log entry. Reads only; writes nothing."""
    from pipelines.summary_native import npc_publish
    from .plan import plan_digest

    root = Path(campaign_dir)
    state, members = _members_for(root, plan, subjects)
    rdir = npc_baseline.npc_root_for(root) / state["range"]
    log = npc_publish.read_publish_log(root, npc_baseline.npc_root_for(root))
    rows = []
    for m in members:
        stem, slug = m["stem"], m["slug"]
        rows.append({
            "subject": m["subject"], "slug": slug,
            "draft_sha256": _sha_file(rdir / "draft" / f"{stem}.md"),
            "composition_sha256": _sha_file(rdir / "gm" / f"{stem}.md"),
            "evidence_sha256": _sha_file(rdir / "evidence" / f"{stem}.md"),
            "target_sha256": _sha_file(root / schema.NPCS_DIR / f"{slug}.md"),
            "log_entry_sha256": _sha_bytes(json.dumps(log.get(slug), sort_keys=True).encode("utf-8")),
        })
    body = {"plan": plan_digest(plan), "members": sorted(rows, key=lambda r: r["slug"])}
    return {"plan_id": plan.plan_id, "members": body["members"],
            "preview_sha256": _sha_bytes(json.dumps(body, sort_keys=True).encode("utf-8"))}


def preview_record_path(campaign_dir: Path | str, plan_id: str) -> Path:
    return delta_dir(campaign_dir, plan_id) / "preview.json"


def store_preview(campaign_dir: Path | str, plan: DeltaPlan, subjects: Iterable[str]) -> dict:
    """Compute the preview for the named members AND record it (the GM's explicit member set).

    ``delta run resume`` publishes only members named in this record, and only while their rows
    still equal the recorded ones (FR-020): a run never computes a preview and confirms it itself.
    """
    pv = publish_preview(campaign_dir, plan, subjects)
    if load_stored_preview(campaign_dir, plan.plan_id) != pv:  # an identical re-preview writes nothing
        write_json(preview_record_path(campaign_dir, plan.plan_id), pv)
    return pv


def load_stored_preview(campaign_dir: Path | str, plan_id: str) -> dict | None:
    p = preview_record_path(campaign_dir, plan_id)
    return read_json(p) if p.is_file() else None


def publish(campaign_dir: Path | str, plan: DeltaPlan, subjects: Iterable[str], preview_sha: str, *, now=None):
    """Publish the named members, each on its own, through ``npc_publish.publish``.

    Members are independent: one held or failed member does not stop or undo another, and nothing
    here claims group atomicity. Preconditions, in order: explicit members; the preview digest still
    matches (exit 3 otherwise); verification is recomputed here (a hand-written ``verify.md`` is
    overwritten, never believed); sign-off freshness is scoped to each member's own dependencies.
    The sign-off itself is the real authority ledger's; nothing here can supply one.
    """
    from pipelines.summary_native import npc_publish

    from .review_binding import member_holds, require_fresh

    root = Path(campaign_dir)
    _st, chosen_rows = _members_for(root, plan, subjects)
    # required: an NPC publication needs the GM's handoff review binding (FR-017/FR-020); exit 3 on a moved
    # bound hash, exit 1 with no binding at all
    slugs = [m["slug"] for m in chosen_rows]
    binding = require_fresh(root, plan, "npc", members=slugs, required=True, enforce_decisions=False)
    holds = member_holds(binding, slugs)  # a member whose own decision is not an approve is held; others proceed
    current = publish_preview(root, plan, subjects)
    if preview_sha != current["preview_sha256"]:
        raise DeltaRefusal("the preview is stale: a draft, composition, evidence pack, target or publish-log "
                           "entry changed since it was made; run the preview again", EXIT_STALE)
    state, members = _members_for(root, plan, subjects)
    chosen = [m["subject"] for m in members]
    verify(root, plan, subjects=chosen)
    graph = load_graph(root, plan.plan_id)
    return npc_publish.publish(
        root, npc_baseline.npc_root_for(root) / state["range"], names=chosen, dependency_graph=graph,
        current_digests=current_digests(root, plan.plan_id, graph),
        receipt_dir=receipts_dir(root, plan.plan_id), hold={s: r for s, r in holds.items()}, now=now)
