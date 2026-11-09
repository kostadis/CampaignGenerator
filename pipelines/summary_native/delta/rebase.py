"""Source-custody rebase: prepare, repair, decide, show (spec 040, T012, T013, T015, T016).

A rebase is a delta plan of ``kind="rebase"`` (research R1).  This module owns the records around it, all files
under ``docs/summaries/delta/rebase/<rebase_id>/``:

* ``inspection.json``  the stale-pin report at the time of ``prepare``;
* ``snapshots.json``   the verified old and current bytes of each selected chapter (the bytes themselves are in
                       the write-once ``custody/objects`` store);
* ``impact.json``      the deterministic :class:`~.rebase_impact.ImpactSet`;
* ``decisions-r<N>.json`` the GM's append-only decisions;
* ``review.md``        the rendered review (``show``).

Nothing here calls a model (the drafting step is :mod:`.rebase_propose`, a separate module so this one can be
AST-guarded), writes an authored summary, or touches an existing ``docs/grounding/generations/<gid>/``.
A semantic change cannot be adopted by hash replacement alone: ``adopt-unaffected`` is refused while the impact
set lists any affected line or annotation, and ``adopt-with-repairs`` is refused while an affected line has
neither an approved repair nor an explicit hold.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict

from campaignlib.util import atomic_write_text

from . import baseline as baseline_mod, custody_store, grounding_edits, rebase_inspect
from .cli_plan import campaign_identity
from .errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .plan import DELTA_ROOT_REL, DeltaPlan, PlanModels, create_plan, load_plan, plans_dir, save_plan
from .lineage import RebaseBlock, RebaseSource
from .rebase_impact import (
    AffectedLine, ImpactSet, SourceChange, compute_impact, find_line, impact_digest, indexed_lines,
)
from .records_io import read_json, write_json

REBASE_REL = f"{DELTA_ROOT_REL}/rebase"
SOURCE_DECISIONS = ("adopt-unaffected", "adopt-with-repairs", "reject")
MEMBER_DECISIONS = ("repaired", "held", "attested-unaffected")
REASON_REQUIRED = ("reject", "attested-unaffected")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha(value) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _refuse(code: str, message: str, exit_code: int = EXIT_REFUSAL) -> DeltaRefusal:
    return DeltaRefusal(f"{code}: {message}", exit_code)


def rebase_dir(root: Path | str, rebase_id: str) -> Path:
    return Path(root) / REBASE_REL / rebase_id


def hold_marker(chapter: int, rebase_id: str) -> str:
    """The one line a ``hold`` appends under a line (research R5): additive, never a rewrite."""
    return f"⚠ held: superseded by correction to ch {chapter:03d} — see rebase {rebase_id}"


class CustodySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter: int
    path: str
    role: str  # old | current
    sha256: str
    size: int
    provider: str  # snapshot | git | explicit (the provider that supplied the bytes; "current" is the file itself)
    provider_detail: str


@dataclass
class RebaseState:
    root: Path
    plan: DeltaPlan
    rebase_id: str
    directory: Path
    inspection: dict
    snapshots: list[CustodySnapshot]
    snapshots_sha256: str
    impact: ImpactSet

    def snapshot(self, chapter: int, role: str) -> CustodySnapshot:
        return next(s for s in self.snapshots if s.chapter == chapter and s.role == role)

    @property
    def chapters(self) -> list[int]:
        return sorted({s.chapter for s in self.snapshots})


# --------------------------------------------------------------------------- prepare

def _derive_ids(identity: str, baseline_ref: str, changes, for_plan: str | None) -> tuple[str, str]:
    body = {"kind": "rebase", "campaign_identity": identity, "baseline": baseline_ref, "for_plan": for_plan,
            "sources": [[c, o, n] for c, o, n in sorted(changes)]}
    digest = _canonical_sha(body)[:16]
    return f"plan-{digest}", f"rebase-{digest}"


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise DeltaRefusal(f"source is outside the campaign root: {path} (root {root})", EXIT_USAGE) from exc


def _pending_candidates(root: Path, plan_id: str) -> dict[str, bytes]:
    try:
        pending = load_plan(plans_dir(root), plan_id)
    except DeltaRefusal as exc:
        raise DeltaRefusal(f"--for-plan {plan_id}: {exc.message}", EXIT_USAGE) from exc
    if pending.kind != "delta":
        raise DeltaRefusal(f"--for-plan {plan_id} is itself a rebase plan; name the pending delta plan", EXIT_USAGE)
    directory = grounding_edits.edits_dir(root, plan_id) / "candidates"
    found = {name: (directory / f"{name}.md").read_bytes() for name in baseline_mod.DOCUMENT_NAMES
             if (directory / f"{name}.md").is_file()}
    if not found:
        raise DeltaRefusal(f"plan {plan_id} has no candidate documents yet; run `delta grounding check` first, or "
                           "leave out --for-plan", EXIT_USAGE)
    return found


def prepare(root: Path | str, sources: list[Path], *, models: PlanModels,
            old_bytes: Mapping[int, Path | str] | None = None, for_plan: str | None = None) -> dict:
    """Select stale sources, recover and snapshot their old bytes, and write the rebase plan and records.

    Idempotent: the ids are derived from the inputs, so a re-run with the same inputs writes nothing and
    returns the same ids (``created: false``).
    """
    root = Path(root).absolute()
    if not sources:
        raise DeltaRefusal("no sources selected; a rebase does not default to every stale chapter.", EXIT_USAGE)
    baseline = baseline_mod.bind(root)
    manifest = baseline_mod._read_manifest(root, baseline.generation_id)
    rows = baseline_mod._custody_rows(root, manifest)
    by_path = {rel: (chapter, sha) for chapter, (rel, sha) in rows.items()}
    old_bytes = dict(old_bytes or {})
    selected: dict[int, tuple[str, str, Path]] = {}  # chapter -> (rel, pinned sha, file)
    for source in sources:
        rel = _relative(root, Path(source).absolute())
        if rel not in by_path:
            raise _refuse("REBASE_NOTHING_TO_REBASE", f"{rel} is not pinned by the active generation "
                          f"{baseline.generation_id}; there is no custody pin to rebase.", EXIT_USAGE)
        chapter, pinned = by_path[rel]
        file = root / rel
        if not file.is_file():
            raise _refuse("REBASE_STALE", f"chapter {chapter} ({rel}) is missing from the campaign; restore the "
                          "corrected summary before rebasing.", EXIT_STALE)
        if _sha(file.read_bytes()) == pinned:
            raise _refuse("REBASE_NOTHING_TO_REBASE", f"chapter {chapter} ({rel}) matches its custody pin "
                          f"{pinned[:12]}; there is nothing to rebase.", EXIT_USAGE)
        selected[chapter] = (rel, pinned, file)
    unknown = sorted(set(old_bytes) - set(selected))
    if unknown:
        raise DeltaRefusal(f"--old-bytes names chapter(s) not selected: {', '.join(map(str, unknown))}", EXIT_USAGE)
    changes_key = [(c, selected[c][1], _sha(selected[c][2].read_bytes())) for c in selected]
    identity = campaign_identity(root)
    plan_id, rebase_id = _derive_ids(identity, baseline.ref, changes_key, for_plan)
    directory = rebase_dir(root, rebase_id)
    if (plans_dir(root) / f"{plan_id}-r1.json").is_file() and (directory / "impact.json").is_file():
        state = load_state(root, plan_id)
        return _prepared_record(state, created=False)

    inspection = rebase_inspect.inspect(root, explicit_old=old_bytes)
    snapshots: list[CustodySnapshot] = []
    changes: list[SourceChange] = []
    for chapter in sorted(selected):
        rel, pinned, file = selected[chapter]
        old, provider, detail = custody_store.recover(root, chapter, rel, pinned, old_bytes.get(chapter))
        current = file.read_bytes()
        custody_store.put(root, old)
        custody_store.put(root, current)
        snapshots.append(CustodySnapshot(chapter=chapter, path=rel, role="old", sha256=_sha(old), size=len(old),
                                         provider=provider, provider_detail=detail))
        snapshots.append(CustodySnapshot(chapter=chapter, path=rel, role="current", sha256=_sha(current),
                                         size=len(current), provider="current", provider_detail=rel))
        changes.append(SourceChange(chapter, rel, old, current))
    docs = baseline_mod.baseline_documents(baseline, root)
    pending = _pending_candidates(root, for_plan) if for_plan else None
    impact = compute_impact(root, manifest, docs, changes, pending_candidates=pending)

    plan = create_plan(
        campaign_identity=identity, products=("grounding",), stopping_point="apply",
        source_paths=[selected[c][2] for c in sorted(selected)], models=models,
        chapters={str(selected[c][2]): c for c in selected}, grounding_baseline_ref=baseline.ref,
        campaign_root=root)
    plan = plan.model_copy(update={"plan_id": plan_id, "kind": "rebase", "rebase_id": rebase_id})
    write_json(directory / "inspection.json", inspection.model_dump(mode="json"))
    write_json(directory / "snapshots.json", {"snapshots": [s.model_dump(mode="json") for s in snapshots]})
    write_json(directory / "impact.json", impact.model_dump(mode="json"))
    save_plan(plan, plans_dir(root))  # last: its presence is what marks the rebase as prepared
    return _prepared_record(load_state(root, plan_id), created=True, for_plan=for_plan)


def _prepared_record(state: RebaseState, *, created: bool, for_plan: str | None = None) -> dict:
    impact = state.impact
    return {
        "rebase_id": state.rebase_id, "plan_id": state.plan.plan_id, "created": created,
        "baseline_ref": state.plan.grounding_baseline_ref,
        "sources": [{"chapter": c, "path": state.snapshot(c, "old").path,
                     "old_sha256": state.snapshot(c, "old").sha256,
                     "new_sha256": state.snapshot(c, "current").sha256,
                     "old_bytes_provider": state.snapshot(c, "old").provider} for c in state.chapters],
        "impact": {"affected_lines": len(impact.affected_lines),
                   "affected_annotations": len(impact.affected_annotations),
                   "unknown_members": [m.member for m in impact.unknown_members],
                   "followup_consumers": [f.path for f in impact.followup_consumers],
                   "impact_sha256": impact.impact_sha256},
        "records": {"directory": state.directory.relative_to(state.root).as_posix(),
                    "snapshots_sha256": state.snapshots_sha256},
        "call_counts": {"model": 0}}


# --------------------------------------------------------------------------- load and verify

def load_state(root: Path | str, plan_id: str) -> RebaseState:
    """The rebase a plan belongs to, from its records.  Structural problems refuse; staleness is :func:`stale_reasons`."""
    root = Path(root).absolute()
    plan = load_plan(plans_dir(root), plan_id)
    if plan.kind != "rebase" or not plan.rebase_id:
        raise DeltaRefusal(f"plan {plan_id} is not a rebase plan; create one with `delta rebase prepare`", EXIT_USAGE)
    directory = rebase_dir(root, plan.rebase_id)
    try:
        inspection = read_json(directory / "inspection.json")
        snapshot_bytes = (directory / "snapshots.json").read_bytes()
        snapshots = [CustodySnapshot.model_validate(s) for s in json.loads(snapshot_bytes)["snapshots"]]
        impact = ImpactSet.model_validate(read_json(directory / "impact.json"))
    except (OSError, ValueError, KeyError) as exc:
        raise DeltaRefusal(f"rebase {plan.rebase_id} records are missing or unreadable ({exc}); re-run "
                           "`delta rebase prepare`", EXIT_REFUSAL) from exc
    return RebaseState(root=root, plan=plan, rebase_id=plan.rebase_id, directory=directory, inspection=inspection,
                       snapshots=snapshots, snapshots_sha256=_sha(snapshot_bytes), impact=impact)


def stale_reasons(state: RebaseState) -> list[str]:
    """Everything bound at prepare time that no longer holds (REBASE_STALE), each naming its input."""
    out: list[str] = []
    if impact_digest(state.impact) != state.impact.impact_sha256:
        out.append("the impact record changed since it was written")
    for snap in state.snapshots:
        try:
            if custody_store.get(state.root, snap.sha256) is None:
                out.append(f"custody snapshot {snap.sha256[:12]} (ch {snap.chapter} {snap.role}) is missing")
        except DeltaRefusal as exc:
            out.append(exc.message)
        if snap.role == "current":
            try:
                actual = _sha((state.root / snap.path).read_bytes())
            except OSError:
                actual = "missing"
            if actual != snap.sha256:
                out.append(f"the current bytes of chapter {snap.chapter} ({snap.path}) changed since the rebase "
                           f"was prepared (bound {snap.sha256[:12]}, now {actual[:12]})")
    try:
        active = baseline_mod.bind(state.root).ref
    except DeltaRefusal as exc:
        out.append(f"cannot bind the active baseline: {exc.message}")
    else:
        if active != state.plan.grounding_baseline_ref:
            out.append(f"the active baseline is {active}, not the {state.plan.grounding_baseline_ref} this rebase "
                       "was prepared against")
    return out


def require_fresh(state: RebaseState) -> None:
    reasons = stale_reasons(state)
    if reasons:
        raise _refuse("REBASE_STALE", "; ".join(reasons) + ". Re-run `delta rebase prepare`.", EXIT_STALE)


def baseline_docs(state: RebaseState) -> dict[str, bytes]:
    return baseline_mod.baseline_documents(baseline_mod.bind(state.root), state.root)


# --------------------------------------------------------------------------- repairs

def edits_sha256(root: Path | str, plan_id: str) -> str:
    """Digest of the plan's grounding edit state: the current proposal set and the decisions made on it."""
    try:
        proposals = grounding_edits.load_proposals(root, plan_id)
    except DeltaRefusal:
        return _canonical_sha({"proposals": None, "decisions": {}})
    decisions = grounding_edits.current_decisions(root, plan_id, proposals)
    return _canonical_sha({"proposals": proposals.model_dump(mode="json"),
                           "decisions": {k: v.model_dump(mode="json") for k, v in sorted(decisions.items())}})


