import json
import shutil
from pathlib import Path

from tests.narration_wiki_helpers import final_json, run_cli
from tests.test_narration_wiki_collect import _scope as uncollected_scope
from tests.test_narration_wiki_patches import PROPOSALS, accepted_scope
from tests.test_narration_wiki_storage import prepared_scope


def _args(scope, command):
    return (
        command,
        "--campaign-dir", str(scope.campaign_root),
        "--session-dir", str(scope.session_root),
        "--iteration-id", scope.iteration_id,
        "--json",
    )


def test_status_is_one_json_object_and_read_only(tmp_path):
    scope = prepared_scope(tmp_path)
    before = {path: path.read_bytes() for path in scope.iteration_root.rglob("*") if path.is_file()}
    result = run_cli(*_args(scope, "status"))
    assert result.returncode == 0, result.stderr
    payload = final_json(result)
    assert payload["ok"] is True and payload["command"] == "status"
    assert before == {path: path.read_bytes() for path in before}


def test_cli_refuses_empty_scope_and_uses_contract_exit_code(tmp_path):
    result = run_cli("status", "--campaign-dir", "", "--session-dir", "", "--iteration-id", "", "--json")
    assert result.returncode == 2
    assert final_json(result)["ok"] is False


def test_index_check_returns_validation_category_without_success_shape(tmp_path):
    scope = prepared_scope(tmp_path)
    result = run_cli(*_args(scope, "index-check"))
    payload = final_json(result)
    assert result.returncode in {0, 5}
    assert payload["ok"] is (result.returncode == 0)


def test_cli_completes_collection_baseline_conflict_and_gate1(tmp_path):
    scope = uncollected_scope(tmp_path)
    for command in (
        _args(scope, "collect"),
        (*_args(scope, "measure"), "--phase", "before"),
    ):
        result = run_cli(*command)
        assert result.returncode == 0, result.stderr
        assert final_json(result)["ok"] is True
    fixture = Path(__file__).parent / "fixtures" / "narration_wiki" / "gate1"
    (scope.iteration_root / "drafts").mkdir()
    (scope.iteration_root / "conflict-drafts").mkdir()
    shutil.copy2(fixture / "distinct-bookkeeping.md", scope.iteration_root / "drafts" / "distinct-bookkeeping.md")
    shutil.copy2(fixture / "seed-voice.json", scope.iteration_root / "conflict-drafts" / "seed-voice.json")
    conflict = run_cli(
        *_args(scope, "conflict-rule"), "--conflict-id", "seed-voice",
        "--resolution", "Use campaign source", "--rationale", "The campaign owns named guidance",
    )
    assert conflict.returncode == 0, conflict.stderr
    pattern = run_cli(
        *_args(scope, "pattern-rule"), "--pattern-slug", "distinct-bookkeeping",
        "--decision", "accept", "--tier", "campaign",
    )
    assert pattern.returncode == 0, pattern.stderr
    assert (scope.campaign_wiki_root / "patterns" / "distinct-bookkeeping.md").is_file()


def test_cli_completes_atomic_proposal_rejection(tmp_path):
    scope = accepted_scope(tmp_path)
    staged = run_cli(
        *_args(scope, "proposal-stage"), "--proposal-id", "proposal-001",
        "--draft", "incoming/proposal.yaml",
    )
    assert staged.returncode == 0, staged.stderr
    applied = run_cli(*_args(scope, "proposal-apply"), "--proposal-id", "proposal-001")
    assert applied.returncode == 0, applied.stderr
    after = run_cli(
        *_args(scope, "measure"), "--phase", "after", "--proposal-id", "proposal-001",
    )
    assert after.returncode == 0, after.stderr
    ruled = run_cli(
        *_args(scope, "proposal-rule"), "--proposal-id", "proposal-001", "--decision", "reject",
    )
    assert ruled.returncode == 0, ruled.stderr
    assert final_json(ruled)["decision"] == "reject"


def test_status_carries_the_measurement_and_the_staged_diff(tmp_path):
    """The Gate panels read from status, so status has to supply what they show.

    The page bound a measurement table and a diff pane to fields the CLI never
    emitted: the table always read "no measurement has been persisted yet" and
    the diff pane never left its placeholder, while the e2e fixture supplied
    both and passed.
    """
    scope = accepted_scope(tmp_path)
    payload = final_json(run_cli(*_args(scope, "status")))
    assert payload["measurement_phase"] == "before"
    assert {row["key"] for row in payload["measurement_checks"]} == {
        "shape_of", "portable_portrait", "taxonomy", "filing_sections", "bookkeeping_per_narrator", "em_dash",
    }
    # Occurrence rows are dropped so the bounded status envelope stays small.
    assert all("occurrences" not in row for row in payload["measurement_checks"])
    assert payload["staged_diff"] is None and payload["staged_diff_truncated"] is False

    staged = run_cli(
        *_args(scope, "proposal-stage"),
        "--proposal-id", "proposal-001",
        "--draft", "incoming/proposal.yaml",
    )
    assert staged.returncode == 0, staged.stderr
    payload = final_json(run_cli(*_args(scope, "status")))
    diff = (scope.iteration_root / "proposals" / "proposal-001" / "change.diff").read_text()
    assert payload["staged_diff"] == diff
    assert payload["staged_diff_truncated"] is False


def test_recover_is_reachable_and_resolves_a_written_journal(tmp_path):
    """Recovery had no caller: a stuck iteration reported needs_attention forever.

    _status re-implemented a read-only view of the same journals and told the GM
    to inspect hashes, but no command performed the repair.
    """
    scope = prepared_scope(tmp_path)
    ruled = run_cli(
        *_args(scope, "conflict-rule"),
        "--conflict-id", "seed-voice",
        "--resolution", "Use campaign source",
        "--rationale", "The campaign owns named guidance",
    )
    assert ruled.returncode == 0, ruled.stderr
    journal = sorted((scope.iteration_root / "transactions").glob("*.json"))[0]
    value = json.loads(journal.read_text())
    value["state"] = "target_done"
    value["next_action"] = "verify_targets"
    journal.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")

    assert final_json(run_cli(*_args(scope, "status")))["recovery"] is not None
    recovered = run_cli(*_args(scope, "recover"))
    assert recovered.returncode == 0, recovered.stderr
    payload = final_json(recovered)
    assert payload["resolved"] is True and payload["outstanding"] is None
    assert json.loads(journal.read_text())["state"] == "committed"
    assert final_json(run_cli(*_args(scope, "status")))["recovery"] is None
