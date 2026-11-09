"""Completion receipt (spec 039 data-model Receipt).

Contains no capability URLs, tokens or secrets (FR-023): the model forbids extra
fields and a test asserts no field name looks like one.  No model call is made here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pipelines.summary_native.scheduler import atomic_write_record, read_record

from .errors import DeltaRefusal

SCHEMA_VERSION = 1


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    selected_chapters: list[int] = Field(default_factory=list)
    inherited_coverage_and_gaps: dict[str, Any] = Field(default_factory=dict)
    changed: list[str] = Field(default_factory=list)
    new: list[str] = Field(default_factory=list)
    carried: list[str] = Field(default_factory=list)
    held: list[str] = Field(default_factory=list)
    publication_hashes: dict[str, str] = Field(default_factory=dict)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)  # each carries its revision
    read_counts: dict[str, int] = Field(default_factory=dict)
    call_counts: dict[str, int] = Field(default_factory=dict)
    recovery_state: str | None = None


class RebaseReceipt(Receipt):
    """Spec 040 data-model RebaseReceipt: the delta receipt plus what a source-custody rebase did and did NOT read.

    ``integrity_reads`` (every pinned source hashed), ``parsed_historical`` (what was parsed for impact: the
    selected chapters, and, separately, any unselected one), ``cached_evidence_reused``, ``model_input_sources``
    (what a model was ever shown), ``model_calls``, ``unselected_stale_remaining`` and ``followup_consumers`` are
    reported separately and never summed into one count.
    """

    rebase_id: str
    sources_and_decisions: list[dict[str, Any]] = Field(default_factory=list)
    integrity_reads: int = 0
    parsed_historical: dict[str, Any] = Field(default_factory=dict)
    cached_evidence_reused: int = 0
    model_input_sources: dict[str, Any] = Field(default_factory=dict)
    model_calls: int = 0
    unselected_stale_remaining: list[int] = Field(default_factory=list)
    followup_consumers: list[str] = Field(default_factory=list)
    new_generation_ref: str | None = None
    parent_generation_ref: str | None = None


def save_receipt(receipt: Receipt, path: Path | str) -> None:
    atomic_write_record(Path(path), receipt.model_dump(mode="json"))


def load_receipt(path: Path | str) -> Receipt:
    record = read_record(Path(path))
    record.pop("schema", None)
    if record.get("schema_version") != SCHEMA_VERSION:
        raise DeltaRefusal(f"unsupported receipt schema_version {record.get('schema_version')!r}")
    return (RebaseReceipt if "rebase_id" in record else Receipt).model_validate(record)


def build_receipt(campaign_dir: Path | str, plan, state) -> Receipt:
    """The completion receipt, derived from the plan, the run state and the records on disk (FR-024).

    No url, token or secret is read into it: only hashes, subjects, counts and decision revisions.
    """
    from . import associations, census as census_mod, npc_update, run as run_mod, sources as sources_mod
    from .cli_plan import selection_path

    root = Path(campaign_dir)
    outcomes = {m.subject: m for m in state.members}
    dispositions: dict[str, str] = {}
    unresolved: list[str] = []
    try:
        census = census_mod.load_census(root, plan.plan_id)
        dispositions = census.dispositions()
        unresolved = [e.subject for e in census.entries if e.disposition == "unresolved"]
    except DeltaRefusal:
        pass
    changed = sorted(s for s, d in dispositions.items() if d == "changed" and s in outcomes
                     and outcomes[s].outcome.value == "published")
    new = sorted(s for s, d in dispositions.items() if d == "new" and s in outcomes
                 and outcomes[s].outcome.value == "published")
    carried = sorted(s for s, m in outcomes.items() if m.outcome.value == "unchanged")
    held = sorted(s for s, m in outcomes.items() if m.outcome.value in ("held", "rejected", "failed"))

    hashes: dict[str, str] = {}
    for m in state.members:
        if m.receipt_ref and m.outcome.value == "published":
            try:
                rec = json.loads((root / m.receipt_ref).read_text(encoding="utf-8"))
                hashes[m.subject] = rec.get("target_sha256") or rec.get("body_sha256") or ""
            except (OSError, ValueError):
                pass

    inherited: dict[str, Any] = {"grounding_baseline_ref": plan.grounding_baseline_ref, "npc_horizons": {},
                                 "missing_scope": [], "unresolved": unresolved}
    checks: list[dict[str, Any]] = []
    reads: dict[str, int] = {}
    sel = selection_path(root, plan.plan_id)
    if sel.is_file():
        reads.update(sources_mod.load_selection(sel).read_counts)
    try:
        st = npc_update.load_state(root, plan.plan_id)
        inherited["npc_horizons"] = {m["subject"]: m["horizon"] for m in st["members"]}
        reads.update({f"npc_{k}": v for k, v in st.get("read_counts", {}).items()})
        nd = npc_update.delta_dir(root, plan.plan_id)
        for m in st["members"]:
            vj = nd / f"{m['stem']}.verify.json"
            if vj.is_file():
                rec = json.loads(vj.read_text(encoding="utf-8"))
                checks.append({"subject": m["subject"], "verdict": rec.get("verdict"),
                               "evidence_kind": rec.get("evidence_kind"), "draft_sha256": rec.get("draft_sha256")})
                inherited["missing_scope"] += [f"{m['subject']}: {x}" for x in rec.get("missing_scope", [])]
    except DeltaRefusal:
        pass

    decisions: list[dict[str, Any]] = []
    try:
        for a in associations.load_store(root, plan.plan_id).associations:
            for h in a.history:
                decisions.append({"kind": "association", "id": a.id, "decision": h.get("decision"),
                                  "revision": h.get("revision")})
    except DeltaRefusal:
        pass

    if run_mod.ambiguous_members(root, plan.plan_id) or run_mod.ambiguous_activation(root, plan):
        recovery = "required"
    elif any(json.loads(p.read_text(encoding="utf-8")).get("reconciled")
             for p in (npc_update.receipts_dir(root, plan.plan_id).glob("*.json")
                       if npc_update.receipts_dir(root, plan.plan_id).is_dir() else [])
             if not p.name.endswith(".intent.json")):
        recovery = "recovered"
    else:
        recovery = "none"
    return Receipt(
        selected_chapters=sorted(s.chapter for s in plan.sources), inherited_coverage_and_gaps=inherited,
        changed=changed, new=new, carried=carried, held=held, publication_hashes=dict(sorted(hashes.items())),
        checks=checks, decisions=decisions, read_counts=reads,
        call_counts={"model": state.counts.model_calls, "checks": state.counts.checks},
        recovery_state=recovery)


def write_receipt(campaign_dir: Path | str, plan, state) -> Path:
    """Build and atomically write ``receipt.json``; returns its path."""
    from .run import receipt_path

    path = receipt_path(campaign_dir, plan.plan_id)
    save_receipt(build_receipt(campaign_dir, plan, state), path)
    return path


def _count_cached(value: Any) -> int:
    """Claims runs a report says were served from cache (extraction reuse by input digest)."""
    if isinstance(value, dict):
        return sum(1 for k, v in value.items() if k == "cached" and v is True) + sum(
            _count_cached(v) for v in value.values())
    if isinstance(value, list):
        return sum(_count_cached(v) for v in value)
    return 0


def build_rebase_receipt(campaign_dir: Path | str, plan) -> RebaseReceipt:
    """The completion receipt of an APPLIED rebase, from its records and the active generation (spec 040 T022).

    Refuses until the rebase's generation is the active one and its lineage parent is the plan's baseline.
    """
    from . import baseline as baseline_mod, grounding_publish as gp, rebase as rebase_mod, rebase_inspect
    from .errors import EXIT_REFUSAL
    from .records_io import read_json

    root = Path(campaign_dir).absolute()
    state = rebase_mod.load_state(root, plan.plan_id)
    active = baseline_mod.bind(root)
    manifest = baseline_mod._read_manifest(root, active.generation_id)
    parent = baseline_mod._delta_parent(root, manifest)
    if parent is None or f"{parent.generation_id}@{parent.manifest_sha256}" != plan.grounding_baseline_ref:
        raise DeltaRefusal(f"rebase {state.rebase_id} is not applied: the active generation {active.generation_id} "
                           f"is not a child of {plan.grounding_baseline_ref}; run `delta grounding apply` first",
                           EXIT_REFUSAL)
    lineage = json.loads((gp.grounding_dir(root, plan.plan_id) / "lineage.json").read_text(encoding="utf-8"))
    block = lineage.get("rebase") or {}
    decisions = read_json(root / block["decisions_ref"])
    kept = {s["chapter"]: s for s in block.get("sources", [])}
    rows = []
    for chapter in state.chapters:
        old, new = state.snapshot(chapter, "old"), state.snapshot(chapter, "current")
        verdict = decisions["sources"][str(chapter)]
        rows.append({"chapter": chapter, "path": old.path, "old_sha256": old.sha256, "new_sha256": new.sha256,
                     "decision": verdict["decision"], "reason": verdict.get("reason"),
                     "old_bytes_provider": old.provider, "rebased": chapter in kept})
    proposals = sorted(state.directory.glob("propose-r*.json"))
    model_calls, shown = 0, {"affected_lines": [], "entry_diffs": []}
    for path in proposals:
        rec = read_json(path)
        model_calls += int(rec.get("model_calls", 0))
        for key in shown:
            shown[key] = sorted(set(shown[key]) | set((rec.get("model_input_sources") or {}).get(key, [])))
    request = json.loads((gp.grounding_dir(root, plan.plan_id) / gp.PUBLISH_REQUEST_FILE).read_text(encoding="utf-8"))
    cached, claims_report = 0, request.get("check_report")
    if claims_report and (root / claims_report).is_file():
        try:
            cached = _count_cached(json.loads((root / claims_report).read_text(encoding="utf-8")))
        except ValueError:
            cached = 0
    check_calls = 0
    for path in sorted(gp.grounding_dir(root, plan.plan_id).glob("check-r*.json")):
        check_calls += int(read_json(path).get("model_calls", 0))
    parsed = sorted(s.chapter for s in state.impact.sources)
    remaining = [e.chapter for e in rebase_inspect.inspect(root).stale]
    return RebaseReceipt(
        rebase_id=state.rebase_id, selected_chapters=sorted(kept),
        inherited_coverage_and_gaps={"grounding_baseline_ref": plan.grounding_baseline_ref, "npc_horizons": {},
                                     "missing_scope": [], "unresolved": []},
        held=sorted(block.get("held_lines", [])), publication_hashes={"grounding": active.manifest_sha256},
        decisions=[{"kind": "rebase", "id": state.rebase_id, "decision": "decided",
                    "revision": decisions["revision"], "reviewer": decisions["reviewer"]}],
        read_counts={"integrity_reads": state.inspection.get("integrity_reads", 0)},
        call_counts={"model": model_calls + check_calls}, recovery_state="none",
        sources_and_decisions=rows, integrity_reads=int(state.inspection.get("integrity_reads", 0)),
        parsed_historical={"selected": parsed, "unselected": sorted(set(parsed) - set(state.chapters))},
        cached_evidence_reused=cached,
        model_input_sources=shown, model_calls=model_calls + check_calls,
        unselected_stale_remaining=remaining,
        followup_consumers=[f.path for f in state.impact.followup_consumers],
        new_generation_ref=active.ref, parent_generation_ref=f"{parent.generation_id}@{parent.manifest_sha256}")


def write_rebase_receipt(campaign_dir: Path | str, plan) -> Path:
    """Build and atomically write the rebase plan's ``receipt.json``; returns its path."""
    from .run import receipt_path

    path = receipt_path(campaign_dir, plan.plan_id)
    save_receipt(build_rebase_receipt(campaign_dir, plan), path)
    return path
