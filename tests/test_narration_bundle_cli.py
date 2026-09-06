"""CLI orchestration and recovery tests for opt-in bundled narration."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from session_doc import sd_narrate


CORPUS = Path(__file__).parent / "fixtures" / "narration_bundle"


class Recorder:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def stream(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": kwargs.get("max_tokens")})
        if self.error:
            raise self.error
        return self.response

    def batch(self, client, *, system, user, model, max_tokens, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def campaign(tmp_path):
    plan = tmp_path / "plan.md"
    shutil.copyfile(CORPUS / "plan.md", plan)
    recap = tmp_path / "recap.md"
    recap.write_text("# Recap\n", encoding="utf-8")
    raw = tmp_path / "raw"
    shutil.copytree(CORPUS / "raw", raw)
    out = tmp_path / "narration"
    report = tmp_path / "reports" / "test-run.json"
    return {"plan": plan, "recap": recap, "raw": raw, "out": out,
            "report": report}


def _argv(campaign, *extra):
    return [
        "sd_narrate", str(campaign["recap"]),
        "--plan", str(campaign["plan"]),
        "--scene-extractions", str(campaign["raw"]),
        "--per-scene-output", str(campaign["out"]),
        "--run-report", str(campaign["report"]),
        *extra,
    ]


def _run(monkeypatch, campaign, response, *extra, provider_batch=False,
         backend_error=None):
    recorder = Recorder(response=response, error=backend_error)
    clients = []
    monkeypatch.setattr(sd_narrate, "client_from_args",
                        lambda args: clients.append(args) or object())
    monkeypatch.setattr(sd_narrate, "stream_api", recorder.stream)
    monkeypatch.setattr(sd_narrate, "run_single_batch", recorder.batch)
    flags = [*extra]
    if provider_batch:
        flags.append("--batch")
    monkeypatch.setattr(sys, "argv", _argv(campaign, "--batch-scenes", *flags))
    return recorder, clients


@pytest.fixture(autouse=True)
def _isolated_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)


def test_bundle_default_selects_full_plan_and_makes_one_live_exchange(
    monkeypatch, campaign, capsys,
):
    response = (CORPUS / "complete_response.txt").read_text(encoding="utf-8")
    recorder, clients = _run(monkeypatch, campaign, response)

    sd_narrate.main()

    assert len(clients) == 1
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["max_tokens"] == 32000
    assert recorder.calls[0]["user"].index("Scene packet 01") < recorder.calls[0]["user"].index("Scene packet 03")
    files = sorted(campaign["out"].glob("session_doc_scene_*.md"))
    assert [path.name for path in files] == [
        "session_doc_scene_01_arrival.md",
        "session_doc_scene_02_the_bargain.md",
        "session_doc_scene_03_departure.md",
    ]
    assert all("<<<CG-SCENE" not in path.read_text(encoding="utf-8") for path in files)
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert report["status"] == "success"
    assert report["exchange_count"] == 1
    assert report["run_id"] == "test-run"
    assert [item["index"] for item in report["requested"]] == [1, 2, 3]
    out = capsys.readouterr().out
    assert "content mode: bundle" in out
    assert "provider batch: off" in out
    assert "Model exchanges: 1" in out


def test_bundle_provider_batch_is_one_item_not_one_item_per_scene(monkeypatch, campaign):
    response = (CORPUS / "complete_response.txt").read_text(encoding="utf-8")
    recorder, _ = _run(monkeypatch, campaign, response, provider_batch=True)

    sd_narrate.main()

    assert len(recorder.calls) == 1
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert report["provider_batch"] is True
    assert report["exchange_count"] == 1


def test_bundle_subset_is_normalized_to_full_plan_order(monkeypatch, campaign):
    response = """<<<CG-SCENE 01 BEGIN: Arrival>>>
one
<<<CG-SCENE 01 END>>>
<<<CG-SCENE 03 BEGIN: Departure>>>
three
<<<CG-SCENE 03 END>>>"""
    recorder, _ = _run(monkeypatch, campaign, response, "--scene", "3", "1")

    sd_narrate.main()

    prompt = recorder.calls[0]["user"]
    assert prompt.index("Scene packet 01") < prompt.index("Scene packet 03")
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert [item["index"] for item in report["requested"]] == [1, 3]


@pytest.mark.parametrize(
    "flags",
    [
        ("--scene", "1", "1"),
        ("--scene", "4"),
        ("--narrator", "Alice"),
    ],
)
def test_invalid_bundle_selection_refuses_before_client_creation(
    monkeypatch, campaign, flags,
):
    recorder, clients = _run(monkeypatch, campaign, "unused", *flags)

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 1
    assert clients == []
    assert recorder.calls == []


def test_capacity_refusal_is_reported_with_zero_calls(monkeypatch, campaign):
    recorder, clients = _run(
        monkeypatch, campaign, "unused", "--batch-max-tokens", "1000"
    )

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 1
    assert clients == []
    assert recorder.calls == []
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert report["status"] == "refused"
    assert report["exchange_count"] == 0
    assert report["written"] == []
    assert report["rejected"][0]["code"] == "CAPACITY"


def test_repeated_exact_override_is_scoped_and_reported(monkeypatch, campaign, tmp_path):
    overrides = tmp_path / "reviewed"
    overrides.mkdir()
    exact = overrides / "02_the_bargain.md"
    shutil.copyfile(CORPUS / "smoothed" / "02_the_bargain.md", exact)
    response = """<<<CG-SCENE 01 BEGIN: Arrival>>>