def build_repair(docs: Mapping[str, bytes], state: RebaseState, line: AffectedLine, text: str, reason: str, *,
                 origin: str, author: str | None, index: Mapping | None = None) -> grounding_edits.Proposal:
    """A host-built ``source_correction`` proposal for one affected baseline line (exact before = its bytes)."""
    found = index.get(line.line_id) if index is not None else find_line(docs, line.line_id)
    if found is None:
        raise _refuse("REBASE_STALE", f"line {line.line_id} no longer exists in the baseline documents; "
                      "re-run `delta rebase prepare`.", EXIT_STALE)
    document, number, raw = found
    snap = state.snapshot(line.chapter, "old")
    proposal = grounding_edits.make_proposal(
        docs, target_id=grounding_edits.line_target_id(document, number, raw), after_text=text,
        category="source_correction", rationale=reason,
        support=f"correction to ch {line.chapter:03d}: {_diff_ref(state, line.chapter)} (old {snap.sha256[:12]})",
        dependent_checks=["citation"])
    return proposal.model_copy(update={"origin": origin, "author": author,
                                       "hold_marker": hold_marker(line.chapter, state.rebase_id)})


def _diff_ref(state: RebaseState, chapter: int) -> str:
    return next(s.diff_ref for s in state.impact.sources if s.chapter == chapter)


