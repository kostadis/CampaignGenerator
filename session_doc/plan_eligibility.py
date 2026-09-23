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


#: Separators inside a bracketed label, and they mean different things.
#: ``/`` joins two speakers on one turn (``**[GM / Brewbarry]**``), so it opens
#: a new *slot*. ``,`` most often carries a qualifier
#: (``**[GM, as the banker]**``), so it opens a new *piece* of the same slot.
#: Splitting claims only that the label names more than one thing — which is
#: visible in the text. Deciding who each piece *is* happens in
#: :func:`_resolve_part`, against the roster.
_SLOT_SEPARATOR = "/"
_PIECE_SEPARATOR = ","

#: ``norm_name(GM_LABEL)`` is a constant. Folding it per part meant recomputing
#: it 134+ times per scene on the corpus's busiest file, on every ``sd_plan``.
_GM_FOLDED = norm_name(GM_LABEL)


def label_slots(label: str) -> list[list[str]]:
    """One speaker label -> its slots, each slot -> its pieces, in order.

    A **bare** label yields one slot of one piece: itself, unmodified. Only a
    bracketed label is tokenised, which is what makes a bare-convention session
    structurally unaffected by #453 rather than merely tested for. That is the
    *only* decision this module takes on a label's shape, and it decides how to
    read the text, never who anybody is.

    The two levels exist because the two separators do different work. Every
    slot is a speaker and must resolve or be reported. A piece after the first
    within a slot is a qualifier *if it resolves to nobody* — ``as the banker``
    in ``[GM, as the banker]`` — and a second speaker if it resolves to
    somebody, so ``[Vukradin, Brewbarry]`` still credits both. Resolution
    decides which, not punctuation.
    """
    label = label.strip()
    if not (label.startswith("[") and label.endswith("]")):
        return [[label]] if label else []
    slots = []
    for slot in label[1:-1].split(_SLOT_SEPARATOR):
        pieces = [p.strip() for p in slot.split(_PIECE_SEPARATOR)]
        pieces = [p for p in pieces if p]
        if pieces:
            slots.append(pieces)
    return slots


def label_parts(label: str) -> list[str]:
    """The flattened view of :func:`label_slots` — every candidate name piece."""
    return [piece for slot in label_slots(label) for piece in slot]


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
    if folded == _GM_FOLDED:
        return GM_LABEL
    return canonical.get(folded)


@dataclass(frozen=True)
class LabelReading:
    """What one speaker label turned out to mean.

    ``characters`` is a *set*: a label naming one character twice contributes
    one turn of evidence, not two.

    ``unresolved`` is the pieces that named nobody the roster knows. It is
    populated even when the label *also* resolved somebody — that partial case
    is the one that used to vanish. ``[GM / Brewbarry / Valphine]`` credited
    Brewbarry and dropped ``Valphine`` with no trace: not counted, not
    reported, not in ``plan.eligibility.json``. Against a roster spelling her
    ``Valphine Sotorra`` that is a real exclusion the GM was never shown.
    """

    label: str
    characters: frozenset[str]
    names_gm: bool
    bracketed: bool
    unresolved: frozenset[str] = frozenset()

    @property
    def is_apparatus(self) -> bool:
        """Bracketed and resolving to nobody — a beat marker, near enough.

        Only the *reporting* bucket turns on this (see :func:`_stranger_buckets`),
        which is the one caller. Presence never does: an unresolved piece creates
        no presence whatever shape its label has.
        """
        return self.bracketed and not self.characters and not self.names_gm


def read_label(label: str, canonical: dict[str, str]) -> LabelReading:
    """Classify one label against the roster.

    A part resolving to a character outranks one resolving to the game master:
    ``[GM / Brewbarry]`` is Brewbarry's presence, and the GM half contributes
    nothing rather than suppressing the label. Per the GM's ruling of
    2026-09-08, **every** roster character a label names is present — so
    ``[Brewbarry / Soma]`` places both. That is the permissive reading, taken
    knowingly and it has no automatic safety net: a turn only one of them spoke
    makes both eligible, and the printed turn counts cannot distinguish a solo
    turn from a joint one. The GM's evidence for overriding it is the scene
    extraction itself.

    A slot that resolves to nobody lands in ``unresolved`` and is reported. A
    *later piece* of a slot that resolves to nobody is a qualifier and is not —
    ``as the banker`` describes the GM's turn, it does not fail to name a
    speaker.
    """
    stripped = label.strip()
    bracketed = stripped.startswith("[") and stripped.endswith("]")
    characters, names_gm, unresolved = set(), False, set()
    for slot in label_slots(stripped):
        for position, piece in enumerate(slot):
            resolved = _resolve_part(piece, canonical)
            if resolved == GM_LABEL:
                names_gm = True
            elif resolved is not None:
                characters.add(resolved)
            elif position == 0:
                unresolved.add(piece)
    return LabelReading(
        label=stripped,
        characters=frozenset(characters),
        names_gm=names_gm,
        bracketed=bracketed,
        unresolved=frozenset(unresolved),
    )


