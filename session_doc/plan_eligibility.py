"""Who may narrate what — the deterministic half of Pass 3's choice.

Issue #385: ``sd_plan`` assigned Brewbarry as the sole first-person narrator of
a scene he speaks zero lines in, in three independent runs, because his player
was not at the table and the prompt was told to give every roster character a
scene. Three mechanisms produced it — the prompt saw only scene *titles*, the
roster was the whole campaign cast, and the only coverage check in the system
checked coverage of the roster rather than of the scene.

Who narrates a scene is an **attribution decision** (Constitution II). This
module takes the *eligibility* half of it away from the model and settles it
from evidence already on disk:

- **Filter A — session attendance.** A player is present iff one of their
  declared display names appears on the tape. A character played only by absent
  players leaves the pool for the whole session.
- **Filter B — scene presence.** Within the pool, a character with no speaker
  label in a scene cannot narrate that scene.

The two read *different label spaces* and are deliberately not one mechanism
applied twice: a VTT carries player display names (``David Mendenhall``), while
``scene_extract`` normalises its output to character names (``Vukradin``).

Everything here is pure. No file I/O, no argparse, no model call — it is handed
strings and returns data, so the rules can be tested without an API key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from campaignlib.players_config import (
    GM_LABEL,
    PlayersConfig,
    absent_characters,
    attending_players,
    norm_name,
    player_name_for,
)
from campaignlib.vtt import speaker_labels
from session_doc.io import scene_speakers


@dataclass(frozen=True)
class Exclusion:
    """One character kept out of one choice, and why.

    Reported, never applied silently. The GM ruled that attendance is read from
    the tape with no override, which makes a wrong exclusion — a player covering
    an absent player's character — correctable only by hand. A correction
    nobody was told about cannot be made.
    """

    character: str
    reason: str
    player: str | None = None
    scene: str | None = None


@dataclass
class Eligibility:
    """The narrator pool, the per-scene candidates, and the evidence for both."""

    pool: set[str]
    candidates: dict[str, set[str]]
    uncoverable: list[str]
    absent_exclusions: list[Exclusion]
    scene_exclusions: list[Exclusion]
    attendance: dict[str, str] = field(default_factory=dict)
    line_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    unrecognised_labels: dict[str, set[str]] = field(default_factory=dict)

    @property
    def has_uncoverable(self) -> bool:
        return bool(self.uncoverable)


def _canonical(roster: list[str]) -> dict[str, str]:
    """Folded name → the roster's own spelling of it."""
    return {norm_name(name): name for name in roster}


def compute_eligibility(
    *,
    scenes: list[dict],
    roster: list[str],
    players: PlayersConfig,
    vtt_text: str,
) -> Eligibility:
    """Apply both filters.

    ``scenes`` is :func:`session_doc.io.load_scene_extractions` output — the
    ``moments`` body of each is the presence evidence, and the ``summary`` body
    is deliberately never consulted. In the real scene 05 the GM narrates
    *about* the absent character without labelling him, and the gm-assist
    summary carries bold headers of its own; either would mark him present.
    """
    labels = speaker_labels(vtt_text)
    canonical = _canonical(roster)

    # ── Filter A ────────────────────────────────────────────────────────────
    absent = absent_characters(players, roster, labels)
    attending = attending_players(players, labels)
    attendance = {
        p.name: next((n for n in p.display_names if n in labels), "")
        for p in players.players
        if p.active
    }
    absent_exclusions = [
        Exclusion(
            character=character,
            player=player_name_for(players, character),
            reason="player has no speaker label on this tape",
        )
        for character in sorted(absent)
    ]
    pool = {c for c in roster if c not in absent}

    # ── Filter B ────────────────────────────────────────────────────────────
    candidates: dict[str, set[str]] = {}
    line_counts: dict[str, dict[str, int]] = {}
    unrecognised: dict[str, set[str]] = {}
    scene_exclusions: list[Exclusion] = []
    uncoverable: list[str] = []

    for scene in scenes:
        name = scene.get("name", "")
        moments = scene.get("moments") or ""
        present_labels = scene_speakers(moments)

        present: set[str] = set()
        strangers: set[str] = set()
        for label in present_labels:
            known = canonical.get(norm_name(label))
            if known is None:
                strangers.add(label)
            else:
                present.add(known)

        eligible = present & pool
        candidates[name] = eligible
        line_counts[name] = _count_lines(moments, canonical)
        if strangers:
            unrecognised[name] = strangers

        for character in sorted(pool - present):
            scene_exclusions.append(
                Exclusion(
                    character=character,
                    scene=name,
                    reason="no speaker label in this scene",
                )
            )
        if not eligible:
            uncoverable.append(name)

    return Eligibility(
        pool=pool,
        candidates=candidates,
        uncoverable=uncoverable,
        absent_exclusions=absent_exclusions,
        scene_exclusions=scene_exclusions,
        attendance=attendance,
        line_counts=line_counts,
        unrecognised_labels=unrecognised,
    )


