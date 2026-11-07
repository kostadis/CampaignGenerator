"""Shared helpers for the US2 NPC-update tests (not collected: no ``test_`` prefix)."""

from __future__ import annotations

import json
from pathlib import Path

from _delta_us2 import copy_fixture, make_plan  # noqa: F401
from pipelines.summary_native import npc_authored, npc_compose, npc_draft, npc_publish
from pipelines.summary_native.authority import AuthorityLedger
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.cli import main
from pipelines.summary_native.review.store import read_snapshot
from pipelines.summary_native.delta import census as census_mod

CANARY = "CANARY-SECRET-7f3a"

BRANNOC_MODEL = """## Identity

A dwarf smith of Emberfall. [ch 001 / entry]

## Personality and Motivations

He lights the forge again for the town. [ch 003 / 003.01]

## History with the Party

- Restarts the forge and swears to forge for the town again. [ch 003 / 003.01]
- Explains why the forge is cold. [ch 001 / 001.01]

## Last Observed State

As of chapter 003 the forge is lit. [ch 003 / 003.01]

## Relationships

- Tobin Fenwick offers to haul coal for him. [ch 003 / 003.01]

## Notable Quotes

> "Let it burn, then. Let it burn."
— Brannoc Ironvein [ch 003 / moment]

## Arc-Score Candidates

- "Let it burn, then. Let it burn." [ch 003 / moment]
"""

TOBIN_MODEL = """## Identity

A young fletcher in Emberfall. [ch 003 / entry]

## Personality and Motivations

Willing to help. [ch 003 / 003.01]

## History with the Party

- Offers to haul coal for the forge. [ch 003 / 003.01]

## Last Observed State

As of chapter 003 he watches the forge from the doorway. [ch 003 / 003.01]

## Relationships

- Helps Brannoc Ironvein at the forge. [ch 003 / 003.01]

## Notable Quotes

None in the evidence.

## Arc-Score Candidates

- Offers to haul coal. [ch 003 / 003.01]
"""


class FakeModel:
    """Stands in for ``stream_api``: records every prompt, answers by the NPC named in it."""

    def __init__(self, answers: dict[str, str] | None = None):
        self.answers = answers or {"Brannoc Ironvein": BRANNOC_MODEL, "Tobin Fenwick": TOBIN_MODEL}
        self.prompts: list[tuple[str, str]] = []

    def __call__(self, client, system, user, model, **kw):
        self.prompts.append((system, user))
        for name, text in self.answers.items():
            if f"subject: {name}" in user:
                return text
        raise AssertionError("no canned answer for this prompt")


def install_fake(monkeypatch, fake: FakeModel | None = None) -> FakeModel:
    fake = fake or FakeModel()
    monkeypatch.setattr(npc_draft, "stream_api", fake)
    monkeypatch.setattr(npc_draft, "client_from_args", lambda args, **kw: object())
    return fake


def census_for(root: Path, plan):
    census_mod.run_census(root, plan)
    return census_mod.load_census(root, plan.plan_id)


def _sole_plan(root: Path, plan=None):
    from pipelines.summary_native.delta import plan as dplan

    if plan is not None:
        return plan
    pdir = dplan.plans_dir(root)
    ids = sorted({p.stem.rsplit("-r", 1)[0] for p in pdir.glob("*-r*.json")})
    assert ids, "no plan saved"
    return dplan.load_plan(pdir, ids[-1])


def _npc_handoff(root: Path, plan) -> str:
    """The NPC half of `delta review handoff` (a plan that also carries grounding would need its four-document
    review for the other half, which these NPC tests do not have)."""
    from pipelines.summary_native.delta import cli_review

    return cli_review._handoff_npc(root, plan)["review_id"]


def handoff_and_sign(root: Path, capsys, stems: dict[str, str] | None = None, plan=None) -> dict[str, dict]:
    """The GM's real path: `delta review handoff` (one combined review + the publication binding), then the
    real exact-draft sign-off (`review npc sign`) for each named stem (default: every drafted member).

    Returns ``{stem: {"review_id", "item", "sha"}}``. Nothing is faked or bypassed.
    """
    plan = _sole_plan(root, plan)
    try:
        initialize_ledger(root, AuthorityLedger(version=2, campaign="delta-fixture", revision=1), actor="test")
    except Exception:  # noqa: BLE001 - already initialised by an earlier attempt
        pass
    main(["review", "init", "--campaign-dir", str(root), "--json"])
    capsys.readouterr()
    review_id = _npc_handoff(root, plan)
    _m, _c, items = read_snapshot(root, review_id)
    signed = {}
    for item in items:
        if item.proposed_action.action != "signoff_npc_draft":
            continue
        d = item.proposed_action.details
        stem = Path(d["draft_path"]).stem
        if stems is not None and stem not in stems:
            continue
        code = main(["review", "npc", "sign", review_id, "--item", item.item_id, "--draft-sha256",
                     d["draft_sha256"], "--expected-decision-revision", "0", "--reviewer", "GM",
                     "--campaign-dir", str(root), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 0, payload
        signed[stem] = {"review_id": review_id, "item": item.item_id, "sha": d["draft_sha256"]}
    return signed


def handoff_only(root: Path, capsys, plan=None) -> str:
    """`delta review handoff` with no sign-off: the publication binding exists, nothing is approved."""
    plan = _sole_plan(root, plan)
    try:
        initialize_ledger(root, AuthorityLedger(version=2, campaign="delta-fixture", revision=1), actor="test")
    except Exception:  # noqa: BLE001
        pass
    main(["review", "init", "--campaign-dir", str(root), "--json"])
    capsys.readouterr()
    return _npc_handoff(root, plan)


def sign_drafts(root: Path, range_dir: Path, members: dict[str, str], capsys,
                summaries=("001-the-cold-forge.md", "002-the-ledger.md", "003-the-new-fire.md")) -> dict[str, dict]:
    """Sign the named drafts through the real handoff + review CLI (see :func:`handoff_and_sign`).

    ``members`` maps draft stem -> subject. (``range_dir`` / ``summaries`` are kept for the old call shape:
    the handoff derives both from the plan's recorded drafts and spans.)
    """
    return handoff_and_sign(root, capsys, members)
