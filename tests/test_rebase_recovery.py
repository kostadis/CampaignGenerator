"""Spec 040 US3 (T029, SC-006): an interrupted rebase apply recovers to exactly one whole-bundle state, and every
identical retry is a no-op.

The same real build as ``tests/test_rebase_stale_boundaries.py`` (stopped before ``grounding apply``).  Failure is
injected only through the promotion layer's own ``fault`` hook, at each of the phases it journals
(``intent``, ``prepared``, ``generation_renamed``, ``receipt``, ``activated``, ``completed``), and recovery is the
existing ``grounding_recovery.recover`` over ``promotion.recovery``.  Nothing is mocked.
"""

from __future__ import annotations

import os

import pytest

from pipelines.summary_native.delta import baseline as bl, grounding_publish as gp, grounding_recovery as gr, rebase
from pipelines.summary_native.promotion import cli as promotion_cli
from tests import _rebase_fixture as rf
from tests._rebase_apply_world import ApplyWorld, build_template
from tests.test_delta_grounding_e2e import run

PRE_ACTIVATION = ("intent", "prepared", "generation_renamed", "receipt")
POST_ACTIVATION = ("activated", "completed")


class InjectedFailure(Exception):
    pass


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    cap = rf.Capture()
    with pytest.MonkeyPatch.context() as mp:
        yield build_template(tmp_path_factory.mktemp("rebase-recovery"), cap, mp)


@pytest.fixture
def w(template: ApplyWorld) -> ApplyWorld:
    return template.reset()


def inject(monkeypatch, point: str) -> None:
    real = promotion_cli.publish_bundle

    def fault(stage: str) -> None:
        if stage == point:
            raise InjectedFailure(point)

    monkeypatch.setattr(promotion_cli, "publish_bundle", lambda *a, **k: real(*a, fault=fault, **k))


def everything(w: ApplyWorld) -> dict[str, str]:
    return rf.sha_tree(w.root, "docs", "config")


def documents(w: ApplyWorld) -> dict[str, bytes]:
    return bl.baseline_documents(bl.bind(w.root), w.root)


def test_the_old_and_new_bundles_differ_in_every_document_the_rebase_changes(w):
    old = documents(w)
    new = w.candidates()
    assert any(new[n] != old[n.removesuffix(".md")] for n in new), "the rebase changes at least one document"


@pytest.mark.parametrize("point", PRE_ACTIVATION)
def test_a_failure_before_activation_recovers_to_the_old_generation(w, monkeypatch, point):
    old_docs = documents(w)
    inject(monkeypatch, point)
    with pytest.raises(InjectedFailure):
        gp.apply(w.plan(), w.preview_sha, campaign_dir=w.root)
    monkeypatch.undo()
    assert w.active() == w.old_generation  # the pointer never moved
    status = gr.recover(w.root, w.plan())
    assert status.state in (gr.ABORTED, gr.COMMITTED) and status.state == gr.ABORTED, status
    assert gr.inspect(w.root, w.plan()).state == gr.ABORTED
    assert w.active() == w.old_generation and documents(w) == old_docs  # whole bundle, the prior one


@pytest.mark.parametrize("point", POST_ACTIVATION)
def test_a_failure_after_the_pointer_swap_recovers_to_the_new_generation(template, monkeypatch, point):
    w = template.reset()
    w.apply()
    clean = documents(w)  # the control: what an uninterrupted apply publishes
    w.reset()
    old_docs = documents(w)
    inject(monkeypatch, point)
    with pytest.raises(InjectedFailure):
        gp.apply(w.plan(), w.preview_sha, campaign_dir=w.root)
    monkeypatch.undo()
    assert gr.inspect(w.root, w.plan()).state == gr.AMBIGUOUS  # commit unknown: apply is never re-run over it
    status = gr.recover(w.root, w.plan())
    assert status.state == gr.COMMITTED, status
    new_docs = documents(w)
    assert w.active() != w.old_generation and new_docs != old_docs
    assert new_docs == clean  # the recovered bundle is the one a clean apply publishes, document for document


@pytest.mark.parametrize("point", PRE_ACTIVATION + POST_ACTIVATION)
def test_each_phase_leaves_exactly_one_of_the_two_whole_states(w, monkeypatch, point):
    old_id, old_docs = w.old_generation, documents(w)
    inject(monkeypatch, point)
    with pytest.raises(InjectedFailure):
        gp.apply(w.plan(), w.preview_sha, campaign_dir=w.root)
    monkeypatch.undo()
    gr.recover(w.root, w.plan())
    active = w.active()
    docs = documents(w)
    is_old, is_new = active == old_id and docs == old_docs, active != old_id and docs != old_docs
    assert is_old != is_new, "exactly one of the old or the new bundle is active"
    assert is_new == (point in POST_ACTIVATION)
    # the pointer, the layout and the members agree on the one generation: no torn mixture
    assert os.readlink(w.root / "docs/grounding/current") == f"generations/{active}/live"
    assert gr.inspect(w.root, w.plan()).state in (gr.COMMITTED, gr.ABORTED)


def test_an_identical_apply_returns_the_original_receipt_and_writes_nothing(w):
    first = w.apply()
    assert first["applied"] is True
    active = w.active()
    before = everything(w)
    again = w.apply()
    assert again["applied"] is True and again["result"]["receipt"] == first["result"]["receipt"]
    assert again["result"]["activation"] == first["result"]["activation"]
    assert w.active() == active and everything(w) == before  # zero writes


