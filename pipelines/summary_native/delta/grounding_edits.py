"""Host-validated grounding edit proposals (spec 039, FR-006, FR-007, T028-T030).

Division of labour (Principle II, research R3):

* The HOST assigns stable line identifiers to the bound baseline, computes every before-digest,
  validates proposals, and reconstructs documents.  Reconstruction applies only proposals a person
  has approved, and leaves every untouched line byte-identical (a CRLF or a missing final newline
  survives).  Nothing in the host side calls a model.
* The MODEL (``propose_edits``, the only model call in this module) is shown numbered baseline lines
  and the selected-source spans.  It names a target and gives replacement text; it never supplies
  before-text or a digest.  Its output is parsed into *drafts*; nothing is applied.

A target id is ``<doc>:L<n>:<h8>`` (one line) or ``<doc>:L<a>-L<b>:<h8>`` (a contiguous range), where
``h8`` is the first eight hex digits of the sha256 of the range's FIRST line, so an id minted for one
baseline cannot silently address different text in another.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from campaignlib import make_client, stream_api

from .errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .plan import DELTA_ROOT_REL

CATEGORIES = ("new_information", "superseded_state", "resolved_thread", "historical_event",
              "no_material_change", "source_correction")
DECISION_VALUES = ("approve", "reject", "discuss", "hold")
DEFAULT_CHECKS = ("heading", "table", "citation", "consistency")
_TARGET = re.compile(r"^(?P<doc>[a-z_]+):L(?P<a>\d+)(?:-L(?P<b>\d+))?:(?P<h>[0-9a-f]{8})$")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lines(data: bytes) -> list[bytes]:
    return data.splitlines(keepends=True)


# --------------------------------------------------------------------------- targets

class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str
    document: str
    start: int  # 1-based, inclusive
    end: int
    sha256: str  # of the exact bytes of the range


def line_target_id(document: str, number: int, line: bytes) -> str:
    return f"{document}:L{number}:{_sha(line)[:8]}"


def assign_targets(docs: Mapping[str, bytes]) -> list[Target]:
    """One stable id per baseline line, in document then line order."""
    out: list[Target] = []
    for name in sorted(docs):
        for n, line in enumerate(_lines(docs[name]), start=1):
            out.append(Target(target_id=line_target_id(name, n, line), document=name,
                              start=n, end=n, sha256=_sha(line)))
    return out


def resolve_target(docs: Mapping[str, bytes], target_id: str) -> Target | None:
    """The target a host-minted id addresses in THIS baseline, or None when it addresses nothing."""
    m = _TARGET.match(target_id or "")
    if not m or m["doc"] not in docs:
        return None
    a = int(m["a"])
    b = int(m["b"]) if m["b"] else a
    lines = _lines(docs[m["doc"]])
    if a < 1 or b < a or b > len(lines) or _sha(lines[a - 1])[:8] != m["h"]:
        return None
    return Target(target_id=target_id, document=m["doc"], start=a, end=b,
                  sha256=_sha(b"".join(lines[a - 1:b])))


# --------------------------------------------------------------------------- records

class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    target_id: str
    before_sha256: str
    after_text: str
    category: str
    rationale: str
    support: str
    dependent_checks: list[str] = Field(default_factory=lambda: list(DEFAULT_CHECKS))
    #: Spec 040 (rebase repairs).  All three are omitted from the serialised record while None, so a proposal
    #: made before they existed keeps its bytes.  ``hold_marker`` is the one line a ``hold`` decision appends
    #: under the target; a proposal without one cannot be held.
    origin: str | None = None  # "gm" | "model"
    author: str | None = None
    hold_marker: str | None = None

    @model_serializer(mode="wrap")
    def _omit_unset(self, handler):
        data = handler(self)
        for key in ("origin", "author", "hold_marker"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class RejectedProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str
    reason: str


class ProposalSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    baseline_ref: str
    revision: int = Field(default=1, ge=1)
    proposals: list[Proposal] = Field(default_factory=list)
    rejected: list[RejectedProposal] = Field(default_factory=list)
    empty_justification: str | None = None
    generated_by: dict[str, str] | None = None
    status: str = "draft"  # a proposal set is always a draft; only decisions approve


class DecisionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    reason: str | None = None
    reviewer: str | None = None


class DecisionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    proposals_revision: int
    revision: int = Field(ge=1)
    decisions: dict[str, DecisionEntry] = Field(default_factory=dict)


def proposal_id_for(target_id: str, after_text: str) -> str:
    return "p-" + _sha(f"{target_id}\0{after_text}".encode("utf-8"))[:12]


def make_proposal(docs: Mapping[str, bytes], *, target_id: str, after_text: str, category: str,
                  rationale: str, support: str, dependent_checks=None) -> Proposal:
    """A proposal whose before-digest is computed by the host from the baseline (never supplied)."""
    target = resolve_target(docs, target_id)
    if target is None:
        raise DeltaRefusal(f"unknown target {target_id!r}", EXIT_REFUSAL)
    return Proposal(
        proposal_id=proposal_id_for(target_id, after_text), target_id=target_id,
        before_sha256=target.sha256, after_text=after_text, category=category,
        rationale=rationale, support=support,
        dependent_checks=list(dependent_checks or DEFAULT_CHECKS))


# --------------------------------------------------------------------------- validation

def _problem(docs, p: Proposal, source_texts) -> str | None:
    target = resolve_target(docs, p.target_id)
    if target is None:
        return f"unknown target {p.target_id}"
    if p.category not in CATEGORIES:
        return f"unknown category {p.category!r} for {p.target_id}"
    if p.before_sha256 != target.sha256:
        return f"stale before_sha256 for {p.target_id}: the baseline line changed since the proposal was made"
    if not p.rationale.strip():
        return f"{p.target_id} has no rationale"
    if source_texts is not None and p.category != "no_material_change":
        if not p.support or not any(p.support in text for text in source_texts.values()):
            return f"support for {p.target_id} is not an exact span of a selected source"
    return None


def partition_proposals(docs: Mapping[str, bytes], proposals, *, source_texts=None):
    """``(accepted, rejected)``: the first of a duplicate or overlap wins; nothing is dropped silently."""
    ok: list[Proposal] = []
    rejected: list[RejectedProposal] = []
    seen_ids: set[str] = set()
    spans: list[tuple[str, int, int, str]] = []
    for p in proposals:
        reason = _problem(docs, p, source_texts)
        if reason is None:
            if p.target_id in seen_ids:
                reason = f"duplicate target {p.target_id}"
            else:
                t = resolve_target(docs, p.target_id)
                clash = next((tid for d, s, e, tid in spans
                              if d == t.document and s <= t.end and t.start <= e), None)
                if clash:
                    reason = f"overlapping target {p.target_id} (overlaps {clash})"
        if reason is not None:
            rejected.append(RejectedProposal(target_id=p.target_id, reason=reason))
            continue
        seen_ids.add(p.target_id)
        t = resolve_target(docs, p.target_id)
        spans.append((t.document, t.start, t.end, p.target_id))
        ok.append(p)
    return ok, rejected


def validate_proposals(docs: Mapping[str, bytes], proposals, *, source_texts=None,
                       empty_justification: str | None = None) -> None:
    """Strict form: any unknown, duplicate, overlapping or stale proposal refuses with all reasons."""
    proposals = list(proposals)
    if not proposals:
        if not (empty_justification or "").strip():
            raise DeltaRefusal(
                "an empty proposal set needs an explicit justification (nothing in the selected "
                "sources changes the grounding documents)", EXIT_REFUSAL)
        return
    _ok, rejected = partition_proposals(docs, proposals, source_texts=source_texts)
    if rejected:
        raise DeltaRefusal("invalid grounding edit proposals: "
                           + "; ".join(r.reason for r in rejected), EXIT_REFUSAL)


# --------------------------------------------------------------------------- reconstruction

def blocking_proposals(proposals, decisions: Mapping[str, DecisionEntry]) -> list[str]:
    return [p.proposal_id for p in proposals
            if (decisions.get(p.proposal_id).decision if decisions.get(p.proposal_id) else None)
            not in ("approve", "reject", "hold")]


def reconstruct(docs: Mapping[str, bytes], proposals, decisions: Mapping[str, DecisionEntry],
                *, empty_justification: str | None = None) -> dict[str, bytes]:
    """Apply APPROVED proposals only; every other byte of every document is unchanged."""
    proposals = list(proposals)
    validate_proposals(docs, proposals, empty_justification=empty_justification)
    blocked = blocking_proposals(proposals, decisions)
    if blocked:
        raise DeltaRefusal(
            "reconstruction blocked: decide each proposal (approve or reject); undecided or "
            "'discuss': " + ", ".join(blocked), EXIT_REFUSAL)
    edits: dict[str, list[tuple[int, int, bytes]]] = {}
    for p in proposals:
        verdict = decisions[p.proposal_id].decision
        if verdict == "hold":
            if not p.hold_marker:
                raise DeltaRefusal(f"proposal {p.proposal_id} cannot be held: it carries no hold marker", EXIT_REFUSAL)
            t = resolve_target(docs, p.target_id)
            original = b"".join(_lines(docs[t.document])[t.start - 1:t.end])
            ending = b"\r\n" if original.endswith(b"\r\n") else b"\n"
            kept = original.endswith((b"\n", b"\r"))
            # the line stays byte-identical; exactly one marker line follows it
            new = (original if kept else original + ending) + p.hold_marker.encode("utf-8") + (ending if kept else b"")
            edits.setdefault(t.document, []).append((t.start, t.end, new))
            continue
        if verdict != "approve" or p.category == "no_material_change":
            continue
        t = resolve_target(docs, p.target_id)
        original = b"".join(_lines(docs[t.document])[t.start - 1:t.end])
        new = p.after_text.encode("utf-8")
        for ending in (b"\r\n", b"\n"):
            if original.endswith(ending):
                if new and not new.endswith((b"\n", b"\r")):
                    new += ending
                break
        edits.setdefault(t.document, []).append((t.start, t.end, new))
    out = dict(docs)
    for name, items in edits.items():
        lines = _lines(docs[name])
        for start, end, new in sorted(items, reverse=True):
            lines[start - 1:end] = [new] if new else []
        out[name] = b"".join(lines)
    return {k: bytes(v) for k, v in out.items()}


# --------------------------------------------------------------------------- storage

def edits_dir(campaign_dir: Path | str, plan_id: str) -> Path:
    return Path(campaign_dir) / DELTA_ROOT_REL / "grounding" / plan_id


def _revisions(directory: Path, stem: str) -> list[tuple[int, Path]]:
    found = []
    for p in directory.glob(f"{stem}-r*.json"):
        m = re.fullmatch(re.escape(stem) + r"-r(\d+)\.json", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return sorted(found)


def _write_new(directory: Path, stem: str, revision: int, record: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stem}-r{revision}.json"
    if target.exists():
        raise DeltaRefusal(f"{target.name} already exists", EXIT_STALE)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def save_proposals(campaign_dir: Path | str, proposal_set: ProposalSet) -> ProposalSet:
    directory = edits_dir(campaign_dir, proposal_set.plan_id)
    existing = _revisions(directory, "proposals")
    saved = proposal_set.model_copy(update={"revision": (existing[-1][0] + 1) if existing else 1})
    _write_new(directory, "proposals", saved.revision, saved.model_dump(mode="json"))
    return saved


def load_proposals(campaign_dir: Path | str, plan_id: str) -> ProposalSet:
    files = _revisions(edits_dir(campaign_dir, plan_id), "proposals")
    if not files:
        raise DeltaRefusal(f"no grounding proposals for plan {plan_id}; run `delta grounding propose`",
                           EXIT_REFUSAL)
    return ProposalSet.model_validate_json(files[-1][1].read_text(encoding="utf-8"))


def load_decisions(campaign_dir: Path | str, plan_id: str) -> DecisionSet | None:
    files = _revisions(edits_dir(campaign_dir, plan_id), "decisions")
    if not files:
        return None
    return DecisionSet.model_validate_json(files[-1][1].read_text(encoding="utf-8"))


def decide(campaign_dir: Path | str, plan_id: str, proposal_id: str, decision: str,
           reason: str | None = None, *, reviewer: str = "") -> DecisionSet:
    """Record one decision as a NEW revisioned file; earlier revisions are kept.

    ``reviewer`` is required and recorded with the decision: who approved an edit is part of the record,
    and there is no default (not even the login name).
    """
    if decision not in DECISION_VALUES:
        raise DeltaRefusal(f"decision must be one of {DECISION_VALUES}; there is no default", EXIT_USAGE)
    if not (reviewer or "").strip():
        raise DeltaRefusal("--reviewer is required to record a grounding decision; there is no default reviewer",
                           EXIT_USAGE)
    proposal_set = load_proposals(campaign_dir, plan_id)
    chosen = {p.proposal_id: p for p in proposal_set.proposals}.get(proposal_id)
    if chosen is None:
        raise DeltaRefusal(f"no such proposal {proposal_id} in plan {plan_id}", EXIT_REFUSAL)
    if decision == "hold" and not chosen.hold_marker:
        raise DeltaRefusal(f"proposal {proposal_id} cannot be held: only a source-correction repair carries a hold "
                           "marker (use approve, reject or discuss)", EXIT_REFUSAL)
    previous = load_decisions(campaign_dir, plan_id)
    carried = dict(previous.decisions) if previous and previous.proposals_revision == proposal_set.revision else {}
    carried[proposal_id] = DecisionEntry(decision=decision, reason=reason, reviewer=reviewer.strip())
    record = DecisionSet(plan_id=plan_id, proposals_revision=proposal_set.revision,
                         revision=(previous.revision + 1) if previous else 1, decisions=carried)
    _write_new(edits_dir(campaign_dir, plan_id), "decisions", record.revision, record.model_dump(mode="json"))
    return record


def decide_many(campaign_dir: Path | str, plan_id: str, decisions: Mapping[str, tuple[str, str | None]], *,
                reviewer: str) -> DecisionSet:
    """Record several decisions as ONE new revisioned file (``{proposal_id: (decision, reason)}``).

    The same rules as :func:`decide` for each: an explicit decision value, a required reviewer, a known proposal,
    and a hold only on a proposal that carries a hold marker.  The bulk hold of a rebase entry uses it so a
    thousand held lines are one revision, not a thousand.
    """
    if not (reviewer or "").strip():
        raise DeltaRefusal("--reviewer is required to record a grounding decision; there is no default reviewer",
                           EXIT_USAGE)
    if not decisions:
        raise DeltaRefusal("no decisions to record", EXIT_USAGE)
    proposal_set = load_proposals(campaign_dir, plan_id)
    known = {p.proposal_id: p for p in proposal_set.proposals}
    for proposal_id, (decision, _reason) in decisions.items():
        if decision not in DECISION_VALUES:
            raise DeltaRefusal(f"decision must be one of {DECISION_VALUES}; there is no default", EXIT_USAGE)
        if proposal_id not in known:
            raise DeltaRefusal(f"no such proposal {proposal_id} in plan {plan_id}", EXIT_REFUSAL)
        if decision == "hold" and not known[proposal_id].hold_marker:
            raise DeltaRefusal(f"proposal {proposal_id} cannot be held: only a source-correction repair carries a "
                               "hold marker", EXIT_REFUSAL)
    previous = load_decisions(campaign_dir, plan_id)
    carried = dict(previous.decisions) if previous and previous.proposals_revision == proposal_set.revision else {}
    for proposal_id, (decision, reason) in decisions.items():
        carried[proposal_id] = DecisionEntry(decision=decision, reason=reason, reviewer=reviewer.strip())
    record = DecisionSet(plan_id=plan_id, proposals_revision=proposal_set.revision,
                         revision=(previous.revision + 1) if previous else 1, decisions=carried)
    _write_new(edits_dir(campaign_dir, plan_id), "decisions", record.revision, record.model_dump(mode="json"))
    return record


def append_proposals(campaign_dir: Path | str, plan_id: str, baseline_ref: str, docs: Mapping[str, bytes],
                     new: list[Proposal], *, generated_by: dict[str, str] | None = None) -> ProposalSet:
    """Add proposals to the plan's set as a NEW revision, keeping the decisions already made on the others.

    ``save_proposals`` starts a re-proposed set undecided; a rebase adds repairs one at a time, and a GM's
    earlier approvals must survive the next one.  The merged set is validated strictly (an unknown, stale,
    duplicate or overlapping proposal refuses and writes nothing).  A proposal already in the set is a no-op.
    """
    try:
        current = load_proposals(campaign_dir, plan_id)
    except DeltaRefusal:
        current = None
    have = {p.proposal_id for p in current.proposals} if current else set()
    fresh = [p for p in new if p.proposal_id not in have]
    if current is not None and not fresh:
        return current
    merged = list(current.proposals if current else []) + fresh
    validate_proposals(docs, merged)
    saved = save_proposals(campaign_dir, ProposalSet(
        plan_id=plan_id, baseline_ref=baseline_ref, proposals=merged,
        generated_by=generated_by or (current.generated_by if current else None)))
    previous = load_decisions(campaign_dir, plan_id)
    if current is not None and previous is not None and previous.proposals_revision == current.revision \
            and previous.decisions:
        carried = DecisionSet(plan_id=plan_id, proposals_revision=saved.revision, revision=previous.revision + 1,
                              decisions=dict(previous.decisions))
        _write_new(edits_dir(campaign_dir, plan_id), "decisions", carried.revision, carried.model_dump(mode="json"))
    return saved


def current_decisions(campaign_dir: Path | str, plan_id: str, proposal_set: ProposalSet) -> dict[str, DecisionEntry]:
    """Decisions that belong to THIS proposal revision (a re-propose starts undecided)."""
    d = load_decisions(campaign_dir, plan_id)
    if d is None or d.proposals_revision != proposal_set.revision:
        return {}
    return d.decisions


def reconstruct_for_plan(campaign_dir: Path | str, plan_id: str,
                         docs: Mapping[str, bytes]) -> dict[str, bytes]:
    proposal_set = load_proposals(campaign_dir, plan_id)
    return reconstruct(docs, proposal_set.proposals,
                       current_decisions(campaign_dir, plan_id, proposal_set),
                       empty_justification=proposal_set.empty_justification)


# --------------------------------------------------------------------------- the model step

SYSTEM_PROMPT = """You propose minimal edits to a campaign's grounding documents so they reflect newly \
selected session summaries. You do not rewrite documents. You are shown numbered baseline lines, each \
with a target id, and the selected source text.

