"""Every distilled-dossier reader goes through the migration guard (spec 032 T031).

``docs/npcs/`` now holds published dossiers directly; distilled ones live under
``docs/npcs/distilled/``. A reader that globbed ``docs/npcs`` would feed generated
output back into identity (FR-022d), and one that ignored an unmigrated
``docs/npcs/`` would silently see nothing (FR-022c). Both are refused, naming the
migration command.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from campaignlib.npc import (
    PUBLISH_HEADER_PREFIX,
    DossierLayoutError,
    load_alias_map,
    refuse_unmigrated_dossier_dir,
)

REPO = Path(__file__).resolve().parent.parent
GUARD = "refuse_unmigrated_dossier_dir"

# research R12's table: (file, function that must call the guard)
R12_READERS = [
    ("campaignlib/npc.py", "load_alias_map"),
    ("pipelines/grounding/planning.py", "main"),
    ("entity_registry/resolve.py", "_dossiers"),
    ("entity_registry/registry.py", "collect_check_findings"),
    ("server/platform_config_service.py", "discover_campaign_paths"),
]
SKIP_DIRS = {"tests", "experiments", "node_modules", ".venv", ".git", "frontend", "specs"}


def _calls(fn: ast.AST) -> set[str]:
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            out.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    return out


@pytest.mark.parametrize("rel,func", R12_READERS)
def test_r12_reader_calls_the_guard(rel, func):
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func]
    assert fns, f"{rel} has no function {func!r} (R12 table out of date?)"
    assert any(GUARD in _calls(f) for f in fns), f"{rel}:{func} must call {GUARD}"


def test_no_in_repo_reader_uses_rglob_on_a_dossier_path():
    offenders = []
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        if rel.parts[0] in SKIP_DIRS or any(p in SKIP_DIRS for p in rel.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "rglob"):
                recv = ast.unparse(node.func.value)
                if "npcs" in recv or "dossier" in recv.lower():
                    offenders.append(f"{rel}:{node.lineno} {recv}.rglob")
    assert not offenders, offenders


def _npcs(tmp_path) -> Path:
    d = tmp_path / "campaign" / "docs" / "npcs"
    d.mkdir(parents=True)
    return d


def test_guard_refuses_a_loose_md_without_the_publish_header(tmp_path):
    npcs = _npcs(tmp_path)
    (npcs / "eelrich-vane.md").write_text("# Eelrich\n", encoding="utf-8")
    (npcs / "distilled").mkdir()
    with pytest.raises(DossierLayoutError) as exc:
        refuse_unmigrated_dossier_dir(npcs / "distilled")
    assert "server.migrate_npc_dossiers" in str(exc.value)
    assert "--propose" in str(exc.value) and "--apply" in str(exc.value)
    assert "eelrich-vane.md" in str(exc.value)


def test_guard_refuses_docs_npcs_itself_and_names_the_migration(tmp_path):
    npcs = _npcs(tmp_path)
    with pytest.raises(DossierLayoutError) as exc:
        refuse_unmigrated_dossier_dir(npcs)
    assert "server.migrate_npc_dossiers" in str(exc.value)
    with pytest.raises(DossierLayoutError):
        load_alias_map(npcs)


def test_guard_allows_published_only_and_no_distilled_dir(tmp_path):
    """The OOTA case: only published files, no distilled/ at all."""
    npcs = _npcs(tmp_path)
    (npcs / "jimjar.md").write_text(PUBLISH_HEADER_PREFIX + " | source: summary_native -->\nbody\n", encoding="utf-8")
    refuse_unmigrated_dossier_dir(npcs / "distilled")
    assert load_alias_map(npcs / "distilled") == {}


def test_guard_allows_a_campaign_with_no_docs_npcs(tmp_path):
    (tmp_path / "docs").mkdir()
    refuse_unmigrated_dossier_dir(tmp_path / "docs" / "npcs" / "distilled")
    assert load_alias_map(tmp_path / "docs" / "npcs" / "distilled") == {}


def test_guard_leaves_non_campaign_directories_alone(tmp_path):
    scratch = tmp_path / "npcs"
    scratch.mkdir()
    (scratch / "grundar.md").write_text("---\nname: Grundar\naliases: []\n---\nbody\n", encoding="utf-8")
    assert load_alias_map(scratch) == {"Grundar": []}


def test_load_alias_map_refuses_even_when_a_registry_would_replace_the_scan(tmp_path):
    npcs = _npcs(tmp_path)
    (npcs / "x.md").write_text("loose\n", encoding="utf-8")
    reg = tmp_path / "reg.yaml"
    reg.write_text("entities: []\n", encoding="utf-8")
    with pytest.raises(DossierLayoutError):
        load_alias_map(npcs / "distilled", registry_path=reg)


def test_registry_check_refuses_an_unmigrated_campaign(tmp_path, capsys):
    from entity_registry import registry

    camp = tmp_path / "campaign"
    assert registry.main(["init", str(camp)]) == 0
    (camp / "docs" / "npcs").mkdir(parents=True)
    (camp / "docs" / "npcs" / "loose.md").write_text("x\n", encoding="utf-8")
    assert registry.main(["check", str(camp)]) == 1
    assert "server.migrate_npc_dossiers" in capsys.readouterr().err


def test_registry_check_reads_distilled_state_not_the_loose_dir(tmp_path, capsys):
    import json
    from entity_registry import registry

    camp = tmp_path / "campaign"
    assert registry.main(["init", str(camp)]) == 0
    d = camp / "docs" / "npcs" / "distilled"
    d.mkdir(parents=True)
    (d / ".dedup_state.json").write_text(json.dumps({"clusters_confirmed": [
        {"files": ["a.md", "b.md"], "canonical": "a.md", "aliases_recorded": []}]}), encoding="utf-8")
    assert registry.main(["check", str(camp)]) == 1
    assert "dedup groups" in capsys.readouterr().out


def test_platform_discovery_refuses_unmigrated_with_409(tmp_path):
    from fastapi import HTTPException
    from server.platform_config_service import PlatformConfigService

    camp = tmp_path / "campaign"
    (camp / "docs" / "npcs").mkdir(parents=True)
    (camp / "docs" / "npcs" / "loose.md").write_text("x\n", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        PlatformConfigService.discover_campaign_paths(str(camp), str(camp))
    assert exc.value.status_code == 409 and "server.migrate_npc_dossiers" in exc.value.detail


def test_dossier_dir_default_is_the_single_declared_distilled_dir():
    from pipelines.summary_native.schema import DISTILLED_DIR
    from server.grounding_config_shared import DossierBuild

    assert DossierBuild().dossier_dir == DISTILLED_DIR + "/" == "docs/npcs/distilled/"


# ── readers that reach the guard through load_alias_map (added after R12) ────

VIA_LOAD_ALIAS_MAP = [
    ("server/routers/connections.py", "extract_connections"),
    ("server/routers/connections.py", "get_context"),
]


@pytest.mark.parametrize("rel,func", VIA_LOAD_ALIAS_MAP)
def test_connections_routes_go_through_the_guard_and_refuse_with_409(rel, func):
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func)
    assert "load_alias_map" in _calls(fn)
    assert "DossierLayoutError" in ast.unparse(fn), f"{func} must turn a refusal into a 409"
    assert "parent.parent" not in ast.unparse(fn), "the campaign root must not be found by depth arithmetic"


@pytest.mark.parametrize("sub", ["docs/npcs", "docs/npcs/distilled", "docs"])
def test_registry_is_found_from_any_dossier_depth(tmp_path, sub):
    from campaignlib.registry import find_registry_above

    (tmp_path / "docs" / "npcs" / "distilled").mkdir(parents=True)
    reg = tmp_path / "docs" / "entity_registry.yaml"
    reg.write_text("version: 1\ncampaign: c\nentities:\n  - name: Jimjar\n    type: npc\n    aliases: [Jim]\n",
                   encoding="utf-8")
    assert find_registry_above(tmp_path / sub) == reg


def test_get_context_finds_the_registry_with_docs_npcs_distilled(tmp_path):
    import json
    from server.routers.connections import get_context

    (tmp_path / "docs" / "npcs" / "distilled").mkdir(parents=True)
    (tmp_path / "docs" / "entity_registry.yaml").write_text(
        "version: 1\ncampaign: c\nentities:\n  - name: Jimjar\n    type: npc\n    aliases: [Jim]\n",
        encoding="utf-8")
    cache = tmp_path / "docs" / "connections.json"
    cache.write_text(json.dumps({"entities": [{"id": "jimjar", "label": "Jimjar", "type": "NPC"}],
                                 "edges": []}), encoding="utf-8")
    out = get_context("jimjar", docs_dir="", dossier_dir=str(tmp_path / "docs/npcs/distilled"),
                      cache_path=str(cache))
    assert "Jim" in out["search_terms"], "the registry's aliases must reach the search terms"


def test_get_context_refuses_an_unmigrated_docs_npcs_with_409(tmp_path):
    import json
    from fastapi import HTTPException
    from server.routers.connections import get_context

    npcs = tmp_path / "docs" / "npcs"
    npcs.mkdir(parents=True)
    (npcs / "loose.md").write_text("x\n", encoding="utf-8")
    cache = tmp_path / "docs" / "connections.json"
    cache.write_text(json.dumps({"entities": [{"id": "a", "label": "A", "type": "NPC"}], "edges": []}),
                     encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        get_context("a", dossier_dir=str(npcs / "distilled"), cache_path=str(cache))
    assert exc.value.status_code == 409 and "server.migrate_npc_dossiers" in exc.value.detail