one
<<<CG-SCENE 01 END>>>
<<<CG-SCENE 02 BEGIN: The Bargain>>>
two
<<<CG-SCENE 02 END>>>"""
    recorder, _ = _run(
        monkeypatch, campaign, response, "--scene", "2", "1",
        "--scene-extraction-file", str(exact),
    )

    sd_narrate.main()

    assert recorder.calls[0]["user"].count("answered quietly") == 1
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert [item["source_kind"] for item in report["requested"]] == [
        "base", "override"
    ]
    assert report["requested"][1]["source_path"] == str(exact.resolve())


def test_partial_writes_complete_sections_and_preserves_existing_missing_file(
    monkeypatch, campaign,
):
    campaign["out"].mkdir()
    existing = campaign["out"] / "session_doc_scene_02_the_bargain.md"
    existing.write_text("keep this reviewed file\n", encoding="utf-8")
    response = """<<<CG-SCENE 01 BEGIN: Arrival>>>
new one
<<<CG-SCENE 01 END>>>
<<<CG-SCENE 02 BEGIN: The Bargain>>>
<<<CG-SCENE 02 END>>>"""
    recorder, _ = _run(monkeypatch, campaign, response)

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 3
    assert len(recorder.calls) == 1
    assert existing.read_text(encoding="utf-8") == "keep this reviewed file\n"
    assert (campaign["out"] / "session_doc_scene_01_arrival.md").exists()
    assert not (campaign["out"] / "session_doc_scene_03_departure.md").exists()
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert report["status"] == "partial"
    assert [item["index"] for item in report["written"]] == [1]
    assert [(item["index"], item["reason"]) for item in report["missing"]] == [
        (2, "empty"), (3, "absent")
    ]


def test_structurally_valid_zero_write_partial_exits_three(monkeypatch, campaign):
    response = """<<<CG-SCENE 01 BEGIN: Arrival>>>
<<<CG-SCENE 01 END>>>"""
    _run(monkeypatch, campaign, response)

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 3
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert report["written"] == []
    assert [item["index"] for item in report["missing"]] == [1, 2, 3]


def test_unreconcilable_response_writes_nothing(monkeypatch, campaign):
    response = (CORPUS / "malformed_response.txt").read_text(encoding="utf-8")
    _run(monkeypatch, campaign, response)

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 4
    assert not list(campaign["out"].glob("session_doc_scene_*.md"))
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert report["status"] == "unreconcilable"
    assert report["written"] == []


def test_backend_exception_is_caught_and_reported(monkeypatch, campaign):
    recorder, _ = _run(
        monkeypatch, campaign, None, backend_error=RuntimeError("boom")
    )

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 1
    assert len(recorder.calls) == 1
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["exchange_count"] == 1
    assert report["rejected"][0]["code"] == "BACKEND"


def test_backend_initialization_exception_is_reported_before_exchange(
    monkeypatch, campaign,
):
    recorder = Recorder(response="unused")
    monkeypatch.setattr(
        sd_narrate, "client_from_args",
        lambda _args: (_ for _ in ()).throw(RuntimeError("cannot initialize")),
    )
    monkeypatch.setattr(sd_narrate, "stream_api", recorder.stream)
    monkeypatch.setattr(sys, "argv", _argv(campaign, "--batch-scenes"))

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 1
    assert recorder.calls == []
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["exchange_count"] == 0
    assert report["written"] == []
    assert report["rejected"][0]["code"] == "BACKEND"


@pytest.mark.parametrize(
    ("flag", "code"),
    [
        ("--party", "PARTY_UNREADABLE"),
        ("--examples", "EXAMPLES_DIRECTORY_NOT_FOUND"),
        ("--context", "CONTEXT_NOT_FOUND"),
    ],
)
def test_bundle_input_refusals_finalize_report_before_client_creation(
    monkeypatch, campaign, tmp_path, flag, code,
):
    missing = tmp_path / "missing-input"
    recorder, clients = _run(
        monkeypatch, campaign, "unused", flag, str(missing)
    )

    with pytest.raises(SystemExit) as exc:
        sd_narrate.main()

    assert exc.value.code == 1
    assert clients == []
    assert recorder.calls == []
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert report["status"] == "refused"
    assert report["exchange_count"] == 0
    assert report["rejected"][0]["code"] == code
