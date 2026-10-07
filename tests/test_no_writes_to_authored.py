"""Nothing but ``npc_authored.init_authored`` writes under ``docs/npcs/authored/`` (spec 032 T032).

SC-005, FR-022. ``authored/`` holds what a person made; no tool overwrites, renames or
deletes it, and nothing touches ``distilled/`` either. Two halves:

* an AST guard over every module in ``pipelines/summary_native`` (so a stage added later
  is checked the moment it exists);
* a behaviour test that runs each stage over a fixture seeded with ``authored/`` and
  ``distilled/`` files and asserts both trees byte-identical. A stage is exercised when
  its subcommand exists and skipped, with a reason, otherwise -- so the test tightens by
  itself as link / draft / compose / verify / publish land.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.conftest_npc import SINCE, UNTIL, npc_campaign, run_cli, sha_tree

PKG = Path(__file__).resolve().parents[1] / "pipelines" / "summary_native"

MUTATING_ATTRS = frozenset({
    "write_text", "write_bytes", "atomic_write_text", "replace", "rename", "renames", "unlink",
    "rmtree", "rmdir", "remove", "move", "touch", "copy", "copy2", "copyfile", "copytree",
    "truncate", "mkdir", "makedirs", "symlink_to", "hardlink_to", "link", "symlink",
})
ALLOWED_WRITER = ("npc_authored.py", "init_authored")


def _is_mutating(call: ast.Call) -> bool:
    f = call.func
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
    if name in MUTATING_ATTRS:
        return True
    if name == "open":
        mode = None
        if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
            mode = call.args[1].value
        for kw in call.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        return isinstance(mode, str) and any(c in mode for c in "wax+")
    return False


def _mentions_authored(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and "authored" in n.id.lower():
            return True
        if isinstance(n, ast.Attribute) and "authored" in n.attr.lower():
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "authored" in n.value.lower():
            return True
    return False


def violations(source: str, filename: str) -> list[str]:
    """Functions that both mutate the filesystem and refer to ``authored`` (outside the one writer)."""
    tree = ast.parse(source)
    out = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        if (filename, fn.name) == ALLOWED_WRITER:
            continue
        if any(isinstance(c, ast.Call) and _is_mutating(c) for c in ast.walk(fn)) and _mentions_authored(fn):
            out.append(f"{filename}:{fn.name}:{fn.lineno}")
    return out


def test_detector_catches_a_writer_and_ignores_a_reader():
    bad = "def f(p):\n    (p / 'authored' / 'x.md').write_text('x')\n"
    assert violations(bad, "m.py")
    bad2 = "def g(authored_dir):\n    import os\n    os.replace(a, authored_dir)\n"
    assert violations(bad2, "m.py")
    ok = "def h(p):\n    return (p / 'authored' / 'x.md').read_text()\n"
    assert not violations(ok, "m.py")


def test_only_init_authored_writes_under_authored():
    mods = sorted(PKG.glob("*.py"))
    assert len(mods) > 5
    found = [v for m in mods for v in violations(m.read_text(encoding="utf-8"), m.name)]
    assert not found, f"writes near authored/ outside init_authored: {found}"


def test_npc_authored_mutates_only_inside_init_authored():
    tree = ast.parse((PKG / "npc_authored.py").read_text(encoding="utf-8"))
    outside = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        if fn.name == "init_authored":
            continue
        if any(isinstance(c, ast.Call) and _is_mutating(c) for c in ast.walk(fn)):
            outside.append(fn.name)
    assert not outside, outside


# ── behaviour ────────────────────────────────────────────────────────────────

def _stage_args(root: Path) -> dict[str, list[str]]:
    shared = [
        "--config", str(root / "config/config.yaml"),
        "--summaries-dir", str(root / "docs/summaries"),
        "--since", str(SINCE), "--until", str(UNTIL),
    ]
    return {
        "npc-link": ["npc-link", *shared],
        "npc-draft": ["npc-draft", *shared, "--all", "--dump-only"],
        "npc-compose": ["npc-compose", *shared],
        "npc-verify": ["npc-verify", *shared],
        "npc-publish": ["npc-publish", *shared, "--all"],
    }


def _seed(root: Path) -> None:
    authored = root / "docs/npcs/authored"
    distilled = root / "docs/npcs/distilled"
    authored.mkdir(parents=True)
    distilled.mkdir(parents=True)
    (authored / "jimjar.authored.yaml").write_text(
        "subject: Jimjar\nmanual:\n  - Jimjar is a deep gnome.\nsecrets: |\n  SECRET-CANARY-7731\n", encoding="utf-8")
    (authored / "eelrich-vane.md").write_text("# Eelrich Vane\n\nHand built.\n", encoding="utf-8")
    (distilled / "hedrack.md").write_text("---\nname: Hedrack\naliases: []\nsource_extracts: [1]\n---\nbody\n", encoding="utf-8")
    (distilled / ".dedup_state.json").write_text("{}\n", encoding="utf-8")


def _subcommands() -> tuple[str, ...]:
    from pipelines.summary_native import cli
    return tuple(cli.SUBCOMMANDS)


@pytest.mark.parametrize("stage", ["npc-link", "npc-draft", "npc-compose", "npc-verify", "npc-publish"])
def test_stage_leaves_authored_and_distilled_byte_identical(tmp_path, stage):
    if stage not in _subcommands():
        pytest.skip(f"{stage} is not implemented yet; this test exercises it as soon as the subcommand exists")
    root = npc_campaign(tmp_path)
    _seed(root)
    before_a = sha_tree(root / "docs/npcs/authored")
    before_d = sha_tree(root / "docs/npcs/distilled")
    # Run the earlier stages first so later ones have something to act on.
    order = ["npc-link", "npc-draft", "npc-compose", "npc-verify", "npc-publish"]
    args = _stage_args(root)
    for name in order[: order.index(stage) + 1]:
        if name not in _subcommands():
            continue
        rc, _out, err = run_cli(args[name])
        assert rc in (0, 1, 2, 3, 5), f"{name} crashed ({rc}): {err}"
    assert sha_tree(root / "docs/npcs/authored") == before_a, f"{stage} changed authored/"
    assert sha_tree(root / "docs/npcs/distilled") == before_d, f"{stage} changed distilled/"
