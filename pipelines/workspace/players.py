#!/usr/bin/env python3
"""``players`` — read the campaign's player entity, and report drift.

    players check [--campaign-dir DIR] [--vtt FILE]

**Deterministic, read-only, model-free.** It reports; it corrects nothing. Same
guarantee ``provenance`` and ``registry check`` carry, and for the same reason:
what to do about a finding is a scope decision, and scope decisions are the
GM's (Constitution II).

Every failure this feature exists to remove was *silent*. A character nobody
plays, a player who resolves in no transcript, a voice file left behind by a
rename — none of them stopped a run, and several of them ran for months.
``players check`` is where those become a list you can read before spending a
token, instead of something you notice in the output.

The one finding worth calling out is the last: **a display name absent from
this transcript**. The existing wrong-VTT pre-flight in ``scene_extract`` and
``enhance_summary`` fires only when *zero* expected names match, so it catches
the whole map being wrong and misses three-of-four matching while the fourth
vanishes. That second case is the one that has actually happened.

Lives in ``pipelines/`` rather than ``server/`` so it imports nothing from the
web layer (``tests/test_layering.py``) and runs from a campaign directory with
no server. ``GET /api/players/check`` calls :func:`collect_findings` directly,
so the page and the command line cannot disagree about whether a campaign is
coherent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from campaignlib.constants import config_path
from campaignlib.party_config import (
    PARTY_CONFIG_FILENAME,
    load_party_config,
    resolve_party_config,
)
from campaignlib.players_config import (
    PLAYERS_CONFIG_FILENAME,
    load_players_config,
    norm_name,
)


def _read_vtt_speakers(vtt: Path) -> set[str]:
    """Every ``Name:`` prefix that starts a line in ``vtt``.

    Deliberately the same shape ``normalize_vtt_speakers`` matches — a literal
    prefix at the start of a line — so "the check says this label is present"
    and "the rewrite will find this label" cannot disagree.
    """
    speakers: set[str] = set()
    for line in vtt.read_text(encoding="utf-8", errors="replace").splitlines():
        head, sep, _rest = line.partition(":")
        if sep and head and head == head.strip() and len(head) < 60:
            speakers.add(head)
    return speakers


#: Where a campaign conventionally keeps its voice specs and style examples.
#: ``new_workspace`` creates both, and every campaign on disk uses them.
DEFAULT_STYLE_DIRS = ("voice", "examples")


def collect_findings(
    campaign_dir: Path | str,
    vtt: Path | None = None,
    style_dirs: "tuple[str, ...] | None" = None,
) -> dict[str, Any]:
    """Everything incoherent about this campaign's player configuration.

    ``style_dirs`` is where to look for files nothing declares. It defaults to
    the convention, and is a parameter rather than a read of
    ``session_doc.yaml``'s ``voice_dir``/``examples_dir`` because that document
    belongs to ``server/`` and this module may not import it
    (``tests/test_layering.py``). A campaign that keeps its files elsewhere
    passes ``--style-dir`` — without which the orphan section would be silently
    empty, which is precisely the "reads as coverage and is not" failure #315
    was.

    Raises ``ValueError`` when a document will not load at all — that is not a
    finding about the campaign, it is the check being unable to run, and the
    two must not look the same.
    """
    campaign_dir = Path(campaign_dir)
    players_path = config_path(campaign_dir, PLAYERS_CONFIG_FILENAME)
    party_path = config_path(campaign_dir, PARTY_CONFIG_FILENAME)

    players = load_players_config(players_path)
    party = load_party_config(party_path) if party_path.exists() else None
    resolved = (
        resolve_party_config(party, campaign_dir, require_files=False)
        if party is not None else None
    )

    characters = [c.name for c in party.characters] if party else []
    known = {norm_name(c) for c in characters}

    # "Nobody has ever played this" — deliberately counting inactive players
    # too. A character whose player has left is historical, not broken
    # (FR-011a): their transcripts still resolve, and reporting it every run
    # would train the reader to ignore this section. What the check is for is
    # a character nobody has been recorded against at all.
    played_by_anyone = {norm_name(c) for p in players.players for c in p.plays}
    unplayed = [c for c in characters if norm_name(c) not in played_by_anyone]

    unknown = [
        {"player": p.id, "character": c}
        for p in players.players
        for c in p.plays
        if norm_name(c) not in known
    ]

    no_display_name = [
        p.id for p in players.players if p.active and not p.display_names
    ]

    missing_declared: list[dict[str, str]] = []
    declared_voice: list[Path] = []
    declared_examples: list[Path] = []
    if resolved is not None:
        for character in resolved.characters:
            for field in ("voice", "examples"):
                path = getattr(character, field)
                if path is None:
                    continue
                (declared_voice if field == "voice" else declared_examples).append(path)
                if not path.exists():
                    missing_declared.append({
                        "character": character.name,
                        "field": field,
                        "path": str(path),
                    })
        for path in resolved.shared_examples:
            declared_examples.append(path)
            if not path.exists():
                missing_declared.append({
                    "character": "<campaign>",
                    "field": "shared_examples",
                    "path": str(path),
                })

    # Orphans: files present but declared by nobody. This is what a rename
    # leaves behind, and under the rule feature 009 deleted it was invisible
    # twice over — the file reached no narrator, AND the detector built to
    # catch exactly this could not see it (#315).
    undeclared: list[str] = []
    claimed = {p.resolve() for p in declared_voice + declared_examples}
    scanned: list[str] = []
    for subdir in (style_dirs or DEFAULT_STYLE_DIRS):
        directory = (campaign_dir / subdir).expanduser()
        if not directory.is_dir():
            continue
        scanned.append(subdir)
        for f in sorted(directory.glob("*.md")):
            if f.name.startswith("_"):
                continue          # shared campaign material, not a per-character file
            if f.resolve() not in claimed:
                try:
                    undeclared.append(str(f.relative_to(campaign_dir)))
                except ValueError:
                    undeclared.append(str(f))

    absent_in_vtt: list[str] = []
    if vtt is not None:
        present = _read_vtt_speakers(vtt)
        expected = [n for p in players.players for n in p.display_names]
        absent_in_vtt = [n for n in expected if n not in present]

    findings = {
        "unplayed_characters": unplayed,
        "unknown_characters": unknown,
        "players_without_display_name": no_display_name,
        "missing_declared_files": missing_declared,
        "undeclared_files": undeclared,
        "absent_in_vtt": absent_in_vtt,
    }
    findings["clean"] = not any(v for k, v in findings.items() if k != "clean")
    # Not a finding — a statement of coverage. An empty orphan section means
    # something different depending on whether anything was scanned.
    findings["scanned_dirs"] = scanned
    return findings


def _report(findings: dict[str, Any], *, checked_vtt: bool) -> None:
    def section(title: str, rows: list, render=str) -> None:
        print(f"\n=== {title} ===")
        if rows:
            for row in rows:
                print(f"  {render(row)}")
        else:
            print("  none")

    section("Characters nobody plays", findings["unplayed_characters"])
    section(
        "Unknown character references",
        findings["unknown_characters"],
        lambda r: f"player {r['player']!r} plays {r['character']!r}, "
                  f"which is not in {PARTY_CONFIG_FILENAME}",
    )
    section("Players with no display name", findings["players_without_display_name"])
    section(
        "Declared files that are missing",
        findings["missing_declared_files"],
        lambda r: f"{r['character']}.{r['field']} -> {r['path']}",
    )
    section("Files nothing declares", findings["undeclared_files"])
    # An empty section means two different things, so say which. "Nothing was
    # scanned" reading as "nothing is wrong" is the failure #315 was.
    scanned = findings.get("scanned_dirs") or []
    if scanned:
        print(f"  (scanned: {', '.join(scanned)})")
    else:
        print("  (scanned nothing — no style directory found. Pass --style-dir "
              "if this campaign keeps its voice/example files elsewhere.)")
    if checked_vtt:
        section("Display names absent from this transcript", findings["absent_in_vtt"])
    else:
        print("\n=== Display names absent from this transcript ===")
        print("  not checked — pass --vtt FILE")


def cmd_check(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir).expanduser()
    vtt = Path(args.vtt).expanduser() if args.vtt else None
    if vtt is not None and not vtt.is_file():
        print(f"Error: --vtt not found: {vtt}", file=sys.stderr)
        return 1
    style_dirs = tuple(args.style_dir) if args.style_dir else None
    try:
        findings = collect_findings(campaign_dir, vtt, style_dirs)
    except ValueError as exc:
        # A document that will not load is the check being unable to run, not a
        # finding about the campaign. obelisk's party.yaml is a PC-name
        # exclusion list rather than a roster and lands here.
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _report(findings, checked_vtt=vtt is not None)
    if findings["clean"]:
        print("\nClean.")
        return 0
    print("\nFindings above. Nothing was changed — this check only reports.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="players",
        description="Read the campaign's player entity and report drift. "
                    "Read-only: no model call, no writes.",
    )
    sub = p.add_subparsers(dest="command", required=True)
    pc = sub.add_parser(
        "check",
        help="report characters nobody plays, unresolvable references, "
             "missing declared files, and files nothing declares",
    )
    pc.add_argument("--campaign-dir", default=".",
                    help="Campaign root (default: the current directory).")
    pc.add_argument("--style-dir", metavar="DIR", action="append", default=None,
                    help="Where this campaign keeps its voice and example "
                         f"files, relative to the campaign root. Repeatable. "
                         f"Defaults to {', '.join(DEFAULT_STYLE_DIRS)}. Only "
                         f"the 'files nothing declares' section reads it.")
    pc.add_argument("--vtt", metavar="FILE", default=None,
                    help="A transcript to check display names against. Reports "
                         "EACH expected name that does not appear — including "
                         "when only one of several is absent, which the "
                         "wrong-VTT pre-flight in scene_extract cannot see.")
    pc.set_defaults(func=cmd_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
