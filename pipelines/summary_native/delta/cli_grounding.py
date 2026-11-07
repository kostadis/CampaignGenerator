"""Grounding verbs: ``baseline status|adopt`` and ``grounding propose|decide|check`` (spec 039, T037).

``propose`` and ``check`` are the only verbs here that call a model, and neither applies or approves
anything: proposals are drafts, a check report carries no approval.  Preview and apply live in
``cli_grounding_publish``.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from . import baseline as baseline_mod, grounding_candidates, grounding_check, grounding_edits
from .cli import DELTA_HANDLERS
from .cli_plan import campaign_root, emit, guarded, load_plan_arg
from .errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .plan import DELTA_ROOT_REL, DeltaPlan


def _bound(args: argparse.Namespace, root: Path):
    """The baseline, refusing (exit 3) when a plan pinned a different one."""
    plan = load_plan_arg(args, root) if getattr(args, "plan", None) else None
    baseline = baseline_mod.bind(root)
    if plan is not None and plan.grounding_baseline_ref and plan.grounding_baseline_ref != baseline.ref:
        raise DeltaRefusal(
            f"the active grounding generation changed since the plan was made "
            f"({plan.grounding_baseline_ref} -> {baseline.ref}); re-plan.", EXIT_STALE)
    return plan, baseline


def _source_texts(plan: DeltaPlan) -> dict[str, str]:
    texts: dict[str, str] = {}
    for s in plan.sources:
        data = Path(s.path).read_bytes()
        if hashlib.sha256(data).hexdigest() != s.sha256:
            raise DeltaRefusal(f"source changed since the plan was made: {s.path}; re-plan.", EXIT_STALE)
        texts[s.path] = data.decode("utf-8")
    return texts


def _choice(args: argparse.Namespace, plan: DeltaPlan, which: str) -> tuple[str | None, str]:
    chosen = getattr(plan.models, which)
    return (args.backend or chosen.backend), (args.model or chosen.model)


@guarded
def _baseline_status(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    _plan, baseline = _bound(args, root)
    record = baseline.to_record()
    lines = [f"generation {baseline.generation_id}  status: {baseline.status}"]
    lines += [f"  {d.name}: origin {d.origin_sha256[:12]} live {d.live_sha256[:12]}"
              + ("  DRIFT" if d.origin_sha256 != d.live_sha256 else "") for d in baseline.documents]
    lines += [f"  drift {h.hunk_id}:\n" + h.diff for h in baseline.drift]
    lines += [f"  member {m.name}: coverage_through={m.coverage_through} gaps={m.gaps}" for m in baseline.members]
    return emit(args, record, "\n".join(lines))


@guarded
def _baseline_adopt(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    adoption = baseline_mod.adopt(root, baseline_mod.parse_resolve(args.resolve))
    record = adoption.model_dump(mode="json")
    return emit(args, record, f"adoption r{adoption.revision} recorded for generation {adoption.generation_id}: "
                + (", ".join(f"{d.hunk}={d.disposition}" for d in adoption.drift) or "no drift"))


def baseline_docs_for(root: Path, baseline) -> dict[str, bytes]:
    """The documents a plan edits against (refuses on unreviewed drift)."""
    return baseline_mod.baseline_documents(baseline, root)


@guarded
def _grounding_propose(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    _plan, baseline = _bound(args, root)
    docs = baseline_docs_for(root, baseline)
    backend, model = _choice(args, plan, "generation")
    proposal_set = grounding_edits.propose_edits(
        docs, _source_texts(plan), plan_id=plan.plan_id, baseline_ref=baseline.ref,
        backend=backend, model=model)
    saved = grounding_edits.save_proposals(root, proposal_set)
    record = {"plan_id": plan.plan_id, "revision": saved.revision, "status": "draft",
              "proposals": [p.model_dump() for p in saved.proposals],
              "rejected": [r.model_dump() for r in saved.rejected],
              "empty_justification": saved.empty_justification,
              "call_counts": {"model": 1}, "applied": 0}
    return emit(args, record, f"{len(saved.proposals)} draft proposal(s), {len(saved.rejected)} rejected; "
                "none applied. Decide each with `delta grounding decide`.")


def _plan_for_proposal(root: Path, proposal_id: str) -> str:
    base = root / DELTA_ROOT_REL / "grounding"
    owners = []
    for d in sorted(base.glob("*")) if base.is_dir() else []:
        try:
            if any(p.proposal_id == proposal_id for p in grounding_edits.load_proposals(root, d.name).proposals):
                owners.append(d.name)
        except DeltaRefusal:
            continue
    if len(owners) != 1:
        raise DeltaRefusal(f"cannot tell which plan owns proposal {proposal_id}; pass --plan ID", EXIT_USAGE)
    return owners[0]


@guarded
def _grounding_decide(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan_id = args.plan or _plan_for_proposal(root, args.proposal_id)
    record = grounding_edits.decide(root, plan_id, args.proposal_id, args.decision, args.reason,
                                    reviewer=args.reviewer or "")
    return emit(args, record.model_dump(mode="json"),
                f"decision r{record.revision}: {args.proposal_id} = {args.decision}")


@guarded
def _grounding_check(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    _plan, baseline = _bound(args, root)
    docs = baseline_docs_for(root, baseline)
    candidate = grounding_edits.reconstruct_for_plan(root, plan.plan_id, docs)
    texts = _source_texts(plan)
    new_targets = grounding_check.new_targets_for_sources(
        {s.chapter: texts[s.path] for s in plan.sources})
    report = grounding_check.check_documents(
        docs, candidate, new_targets=new_targets, custody=baseline_mod.custody_resolver(baseline, root))
    calls = 0
    if any(candidate[k] != docs[k] for k in candidate):
        backend, model = _choice(args, plan, "consistency")
        report.findings += grounding_check.propose_consistency_findings(
            docs, candidate, texts, backend=backend, model=model)
        calls = 1
    saved = grounding_check.save_check_report(
        root, plan.plan_id, report,
        candidate_sha256={k: hashlib.sha256(v).hexdigest() for k, v in candidate.items()}, model_calls=calls)
    saved["call_counts"] = {"model": calls}
    lineage = grounding_candidates.materialize(
        root, plan.plan_id, baseline, candidate,
        check_path=Path(saved["path"]).relative_to(root).as_posix(), check_passed=report.passed)
    saved["lineage"] = {m.name: m.mode for m in lineage.members}
    saved["candidates"] = sorted(candidate)
    code = emit(args, saved, f"check {'passed' if report.passed else 'BLOCKED'}: "
                + "; ".join(f"{f.code} {f.document}:{f.line} {f.detail}" for f in report.findings))
    return code if report.passed else EXIT_REFUSAL


DELTA_HANDLERS["baseline status"] = _baseline_status
DELTA_HANDLERS["baseline adopt"] = _baseline_adopt
DELTA_HANDLERS["grounding propose"] = _grounding_propose
DELTA_HANDLERS["grounding decide"] = _grounding_decide
DELTA_HANDLERS["grounding check"] = _grounding_check