def test_an_identical_apply_after_recovery_returns_the_original_receipt(w, monkeypatch):
    inject(monkeypatch, "completed")
    with pytest.raises(InjectedFailure):
        gp.apply(w.plan(), w.preview_sha, campaign_dir=w.root)
    monkeypatch.undo()
    assert gr.recover(w.root, w.plan()).state == gr.COMMITTED
    before = everything(w)
    again = w.apply()
    assert again["result"]["receipt"]["generation_id"] == w.active()
    assert everything(w) == before


def test_an_identical_prepare_and_decide_are_no_ops(w):
    sources = [a for c in (2, 3, 4, 5) for a in ("--source", str(w.fx.paths[c]))]
    before = everything(w)
    with w.cap.active():
        prepared = run(w.cap, w.root, "rebase", "prepare", *sources)["data"]
        assert prepared["plan_id"] == w.plan_id and prepared["created"] is False
        review = run(w.cap, w.root, "rebase", "show", "--plan", w.plan_id)["data"]
        argv = ["rebase", "decide", "--plan", w.plan_id, "--reviewer", "gm", "--reason", "read by the GM"]
        for c in (2, 3, 4, 5):
            argv += ["--source-decision", f"{c}=adopt-with-repairs"]
        for m in review["unknown_members"]:
            argv += ["--member-decision", f"{m['member']}=attested-unaffected"]
        decided = run(w.cap, w.root, *argv)["data"]
    assert decided["written"] is False
    after = everything(w)
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    assert changed == [p for p in changed if p.endswith("review.md")], changed  # `show` re-renders its own view only
    assert rebase.bound_inputs(w.root, w.plan()) == rebase.bound_inputs(w.root, w.plan())


# --------------------------------------------------------------------------- review fixes (4, 5)

def _request(w: ApplyWorld) -> dict:
    import json

    return json.loads((gp.grounding_dir(w.root, w.plan_id) / gp.PUBLISH_REQUEST_FILE).read_text(encoding="utf-8"))


def test_a_committed_request_id_does_not_replay_when_the_staged_content_changed(w):
    from pipelines.summary_native.delta.errors import EXIT_STALE, DeltaRefusal
    from pipelines.summary_native.delta.grounding_candidates import _range_name

    first = w.apply()
    request = _request(w)
    assert gp.default_publisher(w.root, w.plan(), request)["receipt"] == first["result"]["receipt"]  # identical: replay
    range_dir = w.root / request["out_root"] / _range_name(int(request["since"]), int(request["until"]))
    draft = next(p for p in sorted(range_dir.rglob("world_state*.md")))
    draft.write_bytes(draft.read_bytes() + b"\nA line staged after the commit. [ch 002 / 002.01]\n")
    before = everything(w)
    with pytest.raises(DeltaRefusal, match="new --request-id") as raised:
        gp.default_publisher(w.root, w.plan(), request)  # a revised plan reuses the id; it must not get the old receipt
    assert raised.value.exit_code == EXIT_STALE
    assert everything(w) == before


def test_a_corrupt_operation_history_is_a_clean_refusal(w, monkeypatch):
    from pipelines.summary_native.delta.errors import EXIT_RECOVERY, DeltaRefusal
    from pipelines.summary_native.promotion import publish
    from pipelines.summary_native.promotion.errors import PromotionError

    def corrupt(*_a, **_k):
        raise PromotionError("request id has conflicting operation history", code="PROMOTION_HISTORY_INVALID")

    monkeypatch.setattr(publish, "committed_replay", corrupt)
    with pytest.raises(DeltaRefusal, match="PROMOTION_HISTORY_INVALID") as raised:
        gp.default_publisher(w.root, w.plan(), _request(w))
    assert raised.value.exit_code == EXIT_RECOVERY


def test_the_bound_baseline_documents_survive_the_activation_of_the_rebase_generation(w):
    bound = documents(w)
    state = rebase.load_state(w.root, w.plan_id)
    assert rebase.baseline_docs(state) == bound
    w.apply()
    assert documents(w) != bound  # the active baseline moved
    assert rebase.baseline_docs(rebase.load_state(w.root, w.plan_id)) == bound  # the plan still reads ITS baseline
    shown = rebase.show(w.root, w.plan_id)  # reports the staleness instead of failing or re-addressing lines
    assert shown["stale"]


def test_the_receipt_reports_annotations_a_model_was_shown_and_parses_from_records(w):
    import json

    from pipelines.summary_native.delta.receipt import build_rebase_receipt

    w.apply()
    state = rebase.load_state(w.root, w.plan_id)
    (state.directory / "propose-r1.json").write_text(json.dumps({
        "model_calls": 1, "model_input_sources": {"affected_lines": ["world_state#a@1"], "entry_diffs": ["2"],
                                                    "annotations": ["ann-1"]}}), encoding="utf-8")
    receipt = build_rebase_receipt(w.root, w.plan())
    assert receipt.model_input_sources == {"affected_lines": ["world_state#a@1"], "entry_diffs": ["2"],
                                           "annotations": ["ann-1"]}
    assert receipt.parsed_historical == {"selected": [2, 3, 4, 5], "unselected": []}
