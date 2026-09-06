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
    PlayersConfig,
    absent_characters,
    attendance_is_establishable,
    attending_players,
    norm_name,
    player_name_for,
    undetermined_characters,
)
from campaignlib.vtt import speaker_labels
from session_doc.io import scene_speaker_counts


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


@dataclass(frozen=True)
class SceneEligibility:
    """One scene's candidates, keyed by position rather than by name.

    Two extraction files may declare the same ``scene:`` frontmatter value, and
    a name-keyed dict silently collapsed them — so one scene advertised the
    other's candidates and the violation check validated the wrong pair.
    """

    index: int
    name: str
    candidates: set[str]
    counts: dict[str, int]
    strangers: set[str]

    @property
    def uncoverable(self) -> bool:
        return not self.candidates


@dataclass
class Eligibility:
    """The narrator pool, the per-scene candidates, and the evidence for both."""

    pool: set[str]
    scenes: list[SceneEligibility]
    absent_exclusions: list[Exclusion]
    scene_exclusions: list[Exclusion]
    attendance: dict[str, str] = field(default_factory=dict)
    undetermined: set[str] = field(default_factory=set)

    @property
    def uncoverable(self) -> list[str]:
        """Names of the scenes with no eligible narrator, in plan order."""
        return [s.name for s in self.scenes if s.uncoverable]

    @property
    def uncoverable_indexes(self) -> list[int]:
        return [s.index for s in self.scenes if s.uncoverable]

    @property
    def has_uncoverable(self) -> bool:
        return any(s.uncoverable for s in self.scenes)


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
    undetermined = undetermined_characters(players, roster)
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
    scene_records: list[SceneEligibility] = []
    scene_exclusions: list[Exclusion] = []

    for index, scene in enumerate(scenes):
        name = scene.get("name", "")
        counts = scene_speaker_counts(scene.get("moments") or "")

        present: set[str] = set()
        strangers: set[str] = set()
        roster_counts: dict[str, int] = {}
        for label, n in counts.items():
            known = canonical.get(norm_name(label))
            if known is None:
                strangers.add(label)
            else:
                present.add(known)
                roster_counts[known] = roster_counts.get(known, 0) + n

        scene_records.append(SceneEligibility(
            index=index, name=name, candidates=present & pool,
            counts=roster_counts, strangers=strangers,
        ))
        for character in sorted(pool - present):
            scene_exclusions.append(
                Exclusion(
                    character=character,
                    scene=name,
                    reason="no speaker label in this scene",
                )
            )

    return Eligibility(
        pool=pool,
        scenes=scene_records,
        absent_exclusions=absent_exclusions,
        scene_exclusions=scene_exclusions,
        attendance=attendance,
        undetermined=undetermined,
    )


def _stranger_buckets(e: Eligibility) -> "tuple[dict[str, set[str]], int]":
    """Split unresolved labels into "probably a mis-normalised PC" and the rest.

    A label containing a roster character's name — ``Vukradin (David)`` — is
    worth the GM's attention because it silently costs that character a scene.
    A label that is simply an NPC is not, and there are dozens of those per
    session; listing them buried the notice that the covering-player case
    depends on.

    Containment, not similarity: this decides what to *print*, never who anybody
    is, so it asserts no identity.
    """
    suspects: dict[str, set[str]] = {}
    other = 0
    folded_pool = {norm_name(c): c for c in e.pool}
    for scene in e.scenes:
        for label in scene.strangers:
            folded = norm_name(label)
            if any(name in folded for name in folded_pool):
                suspects.setdefault(scene.name, set()).add(label)
            else:
                other += 1
    return suspects, other


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

    if e.undetermined:
        print("\n[eligibility] attendance could not be established (not excluded — "
              "nobody active is bound to them, or their player declares no "
              "display_names). `players check` reports the binding:")
        for character in sorted(e.undetermined):
            print(f"  - {character}")

    if e.scene_exclusions:
        print("\n[eligibility] at the session, but not in these scenes:")
        by_index: dict[str, list[str]] = {}
        for x in e.scene_exclusions:
            by_index.setdefault(x.scene or "", []).append(x.character)
        eligible_by_name = {s.name: s.candidates for s in e.scenes}
        for scene, chars in by_index.items():
            eligible = ", ".join(sorted(eligible_by_name.get(scene, ()))) or "nobody"
            print(f"  - {scene}: {', '.join(sorted(chars))} "
                  f"(eligible here: {eligible})")

    suspects, other = _stranger_buckets(e)
    if suspects:
        print("\n[eligibility] speaker labels that look like a roster character "
              "but did not resolve — scene_extract's normalisation is the "
              "likely cause, and each one costs that character a scene:")
        for scene, labels in suspects.items():
            print(f"  - {scene}: {', '.join(sorted(labels))}")
    if other:
        # NPC labels are expected and there are dozens per session. Listing them
        # buried the line above, which is the one the GM has to read.
        print(f"\n[eligibility] {other} further non-roster label(s) "
              f"(NPCs and unnamed voices) — expected, not listed.")

    if e.has_uncoverable:
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
        "undetermined": sorted(e.undetermined),
        # A list, not a name-keyed object: two scenes may share a frontmatter
        # `scene:` value, and keying by it silently merged them.
        "scenes": [
            {
                "index": s.index,
                "name": s.name,
                "eligible": sorted(s.candidates),
                "line_counts": s.counts,
                "uncoverable": s.uncoverable,
                "unresolved_labels": sorted(s.strangers),
            }
            for s in e.scenes
        ],
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
    }
    path = out_dir / ELIGIBILITY_RECORD
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path
