"""Rebind a pending delta plan to the generation a source-custody rebase made active (spec 040, T023).

A rebase publishes a new generation whose lineage parent is the generation the pending plan was bound to.
``rebind`` writes plan revision ``r+1`` with that new generation as ``grounding_baseline_ref`` and records, in
``docs/summaries/delta/plans/rebind-<plan>-r<N>.json``, exactly what the move did:

* grounding edits the GM had approved are re-applied onto the new baseline documents when their exact
  ``before`` bytes are still there exactly once and do not overlap a line the rebase held; every other edit is
  marked stale and needs re-deciding (it is never carried on a guess);
* the candidates, the check report, the grounding review bindings and the publication preview are RECORDED as
  invalidated and nothing is deleted: the plan digest they bind has moved, so the existing gates refuse them
  and the operator re-runs ``grounding check``, ``preview``, claims, sign-offs and ``apply``;
* an NPC binding whose plan digest is the old revision's is recorded as carried when the NPC projection of
  the old and new revision is byte-equal (:func:`.review_binding.npc_projection_sha256`); published NPC
  receipts are never touched;
* a run state that belongs to the old revision is re-pointed at the new one, because the run refuses a plan
  that changed under it.

Identical input is a no-op.  No model is called, no file is deleted, no existing generation is written.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import baseline as baseline_mod, grounding_edits, review_binding as rb
from .errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .plan import DeltaPlan, load_plan, plan_digest, plans_dir, revise, save_plan
from .rebase_impact import indexed_lines
from .records_io import read_json, write_json


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _refuse(code: str, message: str, exit_code: int = EXIT_REFUSAL) -> DeltaRefusal:
    return DeltaRefusal(f"{code}: {message}", exit_code)


def record_path(root: Path | str, plan_id: str, revision: int) -> Path:
    return plans_dir(root) / f"rebind-{plan_id}-r{revision}.json"


def rebind_records(root: Path | str, plan_id: str) -> list[dict]:
    """Every rebind record of a plan, oldest first."""
    out = []
    for path in plans_dir(root).glob(f"rebind-{plan_id}-r*.json"):
        if re.fullmatch(re.escape(f"rebind-{plan_id}") + r"-r\d+\.json", path.name):
            out.append(read_json(path))
    return sorted(out, key=lambda r: r["to_revision"])


def carried_plan_digest(root: Path | str, plan: DeltaPlan) -> str:
    """``plan_digest``, except across a rebind whose NPC projection is unchanged: then the digest of the revision
    it was rebound FROM (recursively).  The run keys its census on this, so a rebind does not recompute the census
    and thereby re-draft NPCs that were already published.  A plan never rebound returns its own digest."""
    for record in reversed(rebind_records(root, plan.plan_id)):
        if record["to_revision"] != plan.revision:
            continue
        try:
            older = load_plan(plans_dir(root), plan.plan_id, int(record["from_revision"]))
        except DeltaRefusal:
            break
        if rb.npc_projection_sha256(older) == rb.npc_projection_sha256(plan):
            return carried_plan_digest(root, older)
        break
    return plan_digest(plan)


# --------------------------------------------------------------------------- the child check

def _lineage_of(root: Path, manifest) -> dict | None:
    """The delta lineage record a generation retained (its ``kind: "delta"`` record), or None."""
    generation_dir = (root / manifest.published_path).parent
    for record in manifest.retained_records:
        try:
            payload = json.loads((generation_dir / record.retained_path).read_bytes())
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("kind") == "delta":
            return payload
    return None


def _require_child(root: Path, plan: DeltaPlan, generation: str):
    active = baseline_mod.bind(root)
    if active.generation_id != generation:
        raise _refuse("REBIND_NOT_CHILD", f"generation {generation} is not the active generation "
                      f"({active.generation_id}); a plan can only be rebound to the generation now active.")
    manifest = baseline_mod._read_manifest(root, active.generation_id)
    parent = baseline_mod._delta_parent(root, manifest)
    want = plan.grounding_baseline_ref
    if parent is None or f"{parent.generation_id}@{parent.manifest_sha256}" != want:
        got = "no delta parent" if parent is None else f"parent {parent.generation_id}@{parent.manifest_sha256}"
        raise _refuse("REBIND_NOT_CHILD", f"generation {generation} is not a child of the plan's baseline {want} "
                      f"({got}); only the generation published on top of that baseline can be rebound to.")
    return active, manifest


# --------------------------------------------------------------------------- grounding edits

def _find_target(docs, target_id: str, before_sha256: str):
    """The unique ``(document, start, end)`` in ``docs`` whose exact bytes hash to ``before_sha256``, else why not."""
    m = grounding_edits._TARGET.match(target_id)
    if not m or m["doc"] not in docs:
        return None, "its document is not in the new baseline"
    document = m["doc"]
    width = (int(m["b"]) - int(m["a"]) + 1) if m["b"] else 1
    lines = docs[document].splitlines(keepends=True)
    found = [start for start in range(1, len(lines) - width + 2)
             if _sha(b"".join(lines[start - 1:start - 1 + width])) == before_sha256]
    if not found:
        return None, "its exact before bytes are not in the new baseline"
    if len(found) > 1:
        return None, f"its before bytes appear {len(found)} times in the new baseline, so the target is ambiguous"
    return (document, found[0], found[0] + width - 1), None


def _rebind_edits(root: Path, plan: DeltaPlan, new_ref: str, new_docs, protected: set[str]) -> dict:
    """Re-mint the plan's proposals against ``new_docs``.  Returns ``{reapplied, stale}`` (proposal ids)."""
    try:
        proposals = grounding_edits.load_proposals(root, plan.plan_id)
    except DeltaRefusal:
        return {"reapplied": [], "stale": [], "proposals_revision": None, "reasons": {}}
    if proposals.baseline_ref == new_ref:  # already rebound (a crash left the plan file unwritten): nothing to redo
        return {"reapplied": sorted(p.proposal_id for p in proposals.proposals), "stale": [],
                "proposals_revision": proposals.revision, "reasons": {}}
    decisions = grounding_edits.current_decisions(root, plan.plan_id, proposals)
    index = {n: [(lid, num) for lid, num, _raw in indexed_lines(n, raw)] for n, raw in new_docs.items()}
    minted: list[grounding_edits.Proposal] = []
    carried: dict[str, grounding_edits.DecisionEntry] = {}
    reapplied: list[str] = []
    stale: list[str] = []
    reasons: dict[str, str] = {}
    used: list[tuple[str, int, int]] = []
    for p in proposals.proposals:
        found, why = _find_target(new_docs, p.target_id, p.before_sha256)
        if found is not None:
            document, start, end = found
            ids = {lid for lid, num in index[document] if start <= num <= end}
            if ids & protected:
                found, why = None, "it overlaps a line the rebase held or repaired"
            elif any(d == document and s <= end and start <= e for d, s, e in used):
                found, why = None, "it overlaps another re-applied edit"
        if found is None:
            stale.append(p.proposal_id)
            reasons[p.proposal_id] = why or "unknown"
            continue
        document, start, end = found
        used.append(found)
        raw = new_docs[document].splitlines(keepends=True)
        target = (grounding_edits.line_target_id(document, start, raw[start - 1]) if start == end else
                  f"{document}:L{start}-L{end}:{_sha(raw[start - 1])[:8]}")
        new = p.model_copy(update={"target_id": target, "proposal_id": grounding_edits.proposal_id_for(target, p.after_text)})
        minted.append(new)
        reapplied.append(new.proposal_id)
        if p.proposal_id in decisions:
            carried[new.proposal_id] = decisions[p.proposal_id]
    saved = grounding_edits.save_proposals(root, grounding_edits.ProposalSet(
        plan_id=plan.plan_id, baseline_ref=new_ref, proposals=minted, rejected=[],
        empty_justification=proposals.empty_justification, generated_by=proposals.generated_by))
    if carried:
        previous = grounding_edits.load_decisions(root, plan.plan_id)
        record = grounding_edits.DecisionSet(plan_id=plan.plan_id, proposals_revision=saved.revision,
                                             revision=(previous.revision + 1) if previous else 1, decisions=carried)
        grounding_edits._write_new(grounding_edits.edits_dir(root, plan.plan_id), "decisions", record.revision,
                                   record.model_dump(mode="json"))
    return {"reapplied": sorted(reapplied), "stale": sorted(stale), "proposals_revision": saved.revision,
            "reasons": reasons}


