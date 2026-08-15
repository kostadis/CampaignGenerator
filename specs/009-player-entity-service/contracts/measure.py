"""Measurement for spec 009 — run against the live campaigns.

Prints the state of player identity, example routing and voice resolution for
every campaign under $CAMPAIGNS_ROOT (default ~/src/campaigns).

`contracts/baseline.txt` holds the BEFORE reading, taken at T002 with the old
loaders. This script was rewritten when those loaders were deleted, so the two
are not line-for-line comparable — read them side by side rather than diffing.
What must be true after:

  A. every campaign records its players in players.yaml (obelisk excepted —
     its party.yaml is a PC-name exclusion list, not a roster);
  B. no example file reaches a narrator that nothing declares. Before: 6,036
     chars in obelisk, 7,285 in stormgiants and 51,073 in toee reached EVERY
     narrator by falling through, none of it chosen;
  C. every voice file is either declared or reported as an orphan. Before:
     four across two campaigns were unreachable and invisible.

Run it from the repo root:
    python3 specs/009-player-entity-service/contracts/measure.py
"""
import os
import sys
from pathlib import Path

# Repo root is three levels up: contracts/ -> 009-.../ -> specs/ -> repo.
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from campaignlib.party_config import load_party_config, resolve_party_config
from campaignlib.players_config import (
    PLAYERS_CONFIG_FILENAME,
    load_players_config,
    speaker_map,
)
from pipelines.workspace.players import collect_findings
from session_doc.examples import load_declared_examples, load_shared_examples
from session_doc.voice import load_declared_voices

CAMPAIGNS = Path(os.environ.get("CAMPAIGNS_ROOT") or "~/src/campaigns").expanduser()
NAMES = ("Phandalin", "out-of-the-abyss", "stormgiants", "toee", "Hillsfar", "obelisk")


def _load(name: str):
    root = CAMPAIGNS / name
    party_path = root / "config" / "party.yaml"
    players_path = root / "config" / PLAYERS_CONFIG_FILENAME
    party = load_party_config(party_path) if party_path.exists() else None
    players = load_players_config(players_path)
    resolved = (
        resolve_party_config(party, root, require_files=False) if party else None
    )
    return root, party, players, resolved


print("=" * 78)
print("A. the player entity")
print("=" * 78)
for name in NAMES:
    try:
        root, party, players, _ = _load(name)
    except ValueError as exc:
        print(f"{name:20s} CANNOT LOAD: {str(exc)[:90]}")
        continue
    chars = len(party.characters) if party else 0
    gm = [p.id for p in players.players if p.gm]
    labels = sum(len(p.display_names) for p in players.players)
    print(f"{name:20s} {chars} characters, {len(players.players)} players, "
          f"{labels} display names, gm={gm or 'none'}")

print()
print("=" * 78)
print("B. what reaches a narrator, and why")
print("=" * 78)
for name in NAMES:
    try:
        _root, party, _players, resolved = _load(name)
    except ValueError as exc:
        print(f"{name:20s} CANNOT LOAD")
        continue
    if resolved is None:
        print(f"{name:20s} no roster")
        continue
    per_char = load_declared_examples(resolved)
    shared = load_shared_examples(resolved)
    print(f"{name:20s} per-character examples: {sorted(per_char) or 'none'}")
    print(f"{'':20s} shared block: {len(shared) if shared else 0} chars "
          f"({len(resolved.shared_examples)} file(s) DECLARED)")

print()
print("=" * 78)
print("C. voice specs, and files nothing declares")
print("=" * 78)
for name in NAMES:
    try:
        _root, _party, _players, resolved = _load(name)
    except ValueError:
        print(f"{name:20s} CANNOT LOAD")
        continue
    if resolved is None:
        print(f"{name:20s} no roster")
        continue
    voices = load_declared_voices(resolved)
    try:
        findings = collect_findings(CAMPAIGNS / name)
        orphans = findings["undeclared_files"]
    except ValueError:
        orphans = ["<check could not run>"]
    print(f"{name:20s} declared voices: {sorted(voices) or 'none'}")
    print(f"{'':20s} nothing declares: {orphans or 'none'}")

print()
print("=" * 78)
print("D. the speaker map, from the entity")
print("=" * 78)
for name in NAMES:
    try:
        _root, party, players, _ = _load(name)
    except ValueError:
        print(f"{name:20s} CANNOT LOAD")
        continue
    if party is None:
        continue
    mapped = speaker_map(players, party)
    print(f"{name:20s} {mapped or '{} (no display names recorded)'}")