def scene_presence(
    moments: str, canonical: dict[str, str]
) -> tuple[dict[str, int], list[LabelReading]]:
    """``moments`` -> (turns per character, labels with an unresolved slot).

    Filter B, whole. One reading of the text feeds presence and counts alike,
    so a GM can never be shown a turn count for a character the filter excluded
    (FR-009) — the rule :func:`session_doc.io.scene_speaker_labels` is anchored
    for.

    Presence is a yes/no fact: one labelled turn is full eligibility. Soma has
    two lines in scene 03 against Vukradin's sixty-six and both are eligible.
    A threshold above zero would be a tuning knob with no defensible value.

    Counting and reporting are independent: a label may do both. Reporting only
    labels that resolved to *nobody* hid every partially-resolved one, which is
    exactly where a roster character goes missing beside a name that worked.
    """
    counts: dict[str, int] = {}
    unresolved: list[LabelReading] = []
    for label in scene_speaker_labels(moments):
        reading = read_label(label, canonical)
        for character in reading.characters:
            counts[character] = counts.get(character, 0) + 1
        if reading.unresolved:
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
    #: Position, because two extractions may declare the same ``scene:`` value.
    #: The report grouped by name and merged them — the same collapse
    #: :class:`SceneEligibility` is index-keyed to avoid.
    scene_index: int | None = None


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
    #: The readings, not their label strings. ``_stranger_buckets`` needs the
    #: classification :func:`read_label` already made; handing it bare strings
    #: made it re-derive the bracket test from the raw text, a second copy of
    #: the predicate that could drift from :attr:`LabelReading.is_apparatus`
    #: with nothing to fail.
    strangers: tuple[LabelReading, ...]

    @property
    def stranger_labels(self) -> set[str]:
        return {reading.label for reading in self.strangers}

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

        scene_records.append(SceneEligibility(
            index=index, name=name, candidates=present & pool,
            counts=roster_counts, strangers=tuple(unresolved),
        ))
        for character in sorted(pool - present):
            scene_exclusions.append(
                Exclusion(
                    character=character,
                    scene=name,
                    scene_index=index,
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


def _stranger_buckets(
    e: Eligibility,
) -> "tuple[dict[int, tuple[str, set[str]]], int]":
    """Split unresolved labels into "probably a mis-normalised PC" and the rest.

    A label containing a roster character's name — ``Vukradin (David)`` — is
    worth the GM's attention because it silently costs that character a scene.
    A label that is simply an NPC is not, and there are dozens of those per
    session; listing them buried the notice that the covering-player case
    depends on.

    Containment, not similarity: this decides what to *print*, never who anybody
    is, so it asserts no identity.

    Bracketed labels that resolved to nobody go quiet. A beat marker is the
    common case and two in this corpus contain a roster name outright —
    ``[scene tag — Soma's Arcana check]``, ``[scene tag — Vukradin demands a
    meeting]`` — so containment would print both under a notice saying each one
    costs that character a scene, in the one channel #385 built to be read.

    A **shortened** roster name is the exception, and it is why the bracketed
    rule is not the last word. ``**[Valphine]**`` occurs 8 times across two
    corpus files against a roster spelling her ``Valphine Sotorra``; it is
    bracketed, resolves to nobody, and used to file as apparatus among 17 beat
    markers while costing her every scene she spoke in (#460). It is now
    promoted by :func:`truncates_a_roster_name`, which tests containment in the
    one safe direction — a piece inside a name, never a name inside a piece,
    since a beat marker is longer than any name and can never match that way.

    Promoted, not resolved. ``party.yaml`` declares the full name and
    ``speaker_map_from_configs`` rewrites the tape to it in code before the
    model runs, so a short label is a defect in the extraction prompt (#459),
    not a spelling the roster should be taught to accept. Teaching it would be
    similarity asserting identity — what the equality rule exists to refuse.
    """
    suspects: dict[int, tuple[str, set[str]]] = {}
    other = 0
    folded_pool = {norm_name(c): c for c in e.pool}
    def truncates_a_roster_name(reading: LabelReading) -> bool:
        """Is an unresolved piece a shortening of a roster character's name?

        Containment in the **safe direction only**: the piece inside the name,
        never the name inside the piece. ``valphine`` sits inside
        ``valphine sotorra``, while ``scene tag — vukradin demands a meeting``
        sits inside nothing — a beat marker is longer than any name, so it can
        never match this way. The reverse test is the dangerous one and stays
        confined to bare labels below.

        Tested on the tokenised pieces, not the raw label, because the piece
        has already had its brackets removed: ``[valphine]`` is not a substring
        of ``valphine sotorra`` and ``valphine`` is.
        """
        return any(piece in name
                   for piece in (norm_name(p) for p in reading.unresolved)
                   for name in folded_pool)

    for scene in e.scenes:
        for reading in scene.strangers:
            folded = norm_name(reading.label)
            if truncates_a_roster_name(reading):
                # `**[Valphine]**` against a roster declaring `Valphine
                # Sotorra` — 8 occurrences across two corpus sessions, each one
                # a scene she spoke in and was excluded from (#460). It is
                # bracketed and resolves to nobody, so it classified as
                # apparatus and went quiet, filed among the beat markers.
                #
                # Printed, never resolved. `party.yaml` declares the full name
                # and the speaker map rewrites the tape to it in code before
                # the model runs, so a short label is a defect upstream (#459),
                # not a spelling the roster should be taught to accept.
                # Resolving it here would be similarity asserting identity —
                # the thing the equality rule exists to refuse.
                suspects.setdefault(scene.index, (scene.name, set()))[1].add(
                    reading.label)
            elif reading.characters or reading.names_gm:
                # This label resolved at least one speaker and still has a slot
                # that named nobody — so it is a speaker label by demonstration,
                # not by resemblance, and the unnamed slot is a character the
                # roster does not know. Stronger evidence than containment, and
                # it is how `[GM / Brewbarry / Valphine]` reaches the GM.
                suspects.setdefault(scene.index, (scene.name, set()))[1].add(
                    reading.label)
            elif reading.is_apparatus:
                other += 1
            elif any(name in folded for name in folded_pool):
                suspects.setdefault(scene.index, (scene.name, set()))[1].add(
                    reading.label)
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
    character their eligibility with nothing to show for it. That holds per
    *slot*, not per label — ``[GM / Brewbarry / Valphine]`` costs Valphine a
    scene while looking, from its resolved half, like a label that worked.
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
        # Grouped by scene POSITION, not by name: two extractions may declare
        # the same `scene:` value, and grouping by name merged their exclusions
        # and showed one scene's eligible set against the other's.
        by_scene: dict[int, list[str]] = {}
        for x in e.scene_exclusions:
            by_scene.setdefault(x.scene_index if x.scene_index is not None else -1,
                                []).append(x.character)
        eligible_by_index = {s.index: (s.name, s.candidates) for s in e.scenes}
        for index, chars in by_scene.items():
            name, candidates = eligible_by_index.get(index, ("", set()))
            eligible = ", ".join(sorted(candidates)) or "nobody"
            print(f"  - {name}: {', '.join(sorted(chars))} "
                  f"(eligible here: {eligible})")

    suspects, other = _stranger_buckets(e)
    if suspects:
        print("\n[eligibility] speaker labels that look like a roster character "
              "but did not resolve — scene_extract's normalisation is the "
              "likely cause, and each one costs that character a scene:")
        for index in sorted(suspects):
            name, labels = suspects[index]
            print(f"  - {name}: {', '.join(sorted(labels))}")
    if other:
        # There are dozens of these per session and listing them buried the line
        # above, which is the one the GM has to read. It used to call them all
        # "expected", which stopped being true when #453 routed scene apparatus
        # here and `[Valphine]` came with it — a wrong exclusion filed as an
        # NPC. #460 promotes that case, so the bucket is once again mostly what
        # it says. "Mostly" is why the pointer stays: a roster name mangled
        # rather than shortened still lands here, and the record lists it.
        print(f"\n[eligibility] {other} further label(s) that resolved to nobody "
              f"— scene apparatus, NPCs and unnamed voices. Not listed here; "
              f"every one is in {ELIGIBILITY_RECORD} under `unresolved_labels`, "
              f"which is the place to look if a character is missing above.")

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
                "unresolved_labels": sorted(s.stranger_labels),
            }
            for s in e.scenes
        ],
        "exclusions": {
            "absent_players": [
                {"character": x.character, "player": x.player, "reason": x.reason}
                for x in e.absent_exclusions
            ],
            "not_in_scene": [
                {"character": x.character, "scene": x.scene,
                 "scene_index": x.scene_index, "reason": x.reason}
                for x in e.scene_exclusions
            ],
        },
    }
    path = out_dir / ELIGIBILITY_RECORD
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path
