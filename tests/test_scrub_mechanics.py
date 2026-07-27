"""Tests for session_doc/scrub_mechanics.py's --batch wiring.

scrub_mechanics.py runs one stream_api call per scene file over a glob of
independent files. With --batch, all files fan out as one grouped run_batch
call (custom_id = file stem); each success is written through the same
finalize_scrub_response() helper the serial path uses (so files land
byte-identical), a partial failure prints FAILED lines and leaves the
process exiting non-zero while successful files stay on disk, and the
default (no --batch) path is unaffected by the plumbing.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from session_doc import scrub_mechanics  # noqa: E402


# ── Fakes ──────────────────────────────────────────────────────────────────

class FakeStreamAPI:
    """Callable stub for scrub_mechanics.stream_api."""

    def __init__(self, response="<prose>cleaned prose</prose>"):
        self.calls = []
        self._response = response

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": kwargs.get("max_tokens")})
        return self._response


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(scrub_mechanics, "stream_api", fake)
    return fake


class FakeRunBatch:
    """Callable stub for scrub_mechanics.run_batch: records requests and
    returns a results dict keyed by custom_id.

    `text_by_id` supplies per-file response text (default a generic
    <prose> block naming the custom_id, so distinct files produce distinct
    output); `status_by_id` overrides specific custom_ids to simulate
    partial failure (error message is always "boom", matching the
    established FakeRunBatch convention elsewhere in this test suite).
    """

    def __init__(self, text_by_id=None, status_by_id=None):
        self.calls = []
        self._text_by_id = text_by_id or {}
        self._status_by_id = status_by_id or {}

    def __call__(self, client, requests, **kwargs):
        self.calls.append({"requests": requests, "kwargs": kwargs})
        results = {}
        for r in requests:
            cid = r["custom_id"]
            status = self._status_by_id.get(cid, "succeeded")
            if status == "succeeded":
                text = self._text_by_id.get(cid, f"<prose>cleaned {cid}</prose>")
                results[cid] = {"status": "succeeded", "text": text,
                                "stop_reason": "end_turn", "error": None, "usage": None}
            else:
                results[cid] = {"status": status, "text": None,
                                "stop_reason": None, "error": "boom", "usage": None}
        return results


@pytest.fixture
def fake_run_batch(monkeypatch):
    fake = FakeRunBatch()
    monkeypatch.setattr(scrub_mechanics, "run_batch", fake)
    return fake


def _write_scene(tmp_path: Path, name: str, body: str = "raw mechanical text") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


# ── scrub_batch: request shape ─────────────────────────────────────────────

def test_batch_submits_one_request_per_file_with_stem_custom_ids(fake_run_batch, tmp_path):
    targets = [
        _write_scene(tmp_path, "session_doc_scene_01.md", "body one"),
        _write_scene(tmp_path, "session_doc_scene_02.md", "body two"),
        _write_scene(tmp_path, "session_doc_scene_03.md", "body three"),
    ]

    any_failed = scrub_mechanics.scrub_batch(
        targets, client=None, system_prompt="SYS", model="m",
        max_tokens=16000, dry_run=False, save_scan=False,
    )

    assert any_failed is False
    assert len(fake_run_batch.calls) == 1  # one grouped call, not N serial ones
    requests = fake_run_batch.calls[0]["requests"]
    assert [r["custom_id"] for r in requests] == [
        "session_doc_scene_01", "session_doc_scene_02", "session_doc_scene_03",
    ]
    assert all(r["params"]["model"] == "m" for r in requests)
    assert all(r["params"]["max_tokens"] == 16000 for r in requests)


def test_batch_excludes_empty_body_files_from_requests(fake_run_batch, tmp_path):
    _write_scene(tmp_path, "session_doc_scene_01.md", "real body")
    empty = _write_scene(tmp_path, "session_doc_scene_02.md", "---\nscene: x\n---\n\n")
    targets = [tmp_path / "session_doc_scene_01.md", empty]

    scrub_mechanics.scrub_batch(
        targets, client=None, system_prompt="SYS", model="m",
        max_tokens=16000, dry_run=False, save_scan=False,
    )

    ids = [r["custom_id"] for r in fake_run_batch.calls[0]["requests"]]
    assert ids == ["session_doc_scene_01"]  # empty-body file never submitted


def test_batch_all_empty_reports_error_and_never_calls_run_batch(fake_run_batch, tmp_path):
    empty = _write_scene(tmp_path, "session_doc_scene_01.md", "---\nscene: x\n---\n\n")

    any_failed = scrub_mechanics.scrub_batch(
        [empty], client=None, system_prompt="SYS", model="m",
        max_tokens=16000, dry_run=False, save_scan=False,
    )

    assert any_failed is True
    assert len(fake_run_batch.calls) == 0


# ── scrub_batch: successes written byte-identical to the serial path ──────

def test_batch_and_serial_paths_write_byte_identical_scrubbed_files(
    monkeypatch, tmp_path
):
    body = "---\nscene: Scene A\n---\n\nraw mechanical text here"
    response = "<prose>The party crept through the ruined hall.</prose>"

    serial_path = _write_scene(tmp_path, "session_doc_scene_01.md", body)
    monkeypatch.setattr(scrub_mechanics, "stream_api", FakeStreamAPI(response=response))
    scrub_mechanics.scrub_one(serial_path, client=None, system_prompt="SYS", model="m",
                              max_tokens=16000, dry_run=False, save_scan=False)
    serial_out = serial_path.with_suffix(".scrubbed.md")

    batch_path = _write_scene(tmp_path, "session_doc_scene_02.md", body)
    fake = FakeRunBatch(text_by_id={"session_doc_scene_02": response})
    monkeypatch.setattr(scrub_mechanics, "run_batch", fake)
    scrub_mechanics.scrub_batch([batch_path], client=None, system_prompt="SYS", model="m",
                                max_tokens=16000, dry_run=False, save_scan=False)
    batch_out = batch_path.with_suffix(".scrubbed.md")

    assert serial_out.exists() and batch_out.exists()
    assert serial_out.read_bytes() == batch_out.read_bytes()


def test_batch_write_uses_atomic_write_text(monkeypatch, tmp_path):
    recorded = []

    def fake_atomic_write(path, text):
        recorded.append(Path(path))
        Path(path).write_text(text, encoding="utf-8")

    monkeypatch.setattr(scrub_mechanics, "atomic_write_text", fake_atomic_write)
    fake = FakeRunBatch(text_by_id={
        "session_doc_scene_01": "<prose>clean</prose>",
    })
    monkeypatch.setattr(scrub_mechanics, "run_batch", fake)

    target = _write_scene(tmp_path, "session_doc_scene_01.md", "body")
    scrub_mechanics.scrub_batch([target], client=None, system_prompt="SYS", model="m",
                                max_tokens=16000, dry_run=False, save_scan=False)

    assert recorded == [target.with_suffix(".scrubbed.md")]


# ── scrub_batch: partial failure ──────────────────────────────────────────

def test_batch_partial_failure_prints_failed_line_and_keeps_successes_on_disk(
    monkeypatch, tmp_path, capsys
):
    ok = _write_scene(tmp_path, "session_doc_scene_01.md", "body one")
    bad = _write_scene(tmp_path, "session_doc_scene_02.md", "body two")

    fake = FakeRunBatch(status_by_id={"session_doc_scene_02": "errored"})
    monkeypatch.setattr(scrub_mechanics, "run_batch", fake)

    any_failed = scrub_mechanics.scrub_batch(
        [ok, bad], client=None, system_prompt="SYS", model="m",
        max_tokens=16000, dry_run=False, save_scan=False,
    )

    assert any_failed is True
    err = capsys.readouterr().err
    assert "FAILED session_doc_scene_02: errored boom" in err

    assert ok.with_suffix(".scrubbed.md").exists()          # success stays on disk
    assert not bad.with_suffix(".scrubbed.md").exists()      # failure never written


# ── main(): end-to-end batch wiring ───────────────────────────────────────

@pytest.fixture
def fake_prompt_path(monkeypatch, tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("SYSTEM PROMPT", encoding="utf-8")
    monkeypatch.setattr(scrub_mechanics, "resolve_prompt_path", lambda: prompt)
    return prompt


def test_main_batch_flag_routes_through_run_batch_and_exits_zero_on_success(
    monkeypatch, fake_prompt_path, fake_run_batch, tmp_path
):
    scene_dir = tmp_path / "narration"
    scene_dir.mkdir()
    _write_scene(scene_dir, "session_doc_scene_01.md", "body one")
    _write_scene(scene_dir, "session_doc_scene_02.md", "body two")

    monkeypatch.setattr(scrub_mechanics, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", ["scrub_mechanics.py", str(scene_dir), "--batch"])

    rc = scrub_mechanics.main()

    assert rc == 0
    assert len(fake_run_batch.calls) == 1
    assert (scene_dir / "session_doc_scene_01.scrubbed.md").exists()
    assert (scene_dir / "session_doc_scene_02.scrubbed.md").exists()


def test_main_batch_flag_partial_failure_exits_nonzero(
    monkeypatch, fake_prompt_path, tmp_path
):
    scene_dir = tmp_path / "narration"
    scene_dir.mkdir()
    _write_scene(scene_dir, "session_doc_scene_01.md", "body one")
    _write_scene(scene_dir, "session_doc_scene_02.md", "body two")

    fake = FakeRunBatch(status_by_id={"session_doc_scene_02": "errored"})
    monkeypatch.setattr(scrub_mechanics, "run_batch", fake)
    monkeypatch.setattr(scrub_mechanics, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", ["scrub_mechanics.py", str(scene_dir), "--batch"])

    rc = scrub_mechanics.main()

    assert rc == 1
    assert (scene_dir / "session_doc_scene_01.scrubbed.md").exists()
    assert not (scene_dir / "session_doc_scene_02.scrubbed.md").exists()


# ── Default (no --batch) path is unaffected ───────────────────────────────

def test_default_no_batch_path_uses_stream_api_serially(
    monkeypatch, fake_prompt_path, fake_stream_api, tmp_path
):
    scene_dir = tmp_path / "narration"
    scene_dir.mkdir()
    _write_scene(scene_dir, "session_doc_scene_01.md", "body one")
    _write_scene(scene_dir, "session_doc_scene_02.md", "body two")

    monkeypatch.setattr(scrub_mechanics, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", ["scrub_mechanics.py", str(scene_dir)])

    rc = scrub_mechanics.main()

    assert rc == 0
    assert len(fake_stream_api.calls) == 2  # one call per file, serially
    assert (scene_dir / "session_doc_scene_01.scrubbed.md").exists()
    assert (scene_dir / "session_doc_scene_02.scrubbed.md").exists()


def test_default_no_batch_path_never_touches_run_batch(
    monkeypatch, fake_prompt_path, fake_stream_api, fake_run_batch, tmp_path
):
    scene_dir = tmp_path / "narration"
    scene_dir.mkdir()
    _write_scene(scene_dir, "session_doc_scene_01.md", "body one")

    monkeypatch.setattr(scrub_mechanics, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", ["scrub_mechanics.py", str(scene_dir)])

    scrub_mechanics.main()

    assert len(fake_run_batch.calls) == 0
    assert len(fake_stream_api.calls) == 1
