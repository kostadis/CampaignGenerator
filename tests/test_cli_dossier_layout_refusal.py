"""Every CLI that loads the alias map turns a layout refusal into ``Error:`` + exit 1 (spec 032 FR-022c).

Not a traceback, and the message carries the migration command.
"""

from __future__ import annotations

import sys

import pytest

from campaignlib import load_alias_map_or_exit


def _unmigrated(tmp_path):
    npcs = tmp_path / "docs" / "npcs"
    npcs.mkdir(parents=True)
    (npcs / "loose.md").write_text("not published\n", encoding="utf-8")
    inp = tmp_path / "in.md"
    inp.write_text("# Chapter 1\nstuff\n", encoding="utf-8")
    return npcs, inp


def _cases():
    from pipelines.grounding import campaign_state, distill, party
    from session_doc import scene_extract, sd_narrate

    def distill_argv(d, inp, t):
        return distill, ["distill", str(inp), "-o", str(t / "out.md"), "--dossier-dir", d]

    def state_argv(d, inp, t):
        return campaign_state, ["campaign_state", str(inp), "-o", str(t / "out.md"), "--dossier-dir", d]

    def party_argv(d, inp, t):
        return party, ["party", "-o", str(t / "out.md"), "--dossier-dir", d, "--summaries", str(inp)]

    return {"distill": distill_argv, "campaign_state": state_argv, "party": party_argv}


@pytest.mark.parametrize("name", ["distill", "campaign_state", "party"])
def test_cli_refuses_without_a_traceback(tmp_path, monkeypatch, capsys, name):
    npcs, inp = _unmigrated(tmp_path)
    mod, argv = _cases()[name](str(npcs / "distilled"), inp, tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Error:" in err and "server.migrate_npc_dossiers" in err


def test_helper_prints_the_migration_command_and_exits(tmp_path, capsys):
    npcs, _ = _unmigrated(tmp_path)
    with pytest.raises(SystemExit) as exc:
        load_alias_map_or_exit(npcs / "distilled", exit_code=7)
    assert exc.value.code == 7
    err = capsys.readouterr().err
    assert err.startswith("Error:") and "server.migrate_npc_dossiers" in err


# scene_extract and sd_narrate need a whole session fixture to reach the alias load, so
# they are held to the same rule structurally: a bare load_alias_map call must sit in a
# module that handles DossierLayoutError (or call the _or_exit helper instead).
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINTS = [
    "session_doc/scene_extract.py", "session_doc/sd_narrate.py", "pipelines/grounding/distill.py",
    "pipelines/grounding/campaign_state.py", "pipelines/grounding/party.py",
    "pipelines/grounding/planning.py", "entity_registry/registry.py",
]


@pytest.mark.parametrize("rel", ENTRY_POINTS)
def test_alias_map_loaders_handle_a_layout_refusal(rel):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", getattr(n.func, "attr", "")) == "load_alias_map"]
    if not calls:
        return
    handles = any(isinstance(n, ast.ExceptHandler) and n.type is not None
                  and "DossierLayoutError" in ast.unparse(n.type) or
                  isinstance(n, ast.ExceptHandler) and n.type is not None
                  and "ValueError" in ast.unparse(n.type) and "isinstance(exc, DossierLayoutError)" in ast.unparse(n)
                  for n in ast.walk(tree))
    guarded_earlier = rel.endswith("planning.py")  # main() refuses before run_build_dossiers loads it
    assert handles or guarded_earlier, f"{rel} calls load_alias_map without handling DossierLayoutError"


def test_registry_import_frontmatter_refuses_without_a_traceback(tmp_path, capsys):
    from entity_registry import registry

    npcs, _ = _unmigrated(tmp_path)
    assert registry.main(["init", str(tmp_path)]) == 0
    assert registry.main(["import-frontmatter", str(tmp_path), str(npcs / "distilled")]) == 1
    assert "server.migrate_npc_dossiers" in capsys.readouterr().err
