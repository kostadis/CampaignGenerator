"""Tests for dnd_sheet.py's --batch wiring (feature 004-claude-api-batch).

dnd_sheet's docstring says "no vision required": pdf_to_markdown extracts
plain text via PyMuPDF and sends it to Claude as a string, not a multimodal
content-block list (despite stale docs elsewhere describing a vision path).
These tests assert that exact string is what reaches run_single_batch's
`user` param, mirroring what call_api receives on the non-batch path.
extract_text (the actual PyMuPDF call) is monkeypatched out — these tests
are about the --batch routing, not PDF parsing.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipelines.content_ingest import dnd_sheet  # noqa: E402


class FakeCallAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, content, model, *args, **kwargs):
        self.calls.append({"system": system, "content": content, "model": model,
                           "kwargs": kwargs})
        return "# Test Character\n"


class FakeRunSingleBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        return "# Test Character (batched)\n"


class FailingRunSingleBatch:
    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        raise RuntimeError("batch item 'single' did not succeed: status=errored error=boom")


@pytest.fixture
def fake_extract_text(monkeypatch):
    monkeypatch.setattr(dnd_sheet, "extract_text", lambda pdf_path: "RAW SHEET TEXT")


@pytest.fixture
def fake_call_api(monkeypatch, fake_extract_text):
    fake = FakeCallAPI()
    monkeypatch.setattr(dnd_sheet, "call_api", fake)
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)
    return fake


@pytest.fixture
def fake_run_single_batch(monkeypatch, fake_extract_text):
    fake = FakeRunSingleBatch()
    monkeypatch.setattr(dnd_sheet, "run_single_batch", fake)
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)
    return fake


def _write_pdf_stub(tmp_path: Path) -> Path:
    # extract_text is monkeypatched out, so this file's contents never matter —
    # only its existence (main()'s pre-flight check) does.
    p = tmp_path / "soma.pdf"
    p.write_bytes(b"not a real pdf")
    return p


def test_default_path_uses_call_api_unchanged(monkeypatch, fake_call_api, tmp_path):
    """FR-011: no --batch => call_api called with the plain extracted-text
    string as `content`, no explicit max_tokens (its own 8096 default) —
    exactly as before this feature."""
    pdf = _write_pdf_stub(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "dnd_sheet.py", str(pdf), "--output-dir", str(out_dir),
    ])
    dnd_sheet.main()

    assert len(fake_call_api.calls) == 1
    call = fake_call_api.calls[0]
    assert "RAW SHEET TEXT" in call["content"]
    assert isinstance(call["content"], str)
    assert "max_tokens" not in call["kwargs"]
    assert (out_dir / "soma.md").exists()


def test_batch_flag_passes_same_string_payload_as_user(
    monkeypatch, fake_run_single_batch, tmp_path
):
    """The content-block-or-string payload built for call_api's `content` must
    reach run_single_batch unchanged as `user` — today that payload is a
    plain string (PyMuPDF text extraction), not a vision content-block list."""
    pdf = _write_pdf_stub(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "dnd_sheet.py", str(pdf), "--output-dir", str(out_dir), "--batch",
    ])
    dnd_sheet.main()

    assert len(fake_run_single_batch.calls) == 1
    call = fake_run_single_batch.calls[0]
    assert isinstance(call["user"], str)
    assert "RAW SHEET TEXT" in call["user"]
    assert call["max_tokens"] == 8096  # mirrors call_api's own default
    assert (out_dir / "soma.md").read_text(encoding="utf-8").startswith("# Test Character (batched)")


def test_batch_failure_exits_nonzero(monkeypatch, fake_extract_text, tmp_path, capsys):
    pdf = _write_pdf_stub(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(dnd_sheet, "run_single_batch", FailingRunSingleBatch())
    monkeypatch.setattr(dnd_sheet, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", [
        "dnd_sheet.py", str(pdf), "--output-dir", str(out_dir), "--batch",
    ])

    with pytest.raises(SystemExit) as exc_info:
        dnd_sheet.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Error: batch item failed:" in err
