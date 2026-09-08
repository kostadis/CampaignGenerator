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
import re
from dataclasses import dataclass, field

from campaignlib.players_config import (
    GM_LABEL,
    PlayersConfig,
    absent_characters,
    attendance_is_establishable,
    attending_players,
    norm_name,
    player_name_for,
    undetermined_characters,
)
from campaignlib.vtt import speaker_labels
from session_doc.io import scene_speaker_labels


#: Separators inside a bracketed label. ``/`` joins two speakers on one turn
#: (``**[GM / Brewbarry]**``); ``,`` carries a qualifier
#: (``**[GM, as the banker]**``). Splitting on them claims only that the label
#: names more than one thing — which is visible in the text. Deciding who each
#: part *is* happens in :func:`_resolve_part`, against the roster.
_LABEL_SEPARATORS = re.compile(r"[/,]")


def label_parts(label: str) -> list[str]:
    """One speaker label -> its candidate name parts.

    A **bare** label yields itself, unmodified. Only a bracketed label is
    tokenised, which is what makes a bare-convention session structurally
    unaffected by #453 rather than merely tested for.

    Tokenising is not identifying. Splitting ``[GM / Brewbarry]`` on ``/``
    asserts that the label names two parties, which the punctuation says
    outright; it asserts nothing about who they are.
    """
    label = label.strip()
    if not (label.startswith("[") and label.endswith("]")):
        return [label] if label else []
    inner = label[1:-1]
    return [part for part in (p.strip() for p in _LABEL_SEPARATORS.split(inner)) if part]


def _resolve_part(part: str, canonical: dict[str, str]) -> str | None:
    """One part -> a roster character's own spelling, ``GM_LABEL``, or ``None``.

    Folded **equality**, never containment — and the corpus is what forces the
    distinction. ``**[scene tag — Vukradin demands a meeting]**`` is a beat
    marker that *contains* a roster name. Under containment it would place
    Vukradin in a scene on the strength of scene apparatus: a fabricated
    attribution, which is the most expensive failure this system can produce.
    Under folded equality it resolves to nobody and is correctly inert.

    ``norm_name`` says the same thing for the same reason: "Folding is not
    approximate matching."
    """
    folded = norm_name(part)
    if folded == norm_name(GM_LABEL):
        return GM_LABEL
    return canonical.get(folded)


@dataclass(frozen=True)
class LabelReading:
    """What one speaker label turned out to mean.

    ``characters`` is a *set*: a label naming one character twice contributes
    one turn of evidence, not two.
    """

    label: str
    characters: frozenset[str]
    names_gm: bool
    bracketed: bool

    @property
    def is_apparatus(self) -> bool:
        """Bracketed and resolving to nobody — a beat marker, near enough.

        Only the *reporting* bucket turns on this (see :func:`_stranger_buckets`).
        Presence never does: an unresolved label creates no presence whatever
        shape it has.
        """
        return self.bracketed and not self.characters and not self.names_gm


def read_label(label: str, canonical: dict[str, str]) -> LabelReading:
    """Classify one label against the roster.

    A part resolving to a character outranks one resolving to the game master:
    ``[GM / Brewbarry]`` is Brewbarry's presence, and the GM half contributes
    nothing rather than suppressing the label. Per the GM's ruling of
    2026-09-08, **every** roster character a label names is present — so
    ``[Brewbarry / Soma]`` places both. That is the permissive reading, taken
    knowingly: a turn only one of them spoke can make both eligible, and the
    turn counts beside the pool are the GM's evidence for overriding it.
    """
    stripped = label.strip()
    bracketed = stripped.startswith("[") and stripped.endswith("]")
    characters, names_gm = set(), False
    for part in label_parts(stripped):
        resolved = _resolve_part(part, canonical)
        if resolved == GM_LABEL:
            names_gm = True
        elif resolved is not None:
            characters.add(resolved)
    return LabelReading(
        label=stripped,
        characters=frozenset(characters),
        names_gm=names_gm,
        bracketed=bracketed,
    )


def scene_presence(moments: str, canonical: dict[str, str]):
    """``moments`` -> (turns per character, unresolved labels).

    Filter B, whole. One reading of the text feeds presence and counts alike,
    so a GM can never be shown a turn count for a character the filter excluded
    (FR-009) — the rule :func:`session_doc.io.scene_speaker_labels` is anchored
    for.

    Presence is a yes/no fact: one labelled turn is full eligibility. Soma has
    two lines in scene 03 against Vukradin's sixty-six and both are eligible.
    A threshold above zero would be a tuning knob with no defensible value.
    """
    counts: dict[str, int] = {}
    unresolved: list[LabelReading] = []
    for label in scene_speaker_labels(moments):
        reading = read_label(label, canonical)
        if reading.characters:
            for character in reading.characters:
                counts[character] = counts.get(character, 0) + 1
        elif not reading.names_gm:
            unresolved.append(reading)
    return counts, unresolved


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
        roster_counts, unresolved = scene_presence(
            scene.get("moments") or "", canonical)
        present = set(roster_counts)
        strangers = {reading.label for reading in unresolved}

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
            bracketed = label.startswith("[") and label.endswith("]")
            if bracketed:
                # Scene apparatus, near enough. A bracketed label that resolved
                # to nobody is far more likely a beat marker than a mangled
                # character name, and two markers in this corpus contain a
                # roster name outright — `[scene tag — Soma's Arcana check]`,
                # `[scene tag — Vukradin demands a meeting]`. Containment would
                # print both under a notice that says each one costs that
                # character a scene, in the one channel #385 built to be read.
                # Reading bracketed labels at all (#453) is what put 22 markers
                # in reach of this split, so the quiet bucket is where they go.
                #
                # The cost, recorded: a mis-normalised *bracketed* character
                # label would go quiet too. None exists in the corpus, and the
                # loud alternative is paid every run. Bare labels — where
                # `Vukradin (David)` actually happens — keep the heuristic.
                other += 1
            elif any(name in folded for name in folded_pool):
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
