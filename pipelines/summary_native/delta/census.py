"""NPC census for a delta run (spec 039 T048, FR-011, N1).

One disposition per subject, computed deterministically from the *selected* new sources, the
entity registry, the published baselines and ``players.yaml``. No model decides a disposition:
``propose_triage_hints`` is the only function here that may call a model and its output is
returned as hints, never applied.

Identity is equality only (CLAUDE.md: no similarity identity). A name resolves when it equals,
casefolded, a registry canonical name or declared alias. A form two entities share, or a bare
generic word, is withheld and reported. A capitalised multi-word name that resolves to nothing is
``unresolved`` (never silently absent); a deliberate exclusion from the rulings file is
``excluded``, a different state.

Presence strength: ``entry`` (a ``## NPCs`` entry), ``event`` (a scene bullet or a moment
attribution) or ``prose`` (only mentioned in narrative text). Disposition for a registry NPC:

* entry or event + published baseline -> ``changed``; + no publication -> ``new``
* prose only + published -> ``mentioned_unchanged``; prose only + unpublished -> ``unresolved``
  (``needs_review``: nothing to be unchanged against, and no entry to draft from)
* not found -> ``absent_from_selected`` (``needs_review`` if a ruled indirect reference matches)

Rulings file (``RULINGS_REL``), all optional::

    excluded: {"Old Marrow Pike": "background colour, not an NPC"}
    deferred: {"Tobin Fenwick": "wait for ch004"}
    indirect_references: {"Brannoc Ironvein": ["the smith"]}
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

import campaignlib
from campaignlib.players_config import load_players_config
from campaignlib.registry import find_registry, load_registry
from pipelines.summary_native import npc_forms, npc_slug, parse

from . import npc_baseline
from .errors import EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .plan import DELTA_ROOT_REL, DeltaPlan
from .records_io import read_json, write_json

DISPOSITIONS = ("changed", "new", "mentioned_unchanged", "absent_from_selected",
                "deferred", "excluded", "unresolved")
CENSUS_REL = f"{DELTA_ROOT_REL}/census"
RULINGS_REL = f"{DELTA_ROOT_REL}/census_rulings.yaml"
_CAP_SEQ = re.compile(r"\b[A-Z][\w'’-]*(?:[ \t]+[A-Z][\w'’-]*)+")
_LEADING = {"the", "a", "an"}
_STRENGTH = {"entry": 3, "event": 2, "prose": 1}


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter: int
    kind: str  # entry | scene | moment
    id: str
    strength: str  # entry | event | prose
    text: str


class CensusEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str
    slug: str
    disposition: str
    needs_review: bool = False
    reasons: list[str] = Field(default_factory=list)
    evidence: list[Span] = Field(default_factory=list)
    ruling: str | None = None  # the rule that produced the disposition
    baseline_status: str | None = None


class Census(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    entries: list[CensusEntry] = Field(default_factory=list)
    skipped_player_characters: list[str] = Field(default_factory=list)
    withheld_forms: list[dict] = Field(default_factory=list)

    def by_subject(self) -> dict[str, CensusEntry]:
        return {e.subject: e for e in self.entries}

    def dispositions(self) -> dict[str, str]:
        return {e.subject: e.disposition for e in self.entries}


def census_path(campaign_dir: Path | str, plan_id: str) -> Path:
    return Path(campaign_dir) / CENSUS_REL / f"{plan_id}.json"


def load_rulings(campaign_dir: Path | str) -> dict:
    p = Path(campaign_dir) / RULINGS_REL
    if not p.is_file():
        return {"excluded": {}, "deferred": {}, "indirect_references": {}}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise DeltaRefusal(f"{RULINGS_REL}: must be a mapping", EXIT_USAGE)
    return {"excluded": dict(data.get("excluded") or {}), "deferred": dict(data.get("deferred") or {}),
            "indirect_references": dict(data.get("indirect_references") or {})}


def read_pinned_source(src, root: Path | None = None) -> str:
    """The text of one plan source, only if its bytes are still the ones the plan pinned.

    A changed bound input exits 3 (contract), it is never read quietly (FR-004, N3).
    """
    data = Path(src.path).read_bytes()
    if hashlib.sha256(data).hexdigest() != src.sha256:
        raise DeltaRefusal(f"source changed since the plan was made: {src.path}; re-plan.", EXIT_STALE)
    return data.decode("utf-8")


def _fold(s: str) -> str:
    return " ".join(s.split()).casefold()


# ── text units ──────────────────────────────────────────────────────────────


def _units(pf: parse.ParsedFile, chapter: int):
    """``(chapter, kind, id, strength_for_bullets, text)`` units; entries are handled apart."""
    for sc in pf.scenes:
        sid = sc.source_scene_id or sc.heading
        bullets = "\n".join(ln for ln in sc.body.splitlines() if ln.lstrip().startswith(("- ", "* ")))
        prose = "\n".join(ln for ln in sc.body.splitlines() if not ln.lstrip().startswith(("- ", "* ", "#")))
        yield chapter, "scene", sid, "event", bullets
        yield chapter, "scene", sid, "prose", prose
    mom = pf.section("Memorable Moments")
    if mom is not None:
        attrib = "\n".join(ln for ln in mom.body.splitlines() if ln.lstrip("> ").startswith(("—", "–", "-")))
        rest = "\n".join(ln for ln in mom.body.splitlines() if ln not in attrib.splitlines())
        yield chapter, "moment", "moments", "event", attrib
        yield chapter, "moment", "moments", "prose", rest


def _snippet(text: str, start: int, end: int, width: int = 80) -> str:
    a, b = max(0, start - width), min(len(text), end + width)
    return " ".join(text[a:b].split())


# ── the census ──────────────────────────────────────────────────────────────


def build_census(campaign_dir: Path | str, plan: DeltaPlan, *, npc_root: Path | None = None,
                 registry_path: Path | None = None) -> Census:
    root = Path(campaign_dir)
    rpath = registry_path or find_registry(root)
    if rpath is None:
        raise DeltaRefusal("no entity registry found (docs/entity_registry.yaml); the census resolves "
                           "names through it", EXIT_USAGE)
    reg = load_registry(rpath)
    pcfg = root / "config" / "players.yaml"
    pc_names: set[str] = set()
    if pcfg.is_file():
        for pl in load_players_config(pcfg).players:
            pc_names.update(_fold(c) for c in pl.plays)
    rulings = load_rulings(root)
    excluded = {_fold(k): (k, v) for k, v in rulings["excluded"].items()}
    deferred = {_fold(k): (k, v) for k, v in rulings["deferred"].items()}
    baselines = npc_baseline.load_baselines(root, npc_root=npc_root)
    by_subject_bl = {b.subject: b for b in baselines.values()}

    # forms: every registry name/alias -> owning entities
    owners: dict[str, set[str]] = {}
    ent_by_name = {e.name: e for e in reg.entities}
    for e in reg.entities:
        for f in [e.name, *e.aliases]:
            if f.strip():
                owners.setdefault(_fold(f), set()).add(e.name)
    wordlist, _ = npc_forms.load_wordlist()
    withheld: list[dict] = []
    forms: dict[str, str] = {}  # usable folded form -> entity name
    for f, names in sorted(owners.items()):
        if len(names) > 1:
            withheld.append({"form": f, "reason": "ambiguous", "owners": sorted(names)})
        elif npc_forms.is_generic_token(f, wordlist):
            withheld.append({"form": f, "reason": "generic", "owners": sorted(names)})
        else:
            forms[f] = next(iter(names))

    def is_pc(name: str) -> bool:
        e = ent_by_name[name]
        return any(_fold(f) in pc_names for f in [e.name, *e.aliases])

    npc_names = [e.name for e in reg.entities if e.type == "npc"]
    pcs = sorted(n for n in npc_names if is_pc(n))
    subjects = [n for n in npc_names if not is_pc(n)]
    pat = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(f) for f in sorted(forms, key=lambda x: (-len(x), x)))
                     + r")(?!\w)", re.IGNORECASE) if forms else None

    spans: dict[str, list[Span]] = {n: [] for n in subjects}
    unresolved: dict[str, list[Span]] = {}
    seen_unres_ids: set[tuple[str, str]] = set()

    def add_unresolved(name: str, span: Span) -> None:
        key = _fold(name)
        if (key, f"{span.chapter}:{span.id}:{span.kind}") in seen_unres_ids:
            return
        seen_unres_ids.add((key, f"{span.chapter}:{span.id}:{span.kind}"))
        unresolved.setdefault(name, []).append(span)

    for src in plan.sources:
        path = Path(src.path)
        read_pinned_source(src)  # exit 3 when the bytes moved since the plan
        pf = parse.parse_file(path, root)
        # NPC entries: the heading is the name; resolve by equality
        for ee in pf.entities:
            if ee.category != "npc":
                continue
            span = Span(chapter=src.chapter, kind="entry", id=f"npcs/{ee.heading}", strength="entry",
                        text=" ".join(ee.body.split())[:240])
            canon = forms.get(_fold(ee.heading))
            if canon is not None and ent_by_name[canon].type == "npc":
                if canon in spans:
                    spans[canon].append(span)
            elif canon is None:
                add_unresolved(ee.heading, span)
        for ch, kind, uid, strength, text in _units(pf, src.chapter):
            if not text.strip():
                continue
            masked = text
            if pat is not None:
                for m in pat.finditer(text):
                    canon = forms[_fold(m.group(0))]
                    if canon in spans:
                        spans[canon].append(Span(chapter=ch, kind=kind, id=uid, strength=strength,
                                                 text=_snippet(text, m.start(), m.end())))
                masked = pat.sub(lambda m: " \x00 ", text)
            for m in _CAP_SEQ.finditer(masked):
                toks = m.group(0).split()
                while toks and toks[0].casefold() in _LEADING:
                    toks.pop(0)
                if len(toks) < 2:
                    continue
                name = " ".join(toks)
                add_unresolved(name, Span(chapter=ch, kind=kind, id=uid, strength=strength,
                                          text=_snippet(masked, m.start(), m.end())))

    entries: list[CensusEntry] = []
    for n in sorted(subjects, key=str.casefold):
        bl = by_subject_bl.get(n)
        sp = spans[n]
        best = max((_STRENGTH[s.strength] for s in sp), default=0)
        e = CensusEntry(subject=n, slug=npc_slug.slug_for(n), disposition="absent_from_selected",
                        evidence=sp, baseline_status=bl.status if bl else None)
        if _fold(n) in excluded or any(_fold(f) in excluded for f in ent_by_name[n].aliases):
            e.disposition, e.ruling = "excluded", "rulings.excluded"
            e.reasons.append(str(next(v for k, v in excluded.items() if k == _fold(n) or
                                      k in {_fold(f) for f in ent_by_name[n].aliases})[1]))
        elif _fold(n) in deferred:
            e.disposition, e.ruling = "deferred", "rulings.deferred"
            e.reasons.append(str(deferred[_fold(n)][1]))
        elif best >= 2:
            e.disposition = "changed" if bl is not None else "new"
            e.ruling = "rule: entry/event in selected source" + (" + published baseline" if bl else ", no publication")
        elif best == 1:
            if bl is not None:
                e.disposition, e.ruling = "mentioned_unchanged", "rule: prose-only mention of a published subject"
            else:
                e.disposition, e.needs_review = "unresolved", True
                e.ruling = "rule: prose-only mention, no publication"
                e.reasons.append("mentioned_without_entry_or_publication")
        else:
            e.ruling = "rule: not present in selected sources"
        hints = [h for h in (rulings["indirect_references"].get(n) or [])]
        if hints and e.disposition in ("absent_from_selected", "mentioned_unchanged"):
            alltext = "\n".join(read_pinned_source(s).casefold() for s in plan.sources)
            hit = [h for h in hints if h.casefold() in alltext]
            if hit:
                e.needs_review = True
                e.reasons.append("indirect_reference:" + ",".join(hit))
        entries.append(e)

    for name in sorted(unresolved, key=str.casefold):
        sp = unresolved[name]
        e = CensusEntry(subject=name, slug=npc_slug.slug_for(name), disposition="unresolved",
                        needs_review=True, evidence=sp,
                        ruling="rule: name does not resolve through the registry",
                        reasons=["not_in_registry"])
        if _fold(name) in excluded:
            e.disposition, e.needs_review, e.ruling = "excluded", False, "rulings.excluded"
            e.reasons = [str(excluded[_fold(name)][1])]
        elif _fold(name) in deferred:
            e.disposition, e.needs_review, e.ruling = "deferred", False, "rulings.deferred"
            e.reasons = [str(deferred[_fold(name)][1])]
        entries.append(e)

    return Census(plan_id=plan.plan_id, entries=entries, skipped_player_characters=pcs,
                  withheld_forms=withheld)


def save_census(campaign_dir: Path | str, census: Census) -> Path:
    return write_json(census_path(campaign_dir, census.plan_id), census.model_dump(mode="json"))


def load_census(campaign_dir: Path | str, plan_id: str) -> Census:
    p = census_path(campaign_dir, plan_id)
    if not p.is_file():
        raise DeltaRefusal(f"no census for plan {plan_id}; run `summary_native delta census` first")
    return Census.model_validate(read_json(p))


def run_census(campaign_dir: Path | str, plan: DeltaPlan, **kw) -> tuple[Census, Path]:
    c = build_census(campaign_dir, plan, **kw)
    return c, save_census(campaign_dir, c)


# ── hints (the only model-capable function; output is hints, never a disposition) ──


def propose_triage_hints(census: Census, *, backend: str | None = None, model: str | None = None,
                         client=None, caller=None) -> list[dict]:
    """Ask a model what each ``unresolved`` name might be. Returns ``[{name, hint, ...}]``.

    The census is not modified and no disposition is assigned: the GM rules via the rulings file
    or the registry. ``caller`` is a test seam standing in for ``campaignlib.call_api``.
    """
    names = [e for e in census.entries if e.disposition == "unresolved"]
    hints: list[dict] = []
    if not names:
        return hints
    if caller is None:
        client = client or campaignlib.make_client(backend=backend)
        caller = campaignlib.call_api
    for e in names:
        ev = "\n".join(f"- ch{s.chapter} {s.id}: {s.text}" for s in e.evidence[:3])
        text = caller(client, "You help a game master triage unresolved names. Answer in one sentence: "
                      "is this likely an NPC, a title/role, or noise? You do not decide.",
                      f"Name: {e.subject}\nEvidence:\n{ev}", model)
        hints.append({"name": e.subject, "hint": str(text).strip(),
                      "note": "hint only; no disposition was assigned"})
    return hints
