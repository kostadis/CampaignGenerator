"""T071 / FR-019: an ambiguous grounding activation is inspected and recovered by operation identity.

A real delta publication is made, then the durable operation state is rewound to ``activation_pending``
(what a crash between the pointer swap and the commit record leaves).  Resume must reconcile exactly
that operation through ``promotion.recovery`` -- ``grounding apply`` is never re-run over it.
"""

from __future__ import annotations

import json

from pipelines.summary_native.delta import grounding_publish as gp, grounding_recovery as gr, plan as dplan, run as run_mod
from pipelines.summary_native.promotion.models import AttemptState, OperationState
from pipelines.summary_native.promotion.publish import _write_sync
from pipelines.summary_native.review.models import canonical_bytes
from tests.test_delta_grounding_e2e import INHERITED_LINE, NEW_LINE, campaign, publish_delta  # noqa: F401


def test_ambiguous_activation_is_recovered_by_operation_identity_not_rerun(campaign, capsys, monkeypatch):  # noqa: F811
    root, source = campaign
    pid = publish_delta(capsys, root, source, monkeypatch, 4, "r1", "{line}\n" + NEW_LINE + "\n" + INHERITED_LINE)
    plan = dplan.revise(dplan.load_plan(dplan.plans_dir(root), pid), stopping_point="apply")
    dplan.save_plan(plan, dplan.plans_dir(root))
    generations = sorted(p.name for p in (root / "docs/grounding/generations").iterdir())

    done = gr.inspect(root, plan)
    assert done.state == gr.COMMITTED and done.operation_id == f"operation-delta-{pid}"

    # rewind the operation record: activated pointer, no commit
    op = root / "docs/grounding/operations" / done.operation_id
    committed = OperationState.model_validate_json((op / "state.json").read_bytes())
    pending = OperationState(operation_id=committed.operation_id, state=AttemptState.ACTIVATION_PENDING,
                             intent_sha256=committed.intent_sha256,
                             generation_manifest_sha256=committed.generation_manifest_sha256,
                             receipt_candidate_sha256=committed.receipt_candidate_sha256)
    _write_sync(op / "state.json", canonical_bytes(pending))
    ambiguous = gr.inspect(root, plan)
    assert ambiguous.state == gr.AMBIGUOUS and ambiguous.command.endswith(done.operation_id)
    assert run_mod.ambiguous_activation(root, plan) == [f"grounding:{done.operation_id}"]

    def never(*a, **k):
        raise AssertionError("grounding apply must not be re-run over an ambiguous activation")

    monkeypatch.setattr(gp, "apply", never)
    report = run_mod.advance(root, plan, write_receipt=False)
    assert gr.inspect(root, plan).state == gr.COMMITTED
    state = run_mod.load_run(run_mod.run_path(root, plan.plan_id))
    g = next(m for m in state.members if m.subject == "grounding")
    assert g.outcome is run_mod.MemberOutcome.published and report.status is run_mod.RunStatus.complete
    assert report.ambiguous == []
    assert sorted(p.name for p in (root / "docs/grounding/generations").iterdir()) == generations
    assert json.loads((root / "docs/grounding/operations" / done.operation_id / "state.json").read_text())["state"] == "committed"