Rules:
- Propose an edit only where a selected source changes, supersedes, resolves or adds to what a line says.
- Address a single line by its target id exactly as shown, or a contiguous range as <doc>:L<a>-L<b>:<hash> \
using the first line's hash.
- To add new material, replace an anchor line with itself followed by the new lines.
- `support` MUST be an exact, verbatim span copied from the selected sources.
- Keep citations of the form [ch NNN / target]; cite only chapters and targets that appear in the sources \
or already in the baseline.
- category is one of: new_information, superseded_state, resolved_thread, historical_event, no_material_change.
- Do not state numeric scores, totals or thresholds.
Reply with ONE JSON object and nothing else:
{"proposals":[{"target_id":"...","after_text":"...","category":"...","rationale":"...","support":"..."}],
 "empty_justification": null or "why nothing changes"}"""


def build_prompt(docs: Mapping[str, bytes], source_texts: Mapping[str, str]) -> str:
    parts = ["## Selected sources\n"]
    for path in sorted(source_texts):
        parts.append(f"### {path}\n{source_texts[path]}\n")
    parts.append("## Baseline lines (target id <TAB> text)\n")
    for t in assign_targets(docs):
        text = _lines(docs[t.document])[t.start - 1].decode("utf-8", "replace").rstrip("\r\n")
        if text.strip():
            parts.append(f"{t.target_id}\t{text}")
    return "\n".join(parts)


def parse_model_output(text: str) -> dict:
    body = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*?)\n```$", body, re.S)
    if fence:
        body = fence.group(1)
    try:
        value = json.loads(body)
    except ValueError as exc:
        raise DeltaRefusal(f"the model's proposal output is not valid JSON ({exc}); nothing was saved",
                           EXIT_REFUSAL) from exc
    if not isinstance(value, dict) or not isinstance(value.get("proposals", []), list):
        raise DeltaRefusal("the model's proposal output has no 'proposals' list; nothing was saved",
                           EXIT_REFUSAL)
    return value


def propose_edits(docs: Mapping[str, bytes], source_texts: Mapping[str, str], *, plan_id: str,
                  baseline_ref: str, backend: str | None = None, model: str, client=None,
                  max_tokens: int = 16000) -> ProposalSet:
    """The only model call here.  Returns DRAFT proposals; nothing is applied or approved."""
    if not source_texts:
        raise DeltaRefusal("no sources selected; nothing to propose from.", EXIT_USAGE)
    if client is None:
        client = make_client(backend=backend, model_override=model)
    raw = stream_api(client, SYSTEM_PROMPT, build_prompt(docs, source_texts), model,
                     max_tokens=max_tokens, silent=True)
    value = parse_model_output(raw)
    proposals: list[Proposal] = []
    rejected: list[RejectedProposal] = []
    for item in value.get("proposals", []):
        try:
            tid = str(item["target_id"])
            target = resolve_target(docs, tid)
            if target is None:
                rejected.append(RejectedProposal(target_id=tid, reason=f"unknown target {tid}"))
                continue
            proposals.append(make_proposal(
                docs, target_id=tid, after_text=str(item["after_text"]), category=str(item["category"]),
                rationale=str(item.get("rationale", "")), support=str(item.get("support", ""))))
        except (KeyError, TypeError) as exc:
            rejected.append(RejectedProposal(target_id=str(item.get("target_id", "?")) if isinstance(item, dict) else "?",
                                             reason=f"malformed proposal: {exc!r}"))
    ok, more = partition_proposals(docs, proposals, source_texts=source_texts)
    justification = value.get("empty_justification")
    result = ProposalSet(
        plan_id=plan_id, baseline_ref=baseline_ref, proposals=ok, rejected=rejected + more,
        empty_justification=justification if isinstance(justification, str) and justification.strip() else None,
        generated_by={"backend": backend or "", "model": model})
    if not ok and not result.empty_justification:
        raise DeltaRefusal(
            "the model proposed no usable edits and gave no justification for an empty set; rejected: "
            + ("; ".join(r.reason for r in result.rejected) or "none"), EXIT_REFUSAL)
    return result
