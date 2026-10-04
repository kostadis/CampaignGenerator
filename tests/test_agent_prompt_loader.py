"""Tests for campaignlib.load_agent_prompt — Phase 1 of SessionDocRefactor."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import campaignlib  # noqa: E402
from campaignlib import _clear_prompt_cache, load_agent_prompt  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """The loader caches by absolute path; isolate every test."""
    _clear_prompt_cache()
    yield
    _clear_prompt_cache()


def _write(base: Path, name: str, body: str) -> Path:
    p = base / "config" / "agents" / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_from_base_dir(tmp_path):
    _write(tmp_path, "consistency", "Hello from the override.")
    assert load_agent_prompt("consistency", base_dir=tmp_path) == \
        "Hello from the override."


def test_base_dir_override_wins_over_shipped_default(tmp_path):
    override = tmp_path / "campaign"
    _write(override, "plan", "OVERRIDE copy")
    assert load_agent_prompt("plan", base_dir=override) == "OVERRIDE copy"


def test_falls_back_to_packaged_default(tmp_path):
    empty_override = tmp_path / "campaign"
    empty_override.mkdir()
    assert load_agent_prompt("session_doc/narrate/base", base_dir=empty_override).strip()


def test_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        load_agent_prompt("nope", base_dir=tmp_path / "campaign")
    msg = str(exc.value)
    assert "nope" in msg
    assert "Looked in:" in msg
    assert "campaignlib.resources/agents/nope.md" in msg


def test_cache_separates_campaign_override_from_packaged_default(tmp_path):
    name = "session_doc/narrate/base"
    shipped = load_agent_prompt(name, base_dir=tmp_path)
    _write(tmp_path, name, "OVERRIDE")
    assert load_agent_prompt(name, base_dir=tmp_path) == "OVERRIDE"
    assert shipped != "OVERRIDE"


def test_no_placeholders_returns_template_verbatim(tmp_path):
    _write(tmp_path, "raw", "Plain prose. No substitution wanted.")
    assert load_agent_prompt("raw", base_dir=tmp_path) == \
        "Plain prose. No substitution wanted."


def test_placeholders_substituted_when_complete(tmp_path):
    _write(tmp_path, "with_subs", "Hello {who} from {where}.")
    out = load_agent_prompt(
        "with_subs",
        base_dir=tmp_path,
        placeholders={"who": "Brewbarry", "where": "Phandalin"},
    )
    assert out == "Hello Brewbarry from Phandalin."


def test_missing_placeholder_raises_value_error(tmp_path):
    _write(tmp_path, "needs_two", "{a} and {b}")
    with pytest.raises(ValueError) as exc:
        load_agent_prompt("needs_two", base_dir=tmp_path, placeholders={"a": "x"})
    msg = str(exc.value)
    assert "needs_two" in msg
    assert "'b'" in msg


def test_extra_placeholder_raises_value_error(tmp_path):
    _write(tmp_path, "needs_one", "Just {a}.")
    with pytest.raises(ValueError) as exc:
        load_agent_prompt(
            "needs_one", base_dir=tmp_path,
            placeholders={"a": "x", "stray": "y"},
        )
    msg = str(exc.value)
    assert "needs_one" in msg
    assert "'stray'" in msg


def test_cache_reuses_loaded_content(tmp_path):
    p = _write(tmp_path, "cached", "first version")
    first = load_agent_prompt("cached", base_dir=tmp_path)
    p.write_text("second version", encoding="utf-8")
    second = load_agent_prompt("cached", base_dir=tmp_path)
    assert first == second == "first version"
    _clear_prompt_cache()
    assert load_agent_prompt("cached", base_dir=tmp_path) == "second version"


def test_nested_name_resolves_to_subdir(tmp_path):
    # Phase 2 needs `session_doc/narrate/base` etc. — exercise the path here.
    (tmp_path / "config" / "agents" / "session_doc" / "narrate").mkdir(parents=True)
    (tmp_path / "config" / "agents" / "session_doc" / "narrate" / "base.md").write_text(
        "nested ok", encoding="utf-8"
    )
    assert load_agent_prompt("session_doc/narrate/base", base_dir=tmp_path) == \
        "nested ok"


def test_cwd_used_when_base_dir_unset(tmp_path, monkeypatch):
    cwd_root = tmp_path / "cwd"
    _write(cwd_root, "cwd_only", "loaded from CWD")
    monkeypatch.chdir(cwd_root)

    assert load_agent_prompt("cwd_only") == "loaded from CWD"
