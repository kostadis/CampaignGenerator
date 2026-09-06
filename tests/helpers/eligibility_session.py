"""Fixtures modelling the session that produced issue #385.

Phandalin ``summaries/20260902``: four roster characters, three players at the
table, five scenes. Brewbarry's player was absent — he has **zero** speaker
labels in every scene — and Valphine is absent from scene 3 only.

The detail that matters most is :data:`SCENE_05`. The GM *narrates about*
Brewbarry there ("Brewbarry's already in the tavern") without ever labelling
him, so a presence check that greps for the name instead of anchoring on the
label marks him present in exactly the scene this feature exists to fix. Any
parser change that passes the other fixtures but fails this one has
reintroduced the bug.
"""

from __future__ import annotations

# ── The tape ────────────────────────────────────────────────────────────────
#: Speaker labels are the *players'* display names, not character names.
VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Kostadis Roussos: Alright, we pick up outside the Common Chord.

2
00:00:04.000 --> 00:00:07.000
David Mendenhall: I want to check the noticeboard: anything about spiders?

3
00:00:07.000 --> 00:00:09.000
Wade Brown: My rat goes in first.

4
00:00:09.000 --> 00:00:12.000
Gary Young: I'll hang back and watch the street.
"""

#: The same session with only the GM speaking — the uncoverable case. No
#: session on disk has one, so User Story 3 cannot be regression-tested from
#: a real recording.
VTT_GM_ONLY = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Kostadis Roussos: You travel for three days without incident.
"""

PLAYERS_YAML = """players:
- id: stphane
  name: Stéphane Bourdeaud
  display_names:
  - Stéphane Bourdeaud
  plays:
  - Brewbarry
- id: gary
  name: Gary Young
  display_names:
  - Gary Young
  plays:
  - Valphine Sotorra
- id: wade
  name: Wade Brown
  display_names:
  - Wade Brown
  plays:
  - Soma
- id: david
  name: David Mendenhall
  display_names:
  - David Mendenhall
  plays:
  - Vukradin
- id: kostadis
  name: Kostadis Roussos
  display_names:
  - Kostadis Roussos
  plays: []
  gm: true
"""

ROSTER = ["Vukradin", "Valphine Sotorra", "Soma", "Brewbarry"]

# ── The scenes ──────────────────────────────────────────────────────────────
_HEAD = """---
scene: {name}
source: gmassist
---

# {name}

## Scene summary (from gm-assist, verbatim)

{summary}

## Verbatim moments

{moments}
"""


def _scene(name: str, summary: str, moments: str) -> str:
    return _HEAD.format(name=name, summary=summary, moments=moments)


SCENE_01 = _scene(
    "Rumors and Preparations at the Common Chord",
    "- The party gathers at the Common Chord.\n"
    "- Brewbarry mentions he has heard of a tavern uptown.",
    '**GM** — *setting the scene*\n'
    '> "You are at the Common Chord."\n\n'
    '**Vukradin** — *reading the noticeboard*\n'
    '> "Anything about spiders?"\n\n'
    '**Soma** — *asking about the job*\n'
    '> "Who posted it?"\n\n'
    '**Valphine Sotorra** — *watching the door*\n'
    '> "Someone just came in behind you."\n',
)

SCENE_02 = _scene(
    "The Sewer Stakeout",
    "- The party waits in the sewer for the carrier.",
    '**GM** — *describing the tunnel*\n'
    '> "The water is ankle deep."\n\n'
    '**Vukradin**\n'
    '> "How many crates did you count?"\n\n'
    '**Soma**\n'
    '> "Nine. I counted twice."\n\n'
    '**Valphine Sotorra**\n'
    '> "The ninth one is not like the others."\n',
)

#: Valphine has no label here — she is present in the session but not in this
#: scene. Filter B must exclude her; Soma's two lines must not exclude *her*.
#: Vukradin carries this scene; Soma has a single line over the sending stone
#: and Valphine has none. The real scene 3 is 66 turns against 2 against 0 —
#: the asymmetry matters, because presence and not volume is what decides
#: eligibility (FR-009). Soma stays a candidate; Valphine does not.
MOMENTS_03 = (
    '**GM** — *as Rsolk*\n'
    '> "This is my tunnel."\n\n'
    '**Vukradin**\n'
    '> "Then we should talk terms."\n\n'
    '**Vukradin** — *offering a cut*\n'
    '> "One in five of whatever we clear."\n\n'
    '**Vukradin** — *on the spiders*\n'
    '> "How many of them are down there?"\n\n'
    '**GM** — *as Rsolk, counting*\n'
    '> "More than you would like."\n\n'
    '**Vukradin** — *closing the deal*\n'
    '> "Then it is honest work."\n\n'
    '**Soma** — *over the sending stone*\n'
    '> "Are you still breathing?"\n'
)

