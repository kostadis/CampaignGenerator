"""Feature 003 — the session_doc → platform backend migration.

The interesting case is the one a unit test would not have found and a live run
did: migrating the **backend alone** leaves the platform's Anthropic default
model paired with a local backend. That pair is incompatible, so every service
refuses every run — a campaign that was working before the migration is wholly
blocked after it.

Carrying the model across is not a substitution of the operator's pick (FR-011);
it *is* the operator's pick. Before 003 a Grounding run on dgx took both halves
from `session_doc.yaml` via the cross-service read, so the model that travels
with the backend is the selection that was already in effect.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import yaml

from server.migrate_default_backend import main, read_active_selection


def _campaign(tmp_path: Path, session_doc: str, platform: str | None = None) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "session_doc.yaml").write_text(session_doc, encoding="utf-8")
    if platform is not None:
        (tmp_path / "config" / "platform.yaml").write_text(platform, encoding="utf-8")
    return tmp_path


def _runtime(tmp_path: Path) -> dict:
    raw = yaml.safe_load((tmp_path / "config" / "platform.yaml").read_text(encoding="utf-8"))
    return raw["runtime"]


DGX_DOC = """backends:
  active: dgx
  dgx:
    endpoint: http://spark:8001/v1
    model: Qwen3-Next-80B
"""


def test_carries_the_model_with_the_backend(tmp_path):
    """The defect a live run surfaced: without this, a working DGX campaign is
    blocked on every service the moment it migrates."""
    c = _campaign(tmp_path, DGX_DOC)
    assert main(["--campaign-dir", str(c)]) == 0
    rt = _runtime(c)
    assert rt["default_backend"] == "dgx"
    assert rt["default_model"] == "Qwen3-Next-80B", (
        "migrating the backend without its model leaves an incompatible pair"
    )


def test_a_compatible_platform_model_is_left_alone(tmp_path):
    """An operator who has already set a model the incoming backend can serve
    keeps it — the migration fills a gap, it does not overwrite a choice."""
    c = _campaign(tmp_path, DGX_DOC, platform=(
        "runtime:\n  default_model: Qwen-Chosen-Deliberately\n"
        "  default_backend: anthropic\n  session_dir: null\n"
    ))
    assert main(["--campaign-dir", str(c)]) == 0
    rt = _runtime(c)
    assert rt["default_backend"] == "dgx"
    assert rt["default_model"] == "Qwen-Chosen-Deliberately"


def test_warns_when_no_model_can_be_carried(tmp_path, capsys):
    """A session_doc that names a backend but pins no model for it leaves the
    pair incompatible. That cannot be fixed by migration — inventing a model
    would be the substitution FR-011 forbids — so it is reported loudly
    instead of migrating into a silently broken state."""
    c = _campaign(tmp_path, "backends:\n  active: dgx\n")
    assert main(["--campaign-dir", str(c)]) == 0
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "every run will be refused" in out


def test_session_doc_backends_block_is_preserved(tmp_path):
    """Only the app-wide *role* moves. The block itself remains the Session Doc
    Editor's own override, which it is entitled to keep."""
    c = _campaign(tmp_path, DGX_DOC)
    before = (c / "config" / "session_doc.yaml").read_text(encoding="utf-8")
    main(["--campaign-dir", str(c)])
    assert (c / "config" / "session_doc.yaml").read_text(encoding="utf-8") == before


def test_is_idempotent(tmp_path, capsys):
    c = _campaign(tmp_path, DGX_DOC)
    main(["--campaign-dir", str(c)])
    capsys.readouterr()
    assert main(["--campaign-dir", str(c)]) == 0
    assert "nothing to migrate" in capsys.readouterr().out


def test_dry_run_writes_nothing(tmp_path):
    c = _campaign(tmp_path, DGX_DOC)
    assert main(["--campaign-dir", str(c), "--dry-run"]) == 0
    assert not (c / "config" / "platform.yaml").exists()


def test_no_session_doc_is_a_no_op(tmp_path, capsys):
    (tmp_path / "config").mkdir(parents=True)
    assert main(["--campaign-dir", str(tmp_path)]) == 0
    assert "nothing to migrate" in capsys.readouterr().out


@pytest.mark.parametrize("doc,expected", [
    (DGX_DOC, ("dgx", "Qwen3-Next-80B")),
    ("backends:\n  active: anthropic\n", ("anthropic", None)),
    ("backends:\n  active: bogus\n", (None, None)),
    ("backends: not-a-mapping\n", (None, None)),
    ("not-a-mapping\n", (None, None)),
    ("", (None, None)),
])
def test_read_active_selection_tolerates_malformed_documents(tmp_path, doc, expected):
    """Read raw rather than through SessionEditorConfig: a campaign whose
    document fails strict validation for an unrelated reason should still have
    its backend rescued."""
    p = tmp_path / "session_doc.yaml"
    p.write_text(doc, encoding="utf-8")
    assert read_active_selection(p) == expected
