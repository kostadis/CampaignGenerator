"""``delta review show`` and ``delta review handoff`` (spec 039 T063, Story 3).

``show`` prints the one review document (:mod:`diff_view`) and, under ``--json``, the bindings next to
it.  ``handoff`` creates ONE combined review for the plan's changed and new NPC drafts -- reusing prior
exact-draft sign-offs whose bytes are unchanged -- and records a publication-scope
:class:`~.review_binding.ReviewBinding` per product.  Neither verb approves anything, and neither makes
a model call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from campaignlib.util import atomic_write_text

from . import diff_view, review_binding as rb
from .cli import DELTA_HANDLERS
from .cli_plan import campaign_root, emit, guarded, load_plan_arg
from .errors import EXIT_OK, EXIT_REFUSAL, EXIT_USAGE, DeltaRefusal
from .plan import DeltaPlan, chapter_of

SCOPE = "publication"


def _binding_record(binding: rb.ReviewBinding | None) -> dict | None:
    return None if binding is None else binding.model_dump(mode="json")


def _dossiers(root: Path, plan: DeltaPlan) -> tuple[list[dict], list[str], dict]:
    """One selection entry per drafted member. Each is verified against the member's OWN recorded spans
    (sparse evidence); the summary paths are custody only, limited to the span source files, so no
    chapter outside the selection is parsed or listed (SC-001, FR-004)."""
    from pipelines.summary_native import npc_authored, npc_compose
    from . import npc_baseline, npc_update
    from .records_io import read_json

    state = npc_update.load_state(root, plan.plan_id)
    rdir = npc_baseline.npc_root_for(root) / state["range"]
    out, slugs = [], []
    reads = {"parsed_new": 0, "parsed_historical": 0, "reused_artifact": 0, "model_input": 0}
    custody_seen: set[str] = set()
    for m in sorted(state["members"], key=lambda r: r["slug"]):
        stem = m["stem"]
        draft, evidence = rdir / "draft" / f"{stem}.md", rdir / "evidence" / f"{stem}.md"
        if not draft.is_file() or not evidence.is_file():
            raise DeltaRefusal(f"{m['subject']}: draft or evidence pack is missing; run `delta npc draft`",
                               EXIT_REFUSAL)
        spans_file = npc_update.delta_dir(root, plan.plan_id) / f"{stem}.spans.json"
        if not spans_file.is_file():
            raise DeltaRefusal(f"{m['subject']}: the recorded evidence spans are missing; run `delta npc draft`",
                               EXIT_REFUSAL)
        sparse = npc_update.sparse_from_json(read_json(spans_file))
        evidence_rel = evidence.relative_to(root).as_posix()
        paths = sorted({sp.source_path for sp in sparse.spans if sp.source_path != evidence_rel})
        for sp in sparse.spans:
            key = f"{sp.source_path}"
            if key not in custody_seen:
                custody_seen.add(key)
                reads["parsed_new" if sp.origin == "new" else "reused_artifact"] += 1
        out.append({"id": stem, "npc": m["subject"],
                    "draft_path": draft.relative_to(root).as_posix(),
                    "evidence_path": evidence_rel,
                    "summary_paths": paths, "sparse_evidence": sparse,
                    "manual": npc_authored.load_manual(npc_compose.authored_path_for(root, m["subject"]),
                                                       m["subject"])})
        slugs.append(m["slug"])
    return out, slugs, reads


def _chapter(path: Path) -> int | None:
    try:
        return chapter_of(path)
    except DeltaRefusal:
        return None


def _handoff_npc(root: Path, plan: DeltaPlan) -> dict:
    from pipelines.summary_native.review.cli import _create_combined_dossier_handoff
    from pipelines.summary_native.review.store import ReviewStoreError

    dossiers, slugs, reads = _dossiers(root, plan)
    try:
        created = _create_combined_dossier_handoff(root, dossiers)
    except ReviewStoreError as exc:
        raise DeltaRefusal(f"cannot create the review: {exc}", EXIT_REFUSAL) from exc
    decisions, reviewer = rb.decisions_from_review(root, created["review_id"], signoffs_only=True, members=slugs)
    # FR-014: record the dependency digests the GM is about to review -- for members with no current approval
    # only. A member approved earlier keeps the digests recorded then, so a change made after its sign-off
    # (composition, authored file, registry, players, thread, canon, association) leaves it stale.
    from . import npc_update

    approved = {d.member for d in decisions if d.decision == "approve"}
    recorded = npc_update.graph_recorded(root, plan.plan_id)
    stems = {m["slug"]: m["stem"] for m in npc_update.load_state(root, plan.plan_id)["members"]}
    to_record = [s for s in slugs if s not in approved or stems[s] not in recorded]
    npc_update.rerecord_freshness(root, plan, to_record)
    graph = npc_update.load_graph(root, plan.plan_id)
    digests = npc_update.current_digests(root, plan.plan_id, graph)
    stale = {s: graph.item_stale(stems[s], digests) for s in slugs}
    binding = rb.make_binding(root, plan, "npc", SCOPE, members=slugs, review_id=created["review_id"],
                              reviewer=reviewer, decisions=decisions)
    path = rb.save_binding(root, binding)
    return {"read_counts": reads, "stale_signoffs": {s: r for s, r in stale.items() if r and s in approved},
            "freshness_recorded": sorted(to_record),
            "review_id": created["review_id"], "carried": created["carried"],
            "carried_from": created["carried_from"], "needs_review": created["needs_review"],
            "binding": str(path), "members": slugs}


def _handoff_grounding(root: Path, plan: DeltaPlan) -> dict:
    from . import grounding_publish as gp

    _c, _l, request = gp.load_inputs(root, plan.plan_id)
    review_id = (json.loads(request) if request else {}).get("review")
    if not review_id:
        raise DeltaRefusal("publish_request.json names no document review; run `delta grounding preview "
                           "--review ID` with the four-document review first", EXIT_USAGE)
    decisions, reviewer = rb.decisions_from_review(root, review_id)
    binding = rb.make_binding(root, plan, "grounding", SCOPE, review_id=review_id, reviewer=reviewer,
                              decisions=decisions)
    return {"review_id": review_id, "binding": str(rb.save_binding(root, binding))}


@guarded
def _show(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    text = diff_view.render(root, plan)
    path = rb.document_path(root, plan.plan_id)
    atomic_write_text(path, text)
    if not args.json:
        print(text, end="")
        return EXIT_OK
    bindings = {p: _binding_record(rb.load_binding(root, plan.plan_id, p, SCOPE)) for p in plan.products}
    return emit(args, {"plan_id": plan.plan_id, "document_path": str(path),
                       "document_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                       "document": text, "bindings": bindings, "call_counts": {"model": 0}}, "")


@guarded
def _handoff(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    out: dict = {}
    if "npc" in plan.products:
        out["npc"] = _handoff_npc(root, plan)
    if "grounding" in plan.products:
        out["grounding"] = _handoff_grounding(root, plan)
    text = "\n".join(
        f"{p}: review {v['review_id']}"
        + (f"; {len(v['carried'])} sign-off(s) reused, {len(v['needs_review'])} need review" if p == "npc" else "")
        for p, v in sorted(out.items()))
    return emit(args, {"plan_id": plan.plan_id, "handoff": out, "call_counts": {"model": 0}}, text)


DELTA_HANDLERS["review show"] = _show
DELTA_HANDLERS["review handoff"] = _handoff