def _count_lines(moments: str, canonical: dict[str, str]) -> dict[str, int]:
    """How many labelled turns each roster character has.

    Evidence for the GM's eye only. It never gates eligibility: one label is
    enough, and a threshold above zero would be a tuning knob with no
    defensible value (FR-009). Soma has two lines against Vukradin's
    sixty-six in the real scene 03 and both are legitimate narrators of it.
    """
    counts: dict[str, int] = {}
    for line in moments.splitlines():
        stripped = line.strip()
        if not stripped.startswith("**"):
            continue
        label = stripped[2:].split("**", 1)[0].strip()
        if not label or label.startswith("[") or label == GM_LABEL:
            continue
        known = canonical.get(norm_name(label))
        if known:
            counts[known] = counts.get(known, 0) + 1
    return counts


def report_eligibility(e: Eligibility, *, vtt_path=None) -> None:
    """Print every exclusion, before the model call.

    Not decoration. The GM ruled that attendance is read from the tape with no
    override, which knowingly gets one case wrong: when one player voices an
    absent player's character for a night, those lines carry the *covering*
    player's label, so the covered character reads as absent and is excluded.
    The correction path is the GM editing the plan by hand — which works only
    if they were told. A silent wrong exclusion is the same class of failure as
    the silent wrong inclusion this feature removes.

    Unrecognised labels are reported rather than dropped: a label arriving as
    ``Vukradin (David)`` instead of ``Vukradin`` would otherwise cost that
    character their eligibility with nothing to show for it.
    """
    if e.absent_exclusions:
        where = f" ({vtt_path.name})" if vtt_path is not None else ""
        print(f"\n[eligibility] not at this session{where} — cannot narrate:")
        for x in e.absent_exclusions:
            who = f" (player: {x.player})" if x.player else " (no player bound)"
            print(f"  - {x.character}{who} — {x.reason}")

    if e.scene_exclusions:
        print("\n[eligibility] at the session, but not in these scenes:")
        by_scene: dict[str, list[str]] = {}
        for x in e.scene_exclusions:
            by_scene.setdefault(x.scene or "", []).append(x.character)
        for scene, chars in by_scene.items():
            eligible = ", ".join(sorted(e.candidates.get(scene, ()))) or "nobody"
            print(f"  - {scene}: {', '.join(sorted(chars))} "
                  f"(eligible here: {eligible})")

    if e.unrecognised_labels:
        print("\n[eligibility] speaker labels that match no roster character — "
              "check scene_extract's normalisation before trusting the sets above:")
        for scene, labels in e.unrecognised_labels.items():
            print(f"  - {scene}: {', '.join(sorted(labels))}")

    if e.uncoverable:
        print("\n[eligibility] no eligible narrator at all:")
        for scene in e.uncoverable:
            print(f"  - {scene}")

    pool = ", ".join(sorted(e.pool)) or "nobody"
    print(f"\n[eligibility] narrator pool: {pool}")


#: Written beside plan.md. Answers "which pool was this plan drawn from" after
#: the run is over, from disk, without re-deriving it (Constitution VIII).
ELIGIBILITY_RECORD = "plan.eligibility.json"


def write_eligibility_record(e: Eligibility, *, out_dir, vtt_path) -> "Path":
    """Persist the evidence behind the pool and the per-scene candidates.

    A plan is read months later by somebody asking why a character never
    narrates. Without this the answer is only reconstructable by finding the
    right tape and re-running the filters — and by then the tape may have been
    re-cut. The exclusions and their causes are part of the artifact.
    """
    from pathlib import Path as _Path

    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "vtt": str(vtt_path),
        "attendance": {
            name: {"present": bool(label), "matched_label": label}
            for name, label in sorted(e.attendance.items())
        },
        "pool": sorted(e.pool),
        "scenes": {
            name: {
                "eligible": sorted(cands),
                "line_counts": e.line_counts.get(name, {}),
                "uncoverable": name in e.uncoverable,
            }
            for name, cands in e.candidates.items()
        },
        "exclusions": {
            "absent_players": [
                {"character": x.character, "player": x.player, "reason": x.reason}
                for x in e.absent_exclusions
            ],
            "not_in_scene": [
                {"character": x.character, "scene": x.scene, "reason": x.reason}
                for x in e.scene_exclusions
            ],
        },
        "unrecognised_labels": {
            scene: sorted(labels) for scene, labels in e.unrecognised_labels.items()
        },
    }
    path = out_dir / ELIGIBILITY_RECORD
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path