# --------------------------------------------------------------------------- invalidation, NPC, run state

def _invalidated(root: Path, plan: DeltaPlan) -> list[str]:
    """Grounding artifacts bound to the old plan digest and baseline.  Recorded, never deleted."""
    from . import grounding_publish as gp

    base = gp.grounding_dir(root, plan.plan_id)
    out: list[Path] = sorted((base / "candidates").glob("*.md")) if (base / "candidates").is_dir() else []
    out += [base / gp.LINEAGE_FILE] if (base / gp.LINEAGE_FILE).is_file() else []
    checks = sorted(base.glob("check-r*.json"))
    out += checks[-1:]
    out += [base / gp.PREVIEW_FILE] if (base / gp.PREVIEW_FILE).is_file() else []
    for scope in rb.APPROVAL_SCOPES:
        path = rb.binding_path(root, plan.plan_id, "grounding", scope)
        out += [path] if path.is_file() else []
    return [p.relative_to(root).as_posix() for p in out]


def _npc_carried(root: Path, old: DeltaPlan, new: DeltaPlan) -> tuple[list[dict], str]:
    """NPC bindings of the old revision that stay valid, and the byte-equal projection that justifies it."""
    old_proj, new_proj = rb.npc_projection_sha256(old), rb.npc_projection_sha256(new)
    carried: list[dict] = []
    if old_proj != new_proj:
        return carried, new_proj
    old_digest = plan_digest(old)
    for scope in rb.APPROVAL_SCOPES:
        path = rb.binding_path(root, old.plan_id, "npc", scope)
        if path.is_file() and read_json(path).get("plan_sha256") == old_digest:
            carried.append({"scope": scope, "plan_sha256_from": old_digest})
    return carried, new_proj


