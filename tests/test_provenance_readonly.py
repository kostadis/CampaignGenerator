"""FR-031 / FR-032 / SC-010: this package never writes, and never shells out to
anything but `rg`.

Two guards, because either alone is insufficient:

**Static (AST).** No module under `provenance/` may reference a write sentinel.
A behavioural test can only prove that the paths it exercised did not write; the
AST guard covers the paths nobody thought to exercise. It is deliberately strict
— `.replace` is banned outright even though `str.replace` is harmless, because
distinguishing `Path.replace` from `str.replace` statically is impossible and
the package has no need for either.

**Behavioural (sha256).** Every file in the fixture workspace is hashed before
and after exercising every operation the CLI exposes. SC-010 is a claim about
bytes on disk, so it is checked against bytes on disk.

**The subprocess allow-list** exists because adopting rg made this package one
that shells out (research D16). A search tool that shells out is a search tool
that could shell out to something else after the next hurried edit — so the
argv builder is pinned, and every flag it can emit is enumerated here.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG = REPO_ROOT / "provenance"

#: Referencing any of these means a filesystem mutation is reachable from here.
WRITE_SENTINELS = frozenset(
    {
        "write_text",
        "write_bytes",
        "writelines",
        "mkdir",
        "makedirs",
        "unlink",
        "remove",
        "rmdir",
        "rmtree",
        "rename",
        "replace",
        "touch",
        "chmod",
        "symlink_to",
        "hardlink_to",
        "copy",
        "copy2",
        "copyfile",
        "copytree",
        "move",
        "atomic_write_text",
        "save_registry",
        "dump_registry",
        "mkstemp",
        "NamedTemporaryFile",
    }
)

#: Only this module may spawn a process, and only via the pinned builder.
SUBPROCESS_MODULE = "scan.py"


def _modules() -> list[Path]:
    if not PKG.is_dir():
        return []
    return sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# ── static: no writes ────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_write_sentinel_is_referenced(path: Path) -> None:
    bad: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Attribute) and node.attr in WRITE_SENTINELS:
            bad.append(f".{node.attr}")
        elif isinstance(node, ast.Name) and node.id in WRITE_SENTINELS:
            bad.append(node.id)
    assert not bad, (
        f"{path.relative_to(REPO_ROOT)} references a write sentinel {sorted(set(bad))}. "
        "FR-031: this package never writes — not to campaign content, not to an index, "
        "not to a cache."
    )


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_open_is_never_called_for_writing(path: Path) -> None:
    for node in ast.walk(_tree(path)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "open":
            continue
        modes = [a for a in node.args[1:2] if isinstance(a, ast.Constant)]
        modes += [
            kw.value
            for kw in node.keywords
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant)
        ]
        for mode in modes:
            assert not (set(str(mode.value)) & set("wax+")), (
                f"{path.relative_to(REPO_ROOT)} opens a file for writing"
            )


def test_the_package_never_imports_a_write_helper() -> None:
    """`campaignlib.io`'s atomic_write_text is the repo's write path. Not here."""
    for path in _modules():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                ("campaignlib.io", "campaignlib.atomic")
            ):
                pytest.fail(f"{path.name} imports a write helper")


# ── static: the subprocess allow-list ────────────────────────────────────────


def _subprocess_modules() -> list[Path]:
    found = []
    for path in _modules():
        for node in ast.walk(_tree(path)):
            is_import = isinstance(node, ast.Import) and any(
                a.name == "subprocess" for a in node.names
            )
            is_from = isinstance(node, ast.ImportFrom) and node.module == "subprocess"
            if is_import or is_from:
                found.append(path)
                break
    return found


def test_only_the_scanner_spawns_a_process() -> None:
    names = sorted(p.name for p in _subprocess_modules())
    assert names in ([], [SUBPROCESS_MODULE]), (
        f"subprocess reachable from {names}; only {SUBPROCESS_MODULE} may spawn one"
    )


def test_the_only_binary_spawned_is_rg() -> None:
    """Statically: every subprocess call's argv is the pinned builder's output."""
    from provenance.scan import RG_ARGV_BUILDER

    module = PKG / SUBPROCESS_MODULE
    if not module.is_file():
        pytest.skip("scan.py absent")

    calls = [
        node
        for node in ast.walk(_tree(module))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]
    assert calls, "no subprocess call found; this guard would be vacuous"
    for call in calls:
        first = call.args[0] if call.args else None
        assert isinstance(first, ast.Name) and first.id == RG_ARGV_BUILDER, (
            "a subprocess argv must come from the pinned builder, never be assembled "
            "at the call site"
        )


def test_every_emitted_flag_is_on_the_allow_list(fixture_manifest) -> None:
    """Dynamically: the builder cannot emit a flag nobody signed off on."""
    from provenance.scan import RG_ALLOWED_FLAGS, build_rg_argv

    campaign = fixture_manifest.campaigns["alpha"]
    for regex in (False, True):
        for case_sensitive in (False, True):
            argv = build_rg_argv(
                campaign, "query", regex=regex, case_sensitive=case_sensitive
            )
            emitted = {
                tok
                for i, tok in enumerate(argv)
                if tok.startswith("-") and (i == 0 or argv[i - 1] not in ("-g", "-e"))
            }
            assert emitted <= set(RG_ALLOWED_FLAGS), emitted - set(RG_ALLOWED_FLAGS)


def test_rg_is_never_asked_to_write() -> None:
    """rg has no write mode, but the allow-list is what keeps it that way."""
    from provenance.scan import RG_ALLOWED_FLAGS

    assert not {"--replace", "-r", "--passthru"} & set(RG_ALLOWED_FLAGS)


# ── behavioural: SC-010 ──────────────────────────────────────────────────────


def _fingerprint(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_exercising_everything_changes_no_byte(fixture_workspace: Path) -> None:
    """SC-010, checked where it is actually made: on disk."""
    from provenance import cli

    before = _fingerprint(fixture_workspace)
    root = ["--campaigns-root", str(fixture_workspace)]

    cli.main(["check", *root])
    cli.main(["capabilities", *root])
    cli.main(["search", "Silver Lantern", "--campaign", "alpha", *root])
    cli.main(["search", "Silver Lantern", "--campaign", "alpha", "--json", *root])
    cli.main(["search", "Lantern", "--campaign", "alpha", "--campaign", "beta", *root])
    cli.main(["search", "Marnix", "--campaign", "alpha", "--expand-aliases", *root])
    cli.main(["search", "Lantern", "--campaign", "alpha", "--horizon", "1", *root])
    cli.main(["resolve", "Marnix", "--campaign", "alpha", *root])
    cli.main(["resolve", "Nobody", "--campaign", "alpha", *root])
    cli.main(["resolve", "Anyone", "--campaign", "beta", *root])

    assert _fingerprint(fixture_workspace) == before


def test_no_artifact_is_created(fixture_workspace: Path) -> None:
    """SC-009 is satisfied vacuously — there is nothing derived to delete."""
    from provenance import cli

    before = {str(p.relative_to(fixture_workspace)) for p in fixture_workspace.rglob("*")}
    cli.main(
        ["search", "Silver Lantern", "--campaign", "alpha", "--campaigns-root",
         str(fixture_workspace)]
    )
    after = {str(p.relative_to(fixture_workspace)) for p in fixture_workspace.rglob("*")}
    assert after == before
