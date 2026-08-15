"""One-shot adoption CLI — feature 009.

    python -m server.migrate_players_config --campaign-dir DIR [--config-dir config] [--force]

Builds a campaign's first ``players.yaml`` from what it already records, moves
the voice and example declarations into ``party.yaml``, and removes the retired
fields from both ``party.yaml`` and ``session_doc.yaml``.

**It reports conflicts; it does not resolve them.** Where two sources disagree
about a person, both values and their origins are printed and *neither* is
written. Choosing between them is attribution — a precision decision, and the
GM's (Constitution II). A merge rule here would be exactly the "LLM structures"
step the repo's pipeline rule forbids, done in Python instead of a prompt,
which is no better.

Lives in ``server/`` because it must read **and then strip**
``session_doc.yaml``'s ``roster`` group, which is a ``server/`` model — the same
reason every other one-shot migration in this repo lives here.

Both documents are read **raw** via ``yaml.safe_load``, deliberately not
through their typed loaders: ``load_party_config`` now *refuses* a document
carrying ``player:``, and ``SessionEditorConfig`` no longer declares ``roster``,
so the typed path would reject or silently drop exactly the data this CLI
exists to rescue. ``migrate_grounding_config.py`` records the same reasoning.

**Expect very little from four of the six campaigns, and say so.** Only
Phandalin and out-of-the-abyss record a ``player:`` at all; stormgiants, toee
and Hillsfar record none, and obelisk's ``party.yaml`` is not a roster (see
:func:`_refuse_non_roster`). An almost-empty result there is the correct
outcome, not a failure — the output states it rather than letting silence read
as a bug.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from campaignlib.npc import is_player_placeholder
from campaignlib.party_config import PARTY_CONFIG_FILENAME
from campaignlib.players_config import (
    PLAYERS_CONFIG_FILENAME,
    Player,
    PlayersConfig,
    save_players_config,
)
from campaignlib.textproc import split_frontmatter
from campaignlib.util import atomic_write_text

SESSION_DOC_FILENAME = "session_doc.yaml"


# ── reading ─────────────────────────────────────────────────────────────────


def _load_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _refuse_non_roster(party_raw: dict[str, Any], path: Path) -> str | None:
    """obelisk's shape: a ``characters:`` list whose entries have no ``sheet:``.

    That file is a PC-name **exclusion list** for the entity registry, read by
    ``campaignlib.party.load_party_names`` — two readers, two contracts, one
    filename. Which use wins is a ruling about campaign data, so this refuses
    the campaign by name rather than inventing a roster or crashing on the
    ``ValueError`` the typed loader would raise.
    """
    entries = party_raw.get("characters") or []
    if not entries:
        return None
    if any(isinstance(e, dict) and e.get("sheet") for e in entries):
        return None
    return (
        f"{path} lists characters but none of them names a sheet.\n"
        f"  That file is a PC-name exclusion list for the entity registry "
        f"(campaignlib.party.load_party_names reads it), not a roster.\n"
        f"  Two uses of one filename is a GM ruling, not something a migration "
        f"can decide. Refusing this campaign."
    )


def _sheet_player(campaign_dir: Path, sheet_rel: str) -> str | None:
    """The ``player:`` line from a character sheet's frontmatter, or ``None``.

    A second opinion, not an authority — a D&D Beyond export stamps the
    *downloader's* name into every sheet, which is why toee's four sheets all
    say ``kostadis1``. Harvested only so a disagreement can be reported.
    """
    sheet = (campaign_dir / sheet_rel).expanduser()
    if not sheet.is_file():
        return None
    frontmatter, _body = split_frontmatter(sheet.read_text(encoding="utf-8"))
    if not frontmatter:
        return None
    value = str(frontmatter.get("player") or "").strip()
    return value or None


def _slug(name: str, taken: set[str]) -> str:
    """A short identifier proposed from a person's name.

    A *proposal*: the GM reviews the result, and the slug is what makes the
    same person the same id across campaigns, which no tool can know. Derived
    once and never re-derived — that is the difference between this and a
    key that goes stale when the name is corrected.
    """
    base = re.sub(r"[^a-z0-9]+", "", name.strip().lower().split()[0]) or "player"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}{n}", n + 1
    taken.add(slug)
    return slug


# ── the old routing rule, applied once, to propose declarations ─────────────


def _routes_to(stem: str, first_name: str) -> bool:
    """The deleted rule, kept here **only** to migrate away from it.

    This is the one legitimate use of prefix matching left: reproducing what a
    campaign's files resolved to yesterday, so today's declarations start from
    the same answer instead of from nothing. Every file it cannot attribute is
    reported, not guessed at.
    """
    if not first_name:
        return False
    return (stem == first_name
            or stem.startswith(first_name + "_")
            or stem.startswith(first_name + "-"))


def _propose_declarations(
    campaign_dir: Path, subdir: str, characters: list[str], suffix: str = "",
) -> tuple[dict[str, str], list[str]]:
    """``{character: relative path}`` plus the files attributed to nobody."""
    directory = campaign_dir / subdir
    if not directory.is_dir():
        return {}, []
    declared: dict[str, str] = {}
    orphans: list[str] = []
    for f in sorted(directory.glob("*.md")):
        if f.name.startswith("_"):
            continue
        stem = f.stem.lower().removesuffix(suffix)
        rel = f"{subdir}/{f.name}"
        for character in characters:
            first = character.strip().lower().split()[0] if character.strip() else ""
            if _routes_to(stem, first) and character not in declared:
                declared[character] = rel
                break
        else:
            orphans.append(rel)
    return declared, orphans


# ── the migration ───────────────────────────────────────────────────────────


def migrate(campaign_dir: Path, config_dir: str, force: bool) -> int:
    base = campaign_dir / config_dir
    party_path = base / PARTY_CONFIG_FILENAME
    players_path = base / PLAYERS_CONFIG_FILENAME
    session_doc_path = base / SESSION_DOC_FILENAME

    if not party_path.exists():
        print(f"Error: no {party_path} — nothing to adopt.", file=sys.stderr)
        return 1
    if players_path.exists() and not force:
        print(
            f"Error: refusing to overwrite {players_path}. Pass --force if that "
            f"is what you want.",
            file=sys.stderr,
        )
        return 1

    party_raw = _load_raw(party_path)
    refusal = _refuse_non_roster(party_raw, party_path)
    if refusal:
        print(f"Error: {refusal}", file=sys.stderr)
        return 1

    entries = [e for e in (party_raw.get("characters") or []) if isinstance(e, dict)]
    characters = [str(e["name"]) for e in entries if e.get("name")]
    session_raw = _load_raw(session_doc_path)
    roster_block = session_raw.get("roster") or {}

    conflicts: list[str] = []
    conflicted: set[str] = set()
    notes: list[str] = []

    # ── players ─────────────────────────────────────────────────────────
    taken: set[str] = set()
    players: list[dict[str, Any]] = []
    for entry in entries:
        name = str(entry.get("name") or "")
        roster_value = str(entry.get("player") or "").strip()
        sheet_value = _sheet_player(campaign_dir, str(entry.get("sheet") or ""))

        if is_player_placeholder(roster_value):
            roster_value = ""
        if sheet_value and is_player_placeholder(sheet_value):
            sheet_value = None

        if roster_value and sheet_value and roster_value != sheet_value:
            conflicted.add(name)
            conflicts.append(
                f"{name}: party.yaml says {roster_value!r}, the sheet says "
                f"{sheet_value!r}. Neither written, and the value is LEFT in "
                f"party.yaml so it is not lost — that file will refuse to load "
                f"until you rule on it and move the answer to players.yaml."
            )
            continue
        person = roster_value or sheet_value
        if not person:
            notes.append(f"{name}: no player recorded anywhere.")
            continue
        # A `/`- or `,`-separated field is a co-piloted character: two humans,
        # one PC. Both become players, both bound to it.
        for who in [p.strip().rstrip("*").strip() for p in re.split(r"[/,]", person)]:
            if not who or is_player_placeholder(who):
                continue
            existing = next((p for p in players if p["name"] == who), None)
            if existing is not None:
                existing["plays"].append(name)
                continue
            players.append({
                "id": _slug(who, taken),
                "name": who,
                "display_names": [who],
                "plays": [name],
            })

    gm_player = str(roster_block.get("gm_player") or "").strip()
    if gm_player and not is_player_placeholder(gm_player):
        existing = next((p for p in players if p["name"] == gm_player), None)
        if existing is not None:
            existing["gm"] = True
        else:
            players.append({
                "id": _slug(gm_player, taken),
                "name": gm_player,
                "display_names": [gm_player],
                "plays": [],
                "gm": True,
            })

    # ── declarations ────────────────────────────────────────────────────
    voices, voice_orphans = _propose_declarations(
        campaign_dir, "voice", characters, suffix="_voice")
    examples, example_orphans = _propose_declarations(
        campaign_dir, "examples", characters)

    # ── report before writing ───────────────────────────────────────────
    print(f"Adopting {campaign_dir}")
    print(f"  characters:      {len(characters)}")
    print(f"  players drafted: {len(players)}")
    if not players:
        print("    (none — this campaign records no player anywhere. That is "
              "the correct result for four of the six campaigns, not a "
              "failure: fill players.yaml in on the Players page.)")
    for p in players:
        flag = " [GM]" if p.get("gm") else ""
        print(f"    - {p['id']}: {p['name']} plays {p['plays'] or '(nobody)'}{flag}")
    print(f"  voice declared:    {len(voices)} of {len(characters)}")
    print(f"  examples declared: {len(examples)} of {len(characters)}")

    if voice_orphans or example_orphans:
        print("\n  Files attributed to nobody — RULE ON THESE. Nothing was "
              "written for them:")
        for rel in voice_orphans:
            print(f"    - {rel}")
        for rel in example_orphans:
            print(f"    - {rel}")
        print("\n    Each is one of three things and only you can say which:")
        print("      * campaign-wide style      -> add it to shared_examples "
              "in party.yaml")
        print("      * a character's own file whose name no longer matches "
              "-> add a 'voice:'/'examples:' entry to that character")
        print("      * an orphan from a rename, or a non-PC narrator's file "
              "-> delete it, or leave it and accept the check reporting it")
        print("\n    Ready to paste into party.yaml if they ARE campaign-wide:")
        print("      shared_examples:")
        for rel in example_orphans:
            print(f"      - {rel}")
    if notes:
        print("\n  Notes:")
        for n in notes:
            print(f"    - {n}")
    if conflicts:
        print("\n  CONFLICTS — nothing was written for these:")
        for c in conflicts:
            print(f"    - {c}")

    unrecognised = sorted(set(roster_block) - {"characters", "gm_player"})
    if unrecognised:
        print(f"\n  Unrecognised keys under session_doc.yaml's roster, left "
              f"behind: {', '.join(unrecognised)}")

    # ── write ───────────────────────────────────────────────────────────
    # Written through the service's own saver, which re-runs the uniqueness
    # rules. A raw dump here could produce a file that fails its own loader —
    # `party.yaml` saying `player: Wade` and `session_doc.yaml` saying
    # `gm_player: wade` are two rows whose display names collide, and the
    # migration would have reported success over a document nothing can read.
    try:
        save_players_config(
            players_path,
            PlayersConfig(players=[Player.model_validate(p) for p in players]),
        )
    except ValueError as exc:
        print(
            f"Error: the drafted roster is not valid, so nothing was written:\n"
            f"  {exc}\n"
            f"  Nothing else was changed either — {party_path} and "
            f"{session_doc_path} are untouched.",
            file=sys.stderr,
        )
        return 1

    for entry in entries:
        name = str(entry.get("name") or "")
        # A conflicting `player:` STAYS. Reporting "nothing was written" and
        # then deleting the value from the only file that held it would leave
        # the GM recovering it from scrollback. party.yaml refuses to load
        # while it is there, which is the right kind of stuck: loud, and one
        # ruling away from fixed.
        if name not in conflicted:
            entry.pop("player", None)
        if name in voices:
            entry["voice"] = voices[name]
        if name in examples:
            entry["examples"] = examples[name]
    party_raw["characters"] = entries
    # `shared_examples` is deliberately NOT written from the unattributed
    # files. "This file matched no character" and "this file belongs to the
    # whole campaign" are the same observation, and treating them as the same
    # decision is precisely the fall-through feature 009 deleted: it is how
    # stormgiants' typo'd `thistl.md` reached all four narrators. The tool
    # prints a ready-to-paste block; the GM decides which of the three cases
    # each file is.
    atomic_write_text(
        party_path,
        yaml.safe_dump(party_raw, default_flow_style=False, sort_keys=False,
                       allow_unicode=True),
    )

    if session_doc_path.exists() and "roster" in session_raw:
        session_raw.pop("roster")
        atomic_write_text(
            session_doc_path,
            yaml.safe_dump(session_raw, default_flow_style=False,
                           sort_keys=False, allow_unicode=True),
        )
        print(f"\n  removed the retired roster group from {session_doc_path}")

    print(f"\nWrote {players_path}")
    print(f"Updated {party_path}")
    print("\nReview the result, then run:  players check --campaign-dir "
          f"{campaign_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="One-shot: build players.yaml and move the voice/example "
                    "declarations into party.yaml. Reports conflicts rather "
                    "than resolving them.",
    )
    p.add_argument("--campaign-dir", required=True)
    p.add_argument("--config-dir", default="config")
    p.add_argument("--force", action="store_true",
                   help="Overwrite an existing players.yaml.")
    args = p.parse_args(argv)
    return migrate(Path(args.campaign_dir).expanduser(), args.config_dir, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
