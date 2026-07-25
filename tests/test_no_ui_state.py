"""Guard: nothing reads, writes, or models ``ui_state.yaml`` any more.

``docs/config/ui-state-retirement.md`` closed the last "no service ownership"
row in ``docs/config/service-cut.md`` — not by extracting a sixth service, but
by deleting a tier that owned nothing: six ``ui.<section>`` blobs that were
empty in every campaign, with no writer (the generic
``PUT /api/config/section/{name}`` route had no client) and no reader except
three frontend sites pointed at sections that had already been deleted.

This file is the mechanical guard that keeps it closed, in the spirit of
``tests/test_retrieve_render_isolation.py`` and ``tests/test_config_location.py``:
a structural rule gets a test, not a paragraph in a doc. Without it the cheapest
way to give a new page some persistence is to add a seventh loose section, which
is how the first six got there.

**The migration CLIs are the deliberate exception.** ``server/migrate_*.py``
read ``ui_state.yaml`` raw, by design, so they can rescue fields no live schema
declares. Retiring the reader must not retire the rescuers — a campaign
restored from an old backup still needs them. They are allowlisted below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The migration CLIs and their shared constant module — the one place
# ui_state.yaml is still legitimately named. Plus this file.
_ALLOWED = {
    "server/migrate_common.py",
    "server/migrate_session_doc.py",
    "server/migrate_ensemble_config.py",
    "server/migrate_grounding_config.py",
    "server/migrate_platform_config.py",
    "tests/test_no_ui_state.py",
}

# Retired symbols. A reference to any of these in live code means the tier is
# growing back.
_RETIRED_SYMBOLS = (
    "UIStateService",
    "UISection",
    "UIState",
    "UI_SECTION_NAMES",
    "_LooseSection",
    "SCHEMA_VERSION",
)

_SECTION_ROUTE = re.compile(r"""["'`]/api/config/section/""")


def _sources() -> list[Path]:
    """Live server + frontend sources, minus the migration allowlist."""
    out: list[Path] = []
    for base, patterns in (
        (REPO_ROOT / "server", ("*.py",)),
        (REPO_ROOT / "frontend" / "src", ("*.ts", "*.vue")),
    ):
        for pattern in patterns:
            for path in base.rglob(pattern):
                if "__pycache__" in path.parts or "node_modules" in path.parts:
                    continue
                if path.relative_to(REPO_ROOT).as_posix() in _ALLOWED:
                    continue
                out.append(path)
    return out


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Executable lines only — docstrings and comments removed.

    The retirement left a lot of deliberate prose behind: docstrings and
    comments recording what went and why, which is the point of writing them.
    A guard that fired on those would teach the next person to delete the
    explanation, so they are excluded.

    Python docstrings are found with ``ast`` rather than by looking for a line
    that *starts* with a quote — the first cut of this guard did the latter and
    reported 40 false positives, every one a continuation line inside a
    multi-line docstring. That is the same "grep one spelling of a thing
    defined by its behavior" mistake ``docs/config/platform-isolation.md``
    records three times over.

    It also found one true positive the naive version would have kept: a live
    f-string in ``server/main.py`` telling the GM to go fix ``ui_state.yaml``
    after a boot failure — a file the server no longer reads. Strings are
    therefore scanned, only docstrings are skipped.
    """
    text = path.read_text(encoding="utf-8")
    skip: set[int] = set()

    if path.suffix == ".py":
        import ast

        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            doc = node.body[0] if node.body else None
            if (
                isinstance(doc, ast.Expr)
                and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str)
            ):
                skip.update(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))

    lines: list[tuple[int, str]] = []
    in_block_comment = False
    for n, raw in enumerate(text.splitlines(), 1):
        if n in skip:
            continue
        stripped = raw.strip()
        if path.suffix in (".ts", ".vue"):
            if in_block_comment:
                if "*/" in stripped:
                    in_block_comment = False
                continue
            if stripped.startswith("/*"):
                in_block_comment = "*/" not in stripped
                continue
        code = raw.split("#", 1)[0] if path.suffix == ".py" else raw.split("//", 1)[0]
        if code.strip():
            lines.append((n, code))
    return lines


@pytest.mark.parametrize("symbol", _RETIRED_SYMBOLS)
def test_no_live_reference_to_a_retired_ui_state_symbol(symbol):
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{n}"
        for path in _sources()
        for n, code in _code_lines(path)
        if symbol in code
    ]
    assert not offenders, (
        f"{symbol} is retired with ui_state.yaml "
        f"(docs/config/ui-state-retirement.md) but is referenced at: "
        f"{', '.join(offenders)}"
    )


def test_no_caller_of_the_generic_section_route():
    """``PUT /api/config/section/{name}`` is deleted, not merely unused.

    Checked as a string across both languages because the route could come back
    from either side — a router redeclaring it, or a frontend fetch calling a
    path that would now 404.
    """
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{n}"
        for path in _sources()
        for n, code in _code_lines(path)
        if _SECTION_ROUTE.search(code)
    ]
    assert not offenders, (
        "the generic ui.<section> write door is retired "
        f"(docs/config/ui-state-retirement.md); referenced at: {', '.join(offenders)}"
    )


def test_the_server_never_names_the_retired_document():
    """No server module outside the migration allowlist names
    ``ui_state.yaml``. The frontend is checked by the symbol tests above; this
    one is about the file itself, which the server no longer opens at all."""
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{n}"
        for path in _sources()
        if path.suffix == ".py"
        for n, code in _code_lines(path)
        if "ui_state" in code
    ]
    assert not offenders, (
        "ui_state.yaml is not read by the server any more — only by the "
        f"migration CLIs (allowlisted). Referenced at: {', '.join(offenders)}"
    )


def test_the_migration_clis_still_read_it():
    """The inverse guard, and the reason the allowlist is not just a mute
    button: if a future cleanup deletes the migrators along with the tier, a
    campaign that never migrated loses its data silently. Each CLI must still
    name the file it exists to rescue."""
    for name in (
        "migrate_session_doc",
        "migrate_ensemble_config",
        "migrate_grounding_config",
        "migrate_platform_config",
    ):
        source = (REPO_ROOT / "server" / f"{name}.py").read_text(encoding="utf-8")
        assert "UI_STATE_NAME" in source, (
            f"server/{name}.py no longer reads ui_state.yaml — an unmigrated "
            "campaign would have no way to recover its data"
        )
