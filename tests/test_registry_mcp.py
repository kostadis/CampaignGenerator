"""Tests for entity_registry/registry_mcp.py — the registry MCP server.

Mirrors test_kanka_mcp.py's split: the core functions (registry_add,
registry_alias, ...) are pure wrappers around entity_registry.registry.main()
and are exercised directly against a real temp registry, no `mcp` package
needed. build_server()'s tool registration is checked separately, gated on
`mcp` actually being installed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from entity_registry import registry_mcp as rm


# ── _run_main safety guarantees ──────────────────────────────────────────────

def test_run_main_converts_argparse_systemexit_to_error_code():
    # Missing required --name/--type would call parser.error() -> sys.exit(2);
    # this must never propagate out and kill the server process.
    out, err, code = rm._run_main(["add", "/nonexistent"])
    assert code == 2
    assert "required" in err.lower()


def test_run_main_raises_loud_on_unexpected_input_call(tmp_path):
    # If some code path ever calls input() without an explicit canned answer,
    # that must fail loud (RuntimeError propagating out, becoming an MCP tool
    # error), never hang on the MCP transport's own stdin. add's near-miss
    # branch is the only real input() call site; hit it via _run_main without
    # input_response.
    rm.registry_init(tmp_path)
    rm.registry_add(tmp_path, "Kazryn Nyantani", "npc")
    with pytest.raises(RuntimeError, match="unexpectedly prompted for input"):
        rm._run_main(["add", str(tmp_path), "--name", "Kazryn Nyantany", "--type", "npc"])


# ── registry_init / registry_add ─────────────────────────────────────────────

def test_init_then_add(tmp_path):
    msg = rm.registry_init(tmp_path, campaign="test-camp")
    assert "Wrote" in msg

    msg = rm.registry_add(tmp_path, "Kazryn Nyantani", "npc", aliases=["Nyantani"])
    assert "Added 'Kazryn Nyantani'" in msg


def test_add_exact_collision_fails_outright(tmp_path):
    rm.registry_init(tmp_path)
    rm.registry_add(tmp_path, "Kazryn Nyantani", "npc", aliases=["Nyantani"])

    out = rm.registry_add(tmp_path, "Nyantani", "npc")
    assert out.startswith("FAILED")
    assert "identity collision" in out


def test_add_near_miss_writes_nothing_and_explains_next_steps(tmp_path):
    rm.registry_init(tmp_path)
    rm.registry_add(tmp_path, "Kazryn Nyantani", "npc")

    out = rm.registry_add(tmp_path, "Kazryn Nyantany", "npc")
    assert "looks similar to existing name" in out
    assert "confirm_new=true" in out
    assert "registry_alias" in out

    # Nothing written — a second identical add still reports the same near-miss,
    # not an existing-entity conflict.
    out2 = rm.registry_add(tmp_path, "Kazryn Nyantany", "npc")
    assert "looks similar to existing name" in out2


def test_add_confirm_new_bypasses_near_miss(tmp_path):
    rm.registry_init(tmp_path)
    rm.registry_add(tmp_path, "Kazryn Nyantani", "npc")

    out = rm.registry_add(tmp_path, "Kazryn Nyantany", "npc", confirm_new=True)
    assert "Added 'Kazryn Nyantany'" in out


# ── registry_alias / registry_merge ─────────────────────────────────────────

def test_alias_attaches_variant(tmp_path):
    rm.registry_init(tmp_path)
    rm.registry_add(tmp_path, "Kazryn Nyantani", "npc")

    out = rm.registry_alias(tmp_path, "Kazryn Nyantani", ["Kazryn"])
    assert "Attached ['Kazryn']" in out


def test_alias_refuses_variant_owned_by_different_entity(tmp_path):
    rm.registry_init(tmp_path)
    rm.registry_add(tmp_path, "Kazryn Nyantani", "npc")
    rm.registry_add(tmp_path, "Someone Else", "npc", aliases=["Kazryn"])

    out = rm.registry_alias(tmp_path, "Kazryn Nyantani", ["Kazryn"])
    assert out.startswith("FAILED")
    assert "already belongs to a different entity" in out


def test_merge_folds_entities(tmp_path):
    rm.registry_init(tmp_path)
    rm.registry_add(tmp_path, "Foo Bar", "npc")
    rm.registry_add(tmp_path, "Foo Baz", "npc", confirm_new=True)

    out = rm.registry_merge(tmp_path, "Foo Bar", ["Foo Baz"])
    assert "Merged ['Foo Baz'] into 'Foo Bar'" in out


def test_merge_refuses_across_distinct_guard(tmp_path):
    rm.registry_init(tmp_path)
    rm.registry_add(tmp_path, "Topsy", "npc")
    rm.registry_add(tmp_path, "Turvy", "npc", confirm_new=True)
    rm.registry_mark_distinct(tmp_path, "Topsy", "Turvy")

    out = rm.registry_merge(tmp_path, "Topsy", ["Turvy"])
    assert out.startswith("FAILED")
    assert "marked distinct" in out


# ── registry_mark_distinct / registry_mark_rejected ─────────────────────────

def test_mark_distinct_and_mark_rejected(tmp_path):
    rm.registry_init(tmp_path)
    out = rm.registry_mark_distinct(tmp_path, "Topsy", "Turvy")
    assert "Marked 'Topsy' and 'Turvy' as distinct" in out

    out = rm.registry_mark_rejected(tmp_path, ["Alpha", "Beta"])
    assert "Marked ['Alpha', 'Beta'] as a rejected alias group" in out


# ── registry_check / registry_triage_candidates / registry_project ─────────

def test_check_on_clean_registry_reports_none(tmp_path):
    rm.registry_init(tmp_path)
    rm.registry_add(tmp_path, "Kazryn Nyantani", "npc")

    out = rm.registry_check(tmp_path)
    assert "Grouping drift" in out
    assert "Summary: 0 grouping-drift" in out


def test_triage_candidates_returns_parsed_json(tmp_path):
    rm.registry_init(tmp_path, campaign="test-camp")

    out = rm.registry_triage_candidates(tmp_path)
    assert '"campaign": "test-camp"' in out
    assert '"candidates": []' in out
    assert "triage-candidates: 0 candidate(s)" in out


def test_project_writes_projection_files(tmp_path):
    rm.registry_init(tmp_path)
    rm.registry_add(tmp_path, "Kazryn Nyantani", "npc")

    out = rm.registry_project(tmp_path)
    assert "Wrote" in out
    assert (tmp_path / "docs" / "aliases.json").is_file()
    assert (tmp_path / "docs" / "entity_inventory.md").is_file()


# ── build_server (requires the `mcp` package) ───────────────────────────────

def test_build_server_registers_every_subcommand_as_a_tool(tmp_path):
    pytest.importorskip("mcp")
    import asyncio

    server = rm.build_server(tmp_path)
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}

    expected = {
        "registry_init_tool", "registry_add_tool", "registry_alias_tool",
        "registry_merge_tool", "registry_mark_distinct_tool", "registry_mark_rejected_tool",
        "registry_project_tool", "registry_check_tool", "registry_triage_candidates_tool",
        "registry_import_inventory_tool", "registry_import_dedup_tool",
        "registry_import_frontmatter_tool", "registry_import_alias_decisions_tool",
    }
    assert names == expected


def test_resolve_campaign_dir_prefers_env_over_arg_over_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("CAMPAIGN_DIR", raising=False)
    assert rm.resolve_campaign_dir(["prog", "--campaign-dir", str(tmp_path)]) == tmp_path.resolve()

    env_dir = tmp_path / "from-env"
    env_dir.mkdir()
    monkeypatch.setenv("CAMPAIGN_DIR", str(env_dir))
    assert rm.resolve_campaign_dir(["prog", "--campaign-dir", str(tmp_path)]) == env_dir.resolve()
