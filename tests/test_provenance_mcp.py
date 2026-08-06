"""The MCP seam is a face over the CLI engine, and it is the only one.

Constitution VI says the CLI is the engine and the UI (here, MCP) is a face.
That is only true if the face cannot do anything the engine cannot — so the
central test in this file asserts **equivalence**: every tool produces the same
text as its documented shell invocation, because it literally runs it.

Constitution V says one seam per boundary. The tool surface is therefore pinned:
four read-only tools, no write tool, no identity-mutating tool, and — the
defining property — **no campaign pin anywhere in the server**. Every other
server in the workspace binds a campaign at process start; this one takes scope
per call and requires it (research D4).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from provenance import provenance_mcp as mod

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE = REPO_ROOT / "provenance" / "provenance_mcp.py"

TOOLS = (
    "provenance_search",
    "provenance_resolve",
    "provenance_capabilities",
    "provenance_check",
)


@pytest.fixture(autouse=True)
def _pin_workspace(fixture_workspace: Path, monkeypatch):
    """The tools take no --campaigns-root, so point the env at the fixture."""
    monkeypatch.setenv("CAMPAIGNS_ROOT", str(fixture_workspace))


# ── the surface ──────────────────────────────────────────────────────────────


def test_the_four_tools_exist() -> None:
    for name in TOOLS:
        assert callable(getattr(mod, name)), name


def test_no_write_tool_is_exposed() -> None:
    exported = {
        name
        for name, value in vars(mod).items()
        if callable(value) and not name.startswith("_")
    }
    for forbidden in ("add", "alias", "merge", "mark_distinct", "write", "save", "project"):
        assert not any(forbidden in name for name in exported), forbidden


def test_the_module_imports_without_the_mcp_package() -> None:
    """The FastMCP import must be lazy, inside build_server."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("mcp"):
            assert node.col_offset > 0, "the mcp import must be lazy, not module-level"


# ── scope is required, everywhere (FR-006, Constitution X) ──────────────────


def test_campaigns_is_required_with_no_default() -> None:
    signature = inspect.signature(mod.provenance_search)
    parameter = signature.parameters["campaigns"]
    assert parameter.default is inspect.Parameter.empty, (
        "a default here would be a scope the caller never chose"
    )


def test_an_empty_campaign_list_is_refused() -> None:
    output = mod.provenance_search("Silver Lantern", [])
    assert "EXIT 1" in output
    assert "no campaign scope given" in output
    assert "alpha" in output and "beta" in output


def _executable_strings_and_names() -> tuple[set[str], set[str]]:
    """Everything the module *does*, with the prose stripped out.

    Checked against the AST rather than the raw text because the module
    docstring names ``--campaign-dir`` and ``CAMPAIGN_DIR`` on purpose — to
    explain what this server deliberately does not have. A grep over the source
    cannot tell an explanation from an implementation.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)

    strings, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                strings.add(node.value)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return strings, names


def test_there_is_no_campaign_pin_in_the_server() -> None:
    """The absence IS the feature (research D4)."""
    strings, names = _executable_strings_and_names()
    assert "campaign_dir" not in names
    for pin in ("--campaign-dir", "CAMPAIGN_DIR"):
        assert not any(pin in s for s in strings), f"{pin} would bind this server to one game"


def test_no_all_campaigns_token_exists() -> None:
    strings, _ = _executable_strings_and_names()
    for token in ("all", "--all-campaigns", "*"):
        assert token not in strings


def test_the_instructions_state_the_scope_rule() -> None:
    text = mod.INSTRUCTIONS
    assert 'There is no "all campaigns"' in text
    assert "will be clobbered" in text
    assert "never writes" in text


# ── CLI equivalence (Constitution VI) ────────────────────────────────────────


def _cli(argv: list[str], fixture_workspace: Path) -> str:
    """The same command a human would type — and deliberately without
    ``--campaigns-root``, because ``$CAMPAIGNS_ROOT`` is what the MCP tools see.

    Passing the flag here would make the two sides resolve the workspace by
    different rules, and ``capabilities`` reports which rule fired. The
    difference would be a real one, correctly reported, and comparing across it
    would only prove the test was sloppy.
    """
    import io
    from contextlib import redirect_stderr, redirect_stdout

    from provenance import cli

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    parts = [p.strip() for p in (out.getvalue(), err.getvalue()) if p.strip()]
    text = "\n".join(parts) if parts else ("(no output)" if code == 0 else "(failed)")
    return text if code == 0 else f"EXIT {code}:\n{text}"


def _stable(text: str) -> list[str]:
    """Drop the one line that legitimately differs between two runs: elapsed time."""
    return [line for line in text.splitlines() if "matches," not in line]


def test_search_equals_its_cli_invocation(fixture_workspace: Path) -> None:
    assert _stable(mod.provenance_search("Silver Lantern", ["alpha"], limit=5)) == _stable(
        _cli(
            ["search", "Silver Lantern", "--campaign", "alpha", "--limit", "5",
             "--context-lines", "2"],
            fixture_workspace,
        )
    )


def test_resolve_equals_its_cli_invocation(fixture_workspace: Path) -> None:
    assert mod.provenance_resolve("Marnix", "alpha") == _cli(
        ["resolve", "Marnix", "--campaign", "alpha"], fixture_workspace
    )


def test_capabilities_equals_its_cli_invocation(fixture_workspace: Path) -> None:
    assert mod.provenance_capabilities() == _cli(["capabilities"], fixture_workspace)


def test_check_equals_its_cli_invocation(fixture_workspace: Path) -> None:
    assert mod.provenance_check(["alpha"]) == _cli(
        ["check", "--campaign", "alpha"], fixture_workspace
    )


# ── behaviour through the seam ───────────────────────────────────────────────


def test_a_refusal_surfaces_as_a_refusal_not_an_empty_result() -> None:
    assert "EXIT 1" in mod.provenance_search("x", ["gamma"])
    assert "has no manifest entry" in mod.provenance_search("x", ["gamma"])


def test_a_malformed_call_does_not_kill_the_server() -> None:
    """argparse exits the process; the wrapper must catch that."""
    assert "EXIT 2" in mod._run(["search"])


def test_resolve_reports_all_three_states() -> None:
    assert "RESOLVED" in mod.provenance_resolve("Marnix", "alpha")
    assert "NOT FOUND" in mod.provenance_resolve("Nobody At All", "alpha")
    assert "NO IDENTITY STORE" in mod.provenance_resolve("Anyone", "beta")


def test_check_unscoped_validates_everything() -> None:
    """The one legal unscoped call: authored data only, no corpus content."""
    assert "Checked: alpha, beta" in mod.provenance_check()


def test_cross_campaign_requires_naming_both() -> None:
    output = mod.provenance_search("Silver Lantern", ["alpha", "beta"], limit=50)
    assert "alpha, beta" in output


def test_the_server_builds_when_mcp_is_installed() -> None:
    pytest.importorskip("mcp.server.fastmcp")
    server = mod.build_server()
    assert server.name == "provenance"