def repair_add(root: Path | str, plan_id: str, line_id: str, text: str, reason: str, reviewer: str) -> dict:
    """A GM-authored repair for one affected baseline line, as a DRAFT grounding edit proposal (origin ``gm``).

    It is approved, rejected or held afterwards with ``delta grounding decide``; nothing is applied here.
    """
    for label, value in (("--line", line_id), ("--text", text), ("--reason", reason), ("--reviewer", reviewer)):
        if not (value or "").strip():
            raise DeltaRefusal(f"{label} is required to record a repair; there is no default", EXIT_USAGE)
    state = load_state(root, plan_id)
    require_fresh(state)
    line = next((l for l in state.impact.affected_lines if l.line_id == line_id), None)
    if line is None:
        raise _refuse("REBASE_UNKNOWN_LINE", f"{line_id} is not an affected line of rebase {state.rebase_id}; "
                      "`delta rebase show` lists them.", EXIT_USAGE)
    if line.origin != "baseline":
        raise _refuse("REBASE_UNKNOWN_LINE", f"{line_id} belongs to a pending plan's candidates, not the baseline "
                      "this rebase edits; it is re-decided after the pending plan is rebound.", EXIT_USAGE)
    docs = baseline_docs(state)
    proposal = build_repair(docs, state, line, text, reason.strip(), origin="gm", author=reviewer.strip())
    saved = grounding_edits.append_proposals(state.root, plan_id, state.plan.grounding_baseline_ref or "", docs,
                                             [proposal])
    return {"plan_id": plan_id, "rebase_id": state.rebase_id, "proposal_id": proposal.proposal_id,
            "target_id": proposal.target_id, "line_id": line_id, "origin": "gm", "status": "draft",
            "proposals_revision": saved.revision, "call_counts": {"model": 0},
            "next": f"delta grounding decide {proposal.proposal_id} --plan {plan_id} "
                    "--decision approve|reject|discuss|hold --reviewer NAME"}