SCENE_03 = _scene(
    "Encounter in the Sewers",
    "- Vukradin is separated and meets Rsolk.",
    MOMENTS_03,
)

SCENE_04 = _scene(
    "The Stakeout of Denvar",
    "- The party waits for Denvar to collect his payment.\n"
    "- Brewbarry is not with them.",
    '**GM**\n'
    '> "Denvar sleeps until dusk."\n\n'
    '**Soma**\n'
    '> "My rat has the doorway."\n\n'
    '**Vukradin**\n'
    '> "Wake me when he moves."\n\n'
    '**Valphine Sotorra**\n'
    '> "He is moving now."\n',
)

#: THE critical fixture, on two counts.
#:
#: 1. "Brewbarry" appears three times in the *moments* text and never once as a
#:    speaker label, so a substring search marks him present.
#: 2. The gm-assist summary opens a **bold** line with his name, so a parser
#:    that reads the whole document instead of just the moments section picks
#:    him up as a label.
#:
#: Both are how the real scene 05 is shaped. A parser that survives one and not
#: the other has reintroduced the bug.
MOMENTS_05 = (
    '**GM** — *placing Brewbarry in the tavern*\n'
    '> "Brewbarry\'s already in the tavern."\n\n'
    '**Vukradin** — *describing Brewbarry\'s old circumstances*\n'
    '> "He could never have afforded that place."\n\n'
    '**Soma** — *sending the rat through*\n'
    '> "There is an office behind the wall."\n\n'
    '**Valphine Sotorra**\n'
    '> "Harper sigil on the desk."\n\n'
    '**GM** — *having Brewbarry enter*\n'
    '> "So, Brewbarry... Brewbarry walks in."\n'
)

SCENE_05 = _scene(
    "The Dead Drop at the House of a Thousand Faces",
    "**Brewbarry enters the House of a Thousand Faces**\n\n"
    "- The party investigates the dead drop.\n"
    "- Brewbarry, who had heard of the high-end tavern when he was too poor to\n"
    "  afford it, immediately enters while the others remain outside.",
    MOMENTS_05,
)

#: A scene no player character speaks in — pure GM narration, plus a bracketed
#: action-beat header of the kind ``config/agents/scene_extract.md`` permits.
MOMENTS_UNCOVERABLE = (
    '**GM** — *narrating the journey*\n'
    '> "You travel for three days without incident."\n\n'
    '**[The Long Road North]**\n'
    '- Three days pass.\n'
    '- Nobody speaks of the Harper office.\n'
)

SCENE_UNCOVERABLE = _scene(
    "Three Days on the Road",
    "- The party travels north without incident.",
    MOMENTS_UNCOVERABLE,
)

SCENES = [
    ("01_rumors_and_preparations", SCENE_01),
    ("02_the_sewer_stakeout", SCENE_02),
    ("03_encounter_in_the_sewers", SCENE_03),
    ("04_the_stakeout_of_denvar", SCENE_04),
    ("05_the_dead_drop", SCENE_05),
]

SCENES_WITH_UNCOVERABLE = SCENES + [("06_three_days_on_the_road", SCENE_UNCOVERABLE)]


def write_session(tmp_path, *, uncoverable: bool = False, gm_only_vtt: bool = False):
    """Materialise the fixture session. Returns ``(scene_dir, vtt, players)``."""
    scene_dir = tmp_path / "scene_extractions"
    scene_dir.mkdir(parents=True, exist_ok=True)
    scenes = SCENES_WITH_UNCOVERABLE if uncoverable else SCENES
    for stem, text in scenes:
        (scene_dir / f"{stem}.md").write_text(text, encoding="utf-8")

    vtt = tmp_path / "session.transcript.vtt"
    vtt.write_text(VTT_GM_ONLY if gm_only_vtt else VTT, encoding="utf-8")

    players = tmp_path / "players.yaml"
    players.write_text(PLAYERS_YAML, encoding="utf-8")
    return scene_dir, vtt, players