def _rebind_run_state(root: Path, plan: DeltaPlan, new: DeltaPlan) -> str | None:
    """The run refuses a plan that changed under it, so a run of the old revision follows the plan to the new one."""
    from . import run as run_mod

    path = run_mod.run_path(root, plan.plan_id)
    if not path.is_file():
        return None
    state = run_mod.load_run(path)
    old_ref, new_ref = f"{plan.plan_id}-r{plan.revision}", f"{new.plan_id}-r{new.revision}"
    if state.plan_ref != old_ref:
        return None
    state.plan_ref = new_ref
    run_mod.save_run(state, path)
    return old_ref


# --------------------------------------------------------------------------- the operation

def rebind(root: Path | str, plan_id: str, baseline_generation: str) -> dict:
    """Rebind ``plan_id`` to ``baseline_generation`` (must be active and a child of the plan's baseline)."""
    root = Path(root).absolute()
    if not (baseline_generation or "").strip():
        raise DeltaRefusal("--baseline GENERATION_ID is required; there is no default", EXIT_USAGE)
    plan = load_plan(plans_dir(root), plan_id)
    if plan.kind != "delta":
        raise DeltaRefusal(f"plan {plan_id} is a rebase plan; only a pending delta plan is rebound", EXIT_USAGE)
    active = baseline_mod.bind(root)
    for record in reversed(rebind_records(root, plan_id)):  # identical input is a no-op
        if (record["to_revision"] == plan.revision and record["new_baseline_ref"] == active.ref
                and active.generation_id == baseline_generation):
            return {**record, "written": False, "call_counts": {"model": 0}}
    active, manifest = _require_child(root, plan, baseline_generation)
    lineage = _lineage_of(root, manifest) or {}
    rebase_id = (lineage.get("rebase") or {}).get("rebase_id")
    new_docs = baseline_mod.baseline_documents(active, root)
    block = lineage.get("rebase") or {}
    protected = set(block.get("held_lines", [])) | set(block.get("repaired_lines", []))
    invalidated = _invalidated(root, plan)
    revised = revise(plan, grounding_baseline_ref=active.ref)
    carried, projection = _npc_carried(root, plan, revised)
    edits = _rebind_edits(root, plan, active.ref, new_docs, protected)
    run_from = _rebind_run_state(root, plan, revised)
    record = {
        "plan_id": plan_id, "from_revision": plan.revision, "to_revision": revised.revision,
        "old_baseline_ref": plan.grounding_baseline_ref, "new_baseline_ref": active.ref, "rebase_id": rebase_id,
        "old_plan_sha256": plan_digest(plan), "new_plan_sha256": plan_digest(revised),
        "npc_carried": carried, "npc_projection_sha256": projection,
        "invalidated": invalidated, "reapplied_edits": edits["reapplied"], "stale_edits": edits["stale"],
        "stale_edit_reasons": edits["reasons"], "proposals_revision": edits["proposals_revision"],
        "run_state_rebound_from": run_from,
        "next": f"delta grounding check --plan {plan_id}; then preview, claims, sign-offs and apply (or `delta run resume`)"}
    write_json(record_path(root, plan_id, revised.revision), record)
    save_plan(revised, plans_dir(root))  # last: its presence is what makes the rebind visible
    return {**record, "written": True, "call_counts": {"model": 0}}