def hold_entry(root: Path | str, plan_id: str, entry_ref: str, reason: str, reviewer: str) -> dict:
    """Hold EVERY affected baseline line that cites one changed entry, as explicit per-line decisions (spec 040).

    ``entry_ref`` is ``CH/ENTRY`` as the lines cite it (``3/003.01``).  The GM names the entry, a reason and a
    reviewer; nothing is implicit.  Only the affected baseline lines citing exactly that chapter and entry are
    touched; a line that already has a proposal (a repair or an earlier decision) is left alone and reported.
    Each held line gets its own proposal and its own ``hold`` decision (one new proposals revision and one new
    decisions revision for the whole batch), and the line ids are listed in the output and in the hold record
    ``holds-r<N>.json`` beside the rebase's decisions.  Nothing here calls a model.
    """
    for label, value in (("--hold-entry", entry_ref), ("--reason", reason), ("--reviewer", reviewer)):
        if not (value or "").strip():
            raise DeltaRefusal(f"{label} is required to hold an entry; there is no default", EXIT_USAGE)
    head, sep, tail = entry_ref.strip().partition("/")
    try:
        chapter = int(head)
    except ValueError:
        chapter = None
    if not sep or chapter is None or not tail.strip():
        raise DeltaRefusal(f"bad --hold-entry {entry_ref!r}; expected CH/ENTRY, for example 3/003.01", EXIT_USAGE)
    entry = tail.strip()
    state = load_state(root, plan_id)
    require_fresh(state)
    wanted = [l for l in state.impact.affected_lines
              if l.origin == "baseline" and l.chapter == chapter and l.entry == entry]
    if not wanted:
        listed = sorted({f"{l.chapter}/{l.entry}" for l in state.impact.affected_lines if l.origin == "baseline"})
        raise _refuse("REBASE_UNKNOWN_ENTRY", f"no affected baseline line cites {chapter}/{entry}; the entries that "
                      f"do are: {', '.join(listed) or 'none'}.", EXIT_USAGE)
    docs = baseline_docs(state)
    index = _line_index(docs)
    try:
        existing = {p.target_id for p in grounding_edits.load_proposals(state.root, plan_id).proposals}
    except DeltaRefusal:
        existing = set()
    why = reason.strip()
    proposals, held, skipped = [], [], []
    for line in wanted:
        found = index.get(line.line_id)
        if found is None:
            raise _refuse("REBASE_STALE", f"line {line.line_id} no longer exists in the baseline documents; re-run "
                          "`delta rebase prepare`.", EXIT_STALE)
        if grounding_edits.line_target_id(found[0], found[1], found[2]) in existing:
            skipped.append(line.line_id)
            continue
        text = found[2].decode("utf-8").rstrip("\r\n")
        proposals.append(build_repair(docs, state, line, text, f"held: {why}", origin="gm", author=reviewer.strip(),
                                      index=index))
        held.append(line.line_id)
    if proposals:
        saved = grounding_edits.append_proposals(state.root, plan_id, state.plan.grounding_baseline_ref or "", docs,
                                                 proposals)
        grounding_edits.decide_many(
            state.root, plan_id,
            {p.proposal_id: ("hold", f"bulk hold of {chapter}/{entry} ({line_id}): {why}")
             for p, line_id in zip(proposals, held)}, reviewer=reviewer.strip())
        revision = saved.revision
    else:
        revision = grounding_edits.load_proposals(state.root, plan_id).revision
    n = len(sorted(state.directory.glob("holds-r*.json"))) + 1
    record = {"rebase_id": state.rebase_id, "plan_id": plan_id, "entry": f"{chapter}/{entry}", "reviewer": reviewer.strip(),
              "reason": why, "held_lines": held, "proposal_ids": [p.proposal_id for p in proposals],
              "skipped_already_proposed": skipped, "proposals_revision": revision,
              "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = state.directory / f"holds-r{n}.json"
    write_json(path, record)
    return {**record, "decision": "hold", "count": len(held), "record": path.relative_to(state.root).as_posix(),
            "call_counts": {"model": 0}}


# --------------------------------------------------------------------------- line state

def _line_index(docs: Mapping[str, bytes]) -> dict[str, tuple[str, int, bytes]]:
    """``line_id -> (document, line_no, line)`` for every line (one pass, so a loop over many lines stays linear)."""
    return {lid: (name, n, raw) for name in docs for lid, n, raw in indexed_lines(name, docs[name])}


def _line_states(state: RebaseState) -> dict[str, dict]:
    """``line_id -> {state, proposal_id}`` for each affected line: unruled | approved | rejected | held | discuss."""
    docs = baseline_docs(state)
    index = _line_index(docs)
    try:
        proposals = grounding_edits.load_proposals(state.root, state.plan.plan_id)
    except DeltaRefusal:
        proposals = None
    decisions = grounding_edits.current_decisions(state.root, state.plan.plan_id, proposals) if proposals else {}
    by_target: dict[str, list] = {}
    for p in (proposals.proposals if proposals else []):
        by_target.setdefault(p.target_id, []).append(p)
    out: dict[str, dict] = {}
    for line in state.impact.affected_lines:
        if line.origin != "baseline":
            out[line.line_id] = {"state": "pending-plan", "proposal_id": None}
            continue
        found = index.get(line.line_id)
        target = grounding_edits.line_target_id(found[0], found[1], found[2]) if found else None
        verdicts = []
        for p in by_target.get(target, []):
            d = decisions.get(p.proposal_id)
            verdicts.append((p.proposal_id, {"approve": "approved", "reject": "rejected", "hold": "held",
                                             "discuss": "discuss"}.get(d.decision if d else "", "unruled")))
        ruled = next(((pid, v) for pid, v in verdicts if v in ("approved", "held")), None)
        pick = ruled or (verdicts[0] if verdicts else (None, "unruled"))
        out[line.line_id] = {"state": pick[1], "proposal_id": pick[0]}
    return out


# --------------------------------------------------------------------------- decide

def _decisions_files(directory: Path) -> list[tuple[int, Path]]:
    found = []
    for p in directory.glob("decisions-r*.json"):
        m = re.fullmatch(r"decisions-r(\d+)\.json", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return sorted(found)


def load_decisions(state: RebaseState, revision: int | None = None) -> dict | None:
    files = _decisions_files(state.directory)
    if not files:
        return None
    if revision is None:
        return read_json(files[-1][1])
    path = dict(files).get(revision)
    return read_json(path) if path else None


def _parse_chapter(key: str) -> int:
    try:
        return int(str(key).strip())
    except ValueError as exc:
        raise DeltaRefusal(f"bad chapter {key!r} in --source-decision; expected CH=DECISION", EXIT_USAGE) from exc


def _describe(lines: list[AffectedLine]) -> str:
    return "; ".join(f"{l.line_id} ({l.document} line {l.line_no}, {l.citation}, {l.reason})" for l in lines)


def check_rulings(state: RebaseState, sources: Mapping[int, str], ruled_members: set[str]) -> None:
    """The FR-009 gate, shared by ``decide`` and the candidate build.

    A semantic change cannot be adopted by hash replacement alone, ``adopt-with-repairs`` needs an approved repair
    or an explicit hold for every affected baseline line, and every unknown-impact member needs a ruling.
    """
    for ch, d in sorted(sources.items()):
        if d == "adopt-unaffected":
            lines, notes = state.impact.lines_of(ch), state.impact.annotations_of(ch)
            if lines or notes:
                raise _refuse(
                    "REBASE_SEMANTIC_CHANGE",
                    f"chapter {ch} changed in a way its citing lines depend on, so it cannot be adopted unaffected. "
                    f"Affected lines: {_describe(lines) or 'none'}. Affected annotations: "
                    f"{', '.join(a.annotation_id for a in notes) or 'none'}. Use adopt-with-repairs (with a repair "
                    "or hold for each line) or reject.")
    line_state = _line_states(state)
    unruled: list[str] = []
    for ch, d in sorted(sources.items()):
        if d != "adopt-with-repairs":
            continue
        for line in state.impact.lines_of(ch, "baseline"):
            if line_state[line.line_id]["state"] not in ("approved", "held"):
                unruled.append(f"ch {ch}: {line.line_id} ({line.document} line {line.line_no}, {line.citation}) is "
                               f"{line_state[line.line_id]['state']}")
    open_members = sorted({m.member for m in state.impact.unknown_members} - ruled_members)
    if open_members:
        unruled.append("unknown-impact member(s) without a ruling: " + ", ".join(open_members))
    if unruled:
        raise _refuse("REBASE_UNRULED_IMPACT", "; ".join(unruled) + ". Approve a repair or hold with `delta "
                      "grounding decide`, and rule every unknown-impact member with --member-decision.")


def decide(root: Path | str, plan_id: str, *, reviewer: str | None, source_decisions: Mapping[int | str, str],
           member_decisions: Mapping[str, str] | None = None, reason: str | None = None) -> dict:
    """Record per-source and per-unknown-member decisions as a NEW ``decisions-r<N>.json`` (append-only)."""
    if not (reviewer or "").strip():
        raise DeltaRefusal("--reviewer is required to record a rebase decision; there is no default reviewer",
                           EXIT_USAGE)
    state = load_state(root, plan_id)
    sources = {_parse_chapter(k): v for k, v in source_decisions.items()}
    members = dict(member_decisions or {})
    for ch, d in sources.items():
        if d not in SOURCE_DECISIONS:
            raise DeltaRefusal(f"chapter {ch}: decision must be one of {', '.join(SOURCE_DECISIONS)} (got {d!r}); "
                               "there is no default", EXIT_USAGE)
    for m, d in members.items():
        if d not in MEMBER_DECISIONS:
            raise DeltaRefusal(f"member {m}: decision must be one of {', '.join(MEMBER_DECISIONS)} (got {d!r})",
                               EXIT_USAGE)
    unselected = sorted(set(sources) - set(state.chapters))
    if unselected:
        raise DeltaRefusal(f"chapter(s) {', '.join(map(str, unselected))} are not part of rebase {state.rebase_id} "
                           f"(selected: {', '.join(map(str, state.chapters))})", EXIT_USAGE)
    unknown_names = {m.member for m in state.impact.unknown_members}
    stray = sorted(set(members) - unknown_names)
    if stray:
        raise DeltaRefusal(f"--member-decision names no unknown-impact member: {', '.join(stray)}", EXIT_USAGE)
    if (not (reason or "").strip()
            and (any(d == "reject" for d in sources.values()) or any(d == "attested-unaffected" for d in members.values()))):
        raise DeltaRefusal("--reason is required for each reject and each attested-unaffected decision", EXIT_USAGE)
    require_fresh(state)

    missing = sorted(set(state.chapters) - set(sources))
    if missing:
        raise DeltaRefusal(f"a decision is required for every selected chapter; missing: "
                           f"{', '.join(map(str, missing))}", EXIT_USAGE)
    check_rulings(state, sources, set(members))
    why = (reason or "").strip() or None
    record = {
        "rebase_id": state.rebase_id, "plan_id": plan_id, "reviewer": reviewer.strip(),
        "sources": {str(ch): {"decision": d, "reason": why if d in REASON_REQUIRED else None}
                    for ch, d in sorted(sources.items())},
        "unknown_members": {m: {"decision": d, "reason": why if d in REASON_REQUIRED else None}
                            for m, d in sorted(members.items())},
        "bound": {"snapshots_sha256": state.snapshots_sha256, "impact_sha256": state.impact.impact_sha256,
                  "baseline_ref": state.plan.grounding_baseline_ref,
                  "edits_sha256": edits_sha256(state.root, plan_id)}}
    files = _decisions_files(state.directory)
    if files:
        latest = read_json(files[-1][1])
        if {k: v for k, v in latest.items() if k not in ("revision", "decided_at")} == record:
            return {**latest, "written": False, "call_counts": {"model": 0}}
    revision = files[-1][0] + 1 if files else 1
    record = {**record, "revision": revision, "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = state.directory / f"decisions-r{revision}.json"
    if path.exists():
        raise DeltaRefusal(f"{path.name} already exists", EXIT_STALE)
    write_json(path, record)
    return {**record, "written": True, "path": path.relative_to(state.root).as_posix(), "call_counts": {"model": 0}}


# --------------------------------------------------------------------------- candidate build (T019)

@dataclass
class RebaseCandidate:
    candidate: dict[str, bytes]
    docs: dict[str, bytes]
    block: RebaseBlock
    decisions: dict
    decisions_path: Path
    chapters: list[int]  # the sources the new generation re-pins (every chapter not rejected)


def current_bound(state: RebaseState) -> dict:
    return {"snapshots_sha256": state.snapshots_sha256, "impact_sha256": state.impact.impact_sha256,
            "baseline_ref": state.plan.grounding_baseline_ref, "edits_sha256": edits_sha256(state.root, state.plan.plan_id)}


def require_decided(state: RebaseState) -> tuple[dict, Path]:
    """The latest decisions, refused (``REBASE_UNRULED_IMPACT``) when missing, stale against what they bound, or incomplete."""
    files = _decisions_files(state.directory)
    if not files:
        raise _refuse("REBASE_UNRULED_IMPACT", f"rebase {state.rebase_id} has no decisions; record them with "
                      f"`delta rebase decide --plan {state.plan.plan_id}`.")
    path = files[-1][1]
    decisions = read_json(path)
    now = current_bound(state)
    changed = sorted(k for k in now if decisions.get("bound", {}).get(k) != now[k])
    if changed:
        raise _refuse("REBASE_UNRULED_IMPACT", f"the decisions in {path.name} are stale: {', '.join(changed)} changed "
                      f"since they were recorded; re-run `delta rebase decide --plan {state.plan.plan_id}`.")
    sources = {int(c): v["decision"] for c, v in decisions["sources"].items()}
    members = set(decisions["unknown_members"])
    if set(sources) != set(state.chapters):
        raise _refuse("REBASE_UNRULED_IMPACT", f"{path.name} does not rule every selected chapter")
    check_rulings(state, sources, members)
    if all(d == "reject" for d in sources.values()):
        raise _refuse("REBASE_UNRULED_IMPACT", "every selected chapter is rejected; there is nothing to rebase")
    return decisions, path


def build_candidate(root: Path | str, plan: DeltaPlan, docs: Mapping[str, bytes] | None = None) -> RebaseCandidate:
    """The bound baseline's four documents with only the approved repairs and holds applied, plus the lineage block."""
    state = load_state(root, plan.plan_id)
    require_fresh(state)
    decisions, path = require_decided(state)
    docs = dict(docs if docs is not None else baseline_docs(state))
    try:
        candidate = grounding_edits.reconstruct_for_plan(state.root, plan.plan_id, docs)
    except DeltaRefusal as exc:
        raise _refuse("REBASE_UNRULED_IMPACT", exc.message) from exc
    line_state = _line_states(state)
    chapters = sorted(int(c) for c, v in decisions["sources"].items() if v["decision"] != "reject")
    block = RebaseBlock(
        rebase_id=state.rebase_id, decisions_ref=path.relative_to(state.root).as_posix(),
        decisions_sha256=_sha(path.read_bytes()),
        sources=[RebaseSource(chapter=c, path=state.snapshot(c, "old").path, old_sha256=state.snapshot(c, "old").sha256,
                              new_sha256=state.snapshot(c, "current").sha256,
                              old_snapshot=custody_store.object_rel(state.snapshot(c, "old").sha256),
                              current_snapshot=custody_store.object_rel(state.snapshot(c, "current").sha256))
                 for c in chapters],
        repaired_lines=sorted(i for i, v in line_state.items() if v["state"] == "approved"),
        held_lines=sorted(i for i, v in line_state.items() if v["state"] == "held"),
        attested_members=sorted(m for m, v in decisions["unknown_members"].items()
                                if v["decision"] == "attested-unaffected"),
        unchanged_members=sorted(f"{n}.md" for n in docs if candidate[n] == docs[n]))
    return RebaseCandidate(candidate=candidate, docs=docs, block=block, decisions=decisions, decisions_path=path,
                           chapters=chapters)


# --------------------------------------------------------------------------- show

def _unified(state: RebaseState, chapter: int) -> str:
    old = custody_store.get(state.root, state.snapshot(chapter, "old").sha256) or b""
    new = custody_store.get(state.root, state.snapshot(chapter, "current").sha256) or b""
    path = state.snapshot(chapter, "old").path
    return "".join(difflib.unified_diff(
        old.decode("utf-8", "replace").splitlines(keepends=True), new.decode("utf-8", "replace").splitlines(keepends=True),
        fromfile=f"{path} (pinned {state.snapshot(chapter, 'old').sha256[:12]})",
        tofile=f"{path} (current {state.snapshot(chapter, 'current').sha256[:12]})"))


def show(root: Path | str, plan_id: str) -> dict:
    """The review data, and ``review.md`` rendered from it.  Reports staleness instead of refusing."""
    state = load_state(root, plan_id)
    stale = stale_reasons(state)
    line_state = _line_states(state)
    latest = load_decisions(state)
    member_rulings = (latest or {}).get("unknown_members", {})
    data = {
        "rebase_id": state.rebase_id, "plan_id": plan_id, "baseline_ref": state.plan.grounding_baseline_ref,
        "stale": stale,
        "sources": [{"chapter": s.chapter, "path": s.path, "old_sha256": s.old_sha256, "new_sha256": s.new_sha256,
                     "old_bytes_provider": state.snapshot(s.chapter, "old").provider,
                     "entries": [e.model_dump(mode="json") for e in s.entries if e.status != "unchanged"],
                     "unchanged_entries": [e.entry for e in s.entries if e.status == "unchanged"],
                     "diff": _unified(state, s.chapter)} for s in state.impact.sources],
        "affected_lines": [{**l.model_dump(mode="json"), **line_state[l.line_id]} for l in state.impact.affected_lines],
        "affected_annotations": [a.model_dump(mode="json") for a in state.impact.affected_annotations],
        "unknown_members": [{**m.model_dump(mode="json"), "ruling": member_rulings.get(m.member)}
                            for m in state.impact.unknown_members],
        "followup_consumers": [f.model_dump(mode="json") for f in state.impact.followup_consumers],
        "decisions": [read_json(p) for _n, p in _decisions_files(state.directory)],
        "bound": {"snapshots_sha256": state.snapshots_sha256, "impact_sha256": state.impact.impact_sha256,
                  "edits_sha256": edits_sha256(state.root, plan_id)},
        "call_counts": {"model": 0}}
    path = state.directory / "review.md"
    atomic_write_text(path, render_review(data))
    data["review"] = path.relative_to(state.root).as_posix()
    return data


def render_review(data: dict) -> str:
    out = [f"# Rebase {data['rebase_id']}", "", f"Plan `{data['plan_id']}`, baseline `{data['baseline_ref']}`.", ""]
    if data["stale"]:
        out += ["## STALE", ""] + [f"- {s}" for s in data["stale"]] + [""]
    for s in data["sources"]:
        out += [f"## Chapter {s['chapter']:03d}: `{s['path']}`", "",
                f"Old bytes from: {s['old_bytes_provider']}. Changed entries: "
                + (", ".join(f"{e['entry']} ({e['status']})" for e in s["entries"]) or "none") + ".", "",
                "```diff", s["diff"].rstrip("\n"), "```", ""]
    out += ["## Affected lines", ""]
    out += [f"- `{l['line_id']}` {l['document']} line {l['line_no']} {l['citation']} "
            f"({l['reason']}, {l['origin']}): **{l['state']}**" for l in data["affected_lines"]] or ["- none"]
    if data["affected_annotations"]:
        out += ["", "## Affected annotations", ""] + [f"- `{a['annotation_id']}` span {a['span']}"
                                                       for a in data["affected_annotations"]]
    out += ["", "## Unknown-impact members (each needs a ruling)", ""]
    out += [f"- `{m['member']}` ({m['reason']}): "
            + (f"{m['ruling']['decision']}" if m["ruling"] else "**unruled**") for m in data["unknown_members"]] or ["- none"]
    out += ["", "## Follow-up consumers (read-only; update after publishing)", ""]
    out += [f"- `{f['path']}` cites ch {', '.join(map(str, f['chapters']))}" for f in data["followup_consumers"]] or ["- none"]
    out += ["", "## Decisions so far", ""]
    for d in data["decisions"]:
        out.append(f"- r{d['revision']} by {d['reviewer']}: "
                   + ", ".join(f"ch {c}={v['decision']}" for c, v in d["sources"].items()))
    if not data["decisions"]:
        out.append("- none")
    return "\n".join(out) + "\n"
