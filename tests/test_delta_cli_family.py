"""039 T018: the ``summary_native delta`` parser family (one flag spelling, no --all, stubs exit 2)."""

from __future__ import annotations

import argparse

import pytest

from pipelines.summary_native import cli
from pipelines.summary_native.delta import cli as delta_cli

SHARED = ("--campaign-dir", "--config", "--json", "--force", "--source")

#: Minimal argv that satisfies each leaf's required arguments.
REQUIRED = {
    "associate decide": ["ID1", "--decision", "approve"],
    "grounding decide": ["P1", "--decision", "approve"],
    "npc attest": ["alice", "--reason", "r", "--publication", "abc"],
}


def _delta_leaves(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    top = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    out: dict[str, argparse.ArgumentParser] = {}

    def walk(p, prefix):
        subs = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
        if not subs:
            out[" ".join(prefix)] = p
            return
        for name, child in subs[0].choices.items():
            walk(child, prefix + [name])

    walk(top.choices["delta"], [])
    return out


def _argv(leaf: str, *extra: str) -> list[str]:
    return ["delta", *leaf.split(" "), *REQUIRED.get(leaf, []), *extra]


def test_leaf_set_matches_contract():
    assert set(_delta_leaves(cli.build_parser())) == set(delta_cli.LEAVES)


@pytest.mark.parametrize("leaf", delta_cli.LEAVES)
def test_every_leaf_parses_with_shared_flags(leaf):
    args = cli.build_parser().parse_args(
        _argv(leaf, "--campaign-dir", "/c", "--config", "/c/config/config.yaml", "--json", "--force",
              "--source", "a.md", "--source", "b.md"))
    assert args.delta_leaf == leaf
    assert args.source == ["a.md", "b.md"]
    assert args.json and args.force and args.campaign_dir == "/c"


@pytest.mark.parametrize("leaf", delta_cli.LEAVES)
def test_source_has_no_default(leaf):
    assert cli.build_parser().parse_args(_argv(leaf)).source is None


@pytest.mark.parametrize("leaf", delta_cli.LEAVES)
def test_no_all_option_and_shared_flags_present(leaf):
    parser = _delta_leaves(cli.build_parser())[leaf]
    flags = {s for a in parser._actions for s in a.option_strings}
    assert "--all" not in flags
    assert not [f for f in flags if "all" in f.split("-")]
    assert set(SHARED) <= flags


@pytest.mark.parametrize("leaf", delta_cli.LEAVES)
def test_stub_exits_2_not_implemented(leaf, capsys):
    delta_cli.load_handlers()
    if leaf in delta_cli.DELTA_HANDLERS:
        pytest.skip("leaf has a real handler now; its own tests cover it")
    assert cli.main(_argv(leaf)) == 2
    assert "not implemented" in capsys.readouterr().err


def test_decision_has_no_default_and_is_required(capsys):
    parser = cli.build_parser()
    for leaf in ("associate decide", "grounding decide"):
        p = _delta_leaves(parser)[leaf]
        action = next(a for a in p._actions if "--decision" in a.option_strings)
        assert action.default is None and action.required
        assert set(action.choices) == {"approve", "reject", "discuss"}
        with pytest.raises(SystemExit) as e:
            parser.parse_args(["delta", *leaf.split(" "), "X"])
        assert e.value.code == 2


def test_publish_member_is_repeatable_without_all():
    args = cli.build_parser().parse_args(
        ["delta", "npc", "publish", "--member", "a", "--member", "b", "--preview-sha", "s"])
    assert args.member == ["a", "b"]
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["delta", "npc", "publish", "--all"])


def test_plan_product_and_stop_choices():
    args = cli.build_parser().parse_args(
        ["delta", "plan", "--product", "grounding", "--product", "npc", "--stop", "review"])
    assert args.product == ["grounding", "npc"] and args.stop == "review"
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["delta", "plan", "--product", "all"])


def test_handler_dict_replaces_stub(monkeypatch):
    monkeypatch.setitem(delta_cli.DELTA_HANDLERS, "plan", lambda a: 0)
    assert cli.main(["delta", "plan", "--source", "x"]) == 0
