"""T022 / SC-003 — there is no input that searches everything.

The success criterion is stated as an absence, which is the hardest kind to
test: you cannot enumerate every input that *doesn't* trigger a full-corpus
search. So this file attacks it from three sides.

1. **Structurally** — an AST sweep asserting that no campaign-scope parameter
   anywhere under ``provenance/`` carries a default. A default is the only way a
   scope can arrive without a caller having chosen it, and the sweep covers
   modules that do not exist yet (``provenance_mcp.py``, ``search.py``) the
   moment they land, rather than waiting for someone to remember.
2. **Behaviourally** — omitting ``--campaign`` refuses, with exit ``1``, naming
   the campaigns.
3. **By vocabulary** — ``all``, ``*`` and ``""`` are ordinary unknown names.
   There is no magic token, so SC-003 holds by construction rather than by
   careful defaulting.

The one deliberate exception is ``provenance check``, which validates every
campaign's *authored data* when unscoped. It returns no content and no hits.
``test_only_check_may_default_to_every_campaign`` pins that so the pattern does
not spread to a subcommand that returns text from the corpus.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from provenance.cli import EXIT_LOAD_ERROR, EXIT_OK, EXIT_REFUSED, build_parser, main

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG = REPO_ROOT / "provenance"

#: Parameter names that carry a campaign scope. A default on any of these is a
#: scope the caller did not choose.
SCOPE_PARAMS = {"campaign", "campaigns", "campaign_name", "campaign_names", "scope"}

#: Tokens that must never mean "everything".
MAGIC_TOKENS = ["all", "ALL", "*", "", "  ", "%", ".", "any"]

#: The one deliberate exception, named function by function rather than by a
#: pattern. ``check`` validates the *authored YAML* — it returns no corpus
#: content, no hits and no excerpt, and spends no tokens. The blast radius
#: Principle X guards is content and token spend, and ``check`` has neither
#: (contracts/mcp.md). Anything else appearing in this set is a bug, which is
#: why it lists exact names instead of, say, everything matching ``*_check``.
SCOPE_DEFAULT_EXEMPT = {"provenance_check", "provenance_check_tool"}


def modules() -> list[Path]:
    return sorted(p for p in PKG.glob("*.py") if p.name != "__init__.py")


# ── 1. structural: no scope parameter has a default ──────────────────────────


def _scope_params_with_defaults(tree: ast.AST):
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in SCOPE_DEFAULT_EXEMPT:
            continue
        args = node.args
        positional = args.posonlyargs + args.args
        # defaults align to the TAIL of the positional list
        for arg, default in zip(positional[len(positional) - len(args.defaults):],
                                args.defaults):
            if arg.arg in SCOPE_PARAMS:
                found.append((node.name, arg.arg, ast.unparse(default)))
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            if default is not None and arg.arg in SCOPE_PARAMS:
                found.append((node.name, arg.arg, ast.unparse(default)))
    return found


def test_no_campaign_scope_parameter_carries_a_default():
    """Covers modules that do not exist yet, the moment they land."""
    offenders = []
    for path in modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders += [(path.name, *f) for f in _scope_params_with_defaults(tree)]
    assert not offenders, (
        "a campaign scope must always be chosen by the caller; these have defaults: "
        f"{offenders}"
    )


def test_the_structural_sweep_is_not_vacuous():
    """Guard against the sweep passing because it found nothing to look at."""
    seen = set()
    for path in modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = {a.arg for a in node.args.posonlyargs + node.args.args
                         + node.args.kwonlyargs}
                seen |= names & SCOPE_PARAMS
    assert seen, f"no scope parameters found under {PKG} — the sweep is checking nothing"


# ── 2. argparse: omitting --campaign refuses rather than erroring ────────────


@pytest.mark.parametrize("command", ["search", "resolve"])
def test_campaign_has_no_argparse_default(command):
    action = _campaign_action(command)
    assert action.default is None
    assert action.nargs is None


@pytest.mark.parametrize("command", ["search", "resolve"])
def test_campaign_is_not_argparse_required(command):
    """It must refuse (exit 1) with the campaign list, not usage-error (exit 2).

    argparse's own error prints a usage string and exits 2. A caller who guessed
    a campaign name wrong would learn nothing about which names exist — and the
    manifest is the only enumeration there is (FR-023).
    """
    assert _campaign_action(command).required is False


@pytest.mark.parametrize("command", ["search", "resolve", "check"])
def test_campaign_is_repeatable(command):
    """Naming N campaigns by hand IS the deliberate cross-campaign act (Constitution X)."""
    assert _campaign_action(command).__class__.__name__ == "_AppendAction"


def test_there_is_no_all_campaigns_flag():
    options = {
        option
        for action in build_parser()._subparsers._group_actions[0].choices["search"]._actions
        for option in action.option_strings
    }
    for forbidden in ("--all", "--all-campaigns", "--every-campaign", "--everything"):
        assert forbidden not in options


def test_no_tier_choice_is_a_wildcard():
    assert "all" not in (_action("search", "--tier").choices or ())
    assert "*" not in (_action("search", "--tier").choices or ())


def _action(command: str, option: str):
    parser = build_parser()._subparsers._group_actions[0].choices[command]
    for action in parser._actions:
        if option in action.option_strings:
            return action
    raise AssertionError(f"{command} has no {option}")


def _campaign_action(command: str):
    return _action(command, "--campaign")


# ── 3. behavioural: refusals over the pinned fixture workspace ───────────────


@pytest.fixture
def root(fixture_workspace) -> list[str]:
    return ["--campaigns-root", str(fixture_workspace)]


def test_search_without_a_campaign_refuses(root, capsys):
    assert main(["search", "Silver Lantern", *root]) == EXIT_REFUSED
    err = capsys.readouterr().err
    assert "REFUSED" in err
    assert "no implicit" in err
    assert "alpha" in err and "beta" in err


def test_resolve_without_a_campaign_refuses(root, capsys):
    assert main(["resolve", "Marnix", *root]) == EXIT_REFUSED
    assert "alpha, beta" in capsys.readouterr().err


@pytest.mark.parametrize("token", MAGIC_TOKENS)
def test_no_magic_token_means_every_campaign(root, capsys, token):
    """``all`` is not a keyword. It is a campaign name nobody has, so it refuses."""
    assert main(["search", "Silver Lantern", "--campaign", token, *root]) == EXIT_REFUSED
    err = capsys.readouterr().err
    assert "has no manifest entry" in err
    assert "alpha, beta" in err


@pytest.mark.parametrize("token", MAGIC_TOKENS)
def test_a_magic_token_alongside_a_real_campaign_still_refuses(root, capsys, token):
    """No partial service. Refusing the bad name and searching the good one would
    answer a question the caller did not ask."""
    assert main(
        ["search", "x", "--campaign", "alpha", "--campaign", token, *root]
    ) == EXIT_REFUSED


def test_an_unknown_campaign_refuses_by_name(root, capsys):
    assert main(["search", "x", "--campaign", "gamma", *root]) == EXIT_REFUSED
    assert "'gamma' has no manifest entry" in capsys.readouterr().err


def test_a_refusal_is_never_exit_zero_with_an_empty_result(root, capsys):
    """The whole of Story 3 in one assertion.

    "I refused to answer" and "I looked and found nothing" justify opposite next
    actions, and a scriptable caller must tell them apart without parsing prose.
    """
    for argv in (
        ["search", "x", *root],
        ["search", "x", "--campaign", "all", *root],
        ["search", "x", "--campaign", "beta", "--horizon", "2", *root],
    ):
        assert main(argv) == EXIT_REFUSED
        assert "REFUSED" in capsys.readouterr().err


def test_a_load_error_is_distinct_from_a_refusal(tmp_path, capsys):
    assert main(["search", "x", "--campaign", "alpha",
                 "--campaigns-root", str(tmp_path)]) == EXIT_LOAD_ERROR
    assert "LOAD ERROR" in capsys.readouterr().err


def test_naming_two_campaigns_is_accepted(root, capsys):
    """The deliberate cross-campaign act: N≥2 names, written by hand."""
    code = main(["search", "Silver Lantern", "--campaign", "alpha", "--campaign", "beta",
                 *root])
    assert code != EXIT_REFUSED
    assert "REFUSED" not in capsys.readouterr().err


# ── the one deliberate exception ─────────────────────────────────────────────


def test_only_check_may_default_to_every_campaign(root, capsys):
    """``check`` validates authored data; it returns no corpus content and no hits.

    Pinned here so the pattern does not spread to a subcommand that does.
    """
    main(["check", *root])
    out = capsys.readouterr().out
    assert "Checked: alpha, beta" in out


def test_the_exemption_covers_check_and_nothing_else():
    """The allow-list is a list of names, and it must stay a short one.

    An exemption that grew by pattern — every ``*_check``, every "read-only"
    function — would eventually cover something that returns corpus text, and
    the sweep above would go quiet at exactly the wrong moment.
    """
    assert all("check" in name for name in SCOPE_DEFAULT_EXEMPT)
    assert len(SCOPE_DEFAULT_EXEMPT) <= 2


def test_check_returns_no_corpus_content(root, capsys):
    """Why the exemption is safe, asserted rather than asserted-in-prose."""
    main(["check", *root])
    out = capsys.readouterr().out
    # `check` names paths and globs; it must never quote a line out of a file.
    assert "Silver Lantern" not in out
    assert "┌─" not in out


def test_capabilities_enumerates_without_searching(root, capsys):
    assert main(["capabilities", *root]) == EXIT_OK
    out = capsys.readouterr().out
    assert "alpha" in out and "beta" in out
