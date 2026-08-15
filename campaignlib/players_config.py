"""Player roster configuration — models and YAML I/O for ``<config>/players.yaml``.

Feature 009. This module is the **one** implementation of the player entity's
shape, and ``players.yaml`` is the one place a player's identity is authored.

Before it there was no player entity at all.
``docs/design/PlayerIdentity.md`` surveyed what stood in for one: five join
keys across fourteen stores, none of which named the others, and a clean split
between how each join failed — **everything that failed loudly was a path or an
exact-match refusal; everything that failed silently was a name approximately
matched.** This module is the source those stores become projections of, and
every join it defines is exact.

It lives in ``campaignlib`` rather than ``server`` so the dependency arrow
points one way: ``server/`` and ``pipelines/`` both import ``campaignlib``, and
neither imports the other (``tests/test_layering.py``). The CLIs read this
document, so ``server/`` was never an option for it.

**The four things called "identity".** They are routinely conflated, and every
conflation is a bug that has already happened:

==================  ====================================  ==================
Thing               Where it lives now                    Stability
==================  ====================================  ==================
the person          :attr:`Player.name`                   stable
the recording's     :attr:`Player.display_names` (a list) **per-session**
label
the character       ``party.yaml``'s ``characters[].name``  stable until a rename
the sheet           ``party.yaml``'s ``characters[].sheet`` stable
==================  ====================================  ==================

``name`` and ``display_names`` are deliberately two fields doing two jobs.
``name`` renders into prompts; ``display_names`` are matched against transcript
speaker prefixes. The retired ``party.yaml`` ``player:`` field was documented as
one and rendered as the other, and the one that failed did so silently.

**Strict, and refusing.** Two uniqueness rules are enforced at load and at save
rather than reported, because neither can be a legitimate configuration:

* a duplicate ``id`` — every reference to that player becomes ambiguous;
* a display name held by two players — :func:`speaker_map` would have two valid
  answers and no way to choose, which is the silent misattribution this whole
  feature exists to remove.

Everything else — a binding to a character that does not exist yet, a player
with no display names — is **reported, never refused**, so the GM can name
something they are about to create. See ``PlayersConfigService``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from campaignlib.util import atomic_write_text

PLAYERS_CONFIG_FILENAME = "players.yaml"

#: What a game master's speech is labelled as after normalisation. The literal
#: ``normalize_vtt_speakers`` has always used, named once now that the value
#: comes from the entity rather than from a ``--gm-player`` string.
GM_LABEL = "GM"


class Player(BaseModel):
    """One human at the table.

    ``id`` is a short slug the GM authors (``ben``, ``wade``) — required,
    unique within the document, and deliberately **not** derived from
    :attr:`name`, so a name can be corrected without breaking any reference to
    that player. The same person uses the same slug in every campaign they
    appear in; nothing enforces or reads that across campaigns, but a later
    cross-campaign view then needs no new store, only a read over the existing
    per-campaign documents.

    ``display_names`` is a **list** because the label drifts between sessions
    while this document is per campaign. Phandalin's Wade went from ``Wade`` to
    ``Wade Brown`` between recordings; the back catalogue of transcripts still
    carries the old one, so both have to keep working. Zero is legitimate —
    Hillsfar records a placeholder for all four of its characters.

    ``plays`` holds character names from this campaign's ``party.yaml``. The
    relationship is many-to-many and lives on this side only: one person may
    play two characters, one character may be co-piloted by two people, and
    nothing on the character side points back. One direction, one authority.

    ``gm`` and ``plays`` are independent — toee's ``Calmer`` is a GM-played PC.
    For speaker labelling the game-master label wins; see :func:`speaker_map`.

    ``active`` false marks somebody who has left. They are **never deleted**,
    because every archived transcript still carries their label and deleting
    them would break speaker resolution for the whole corpus. An inactive
    player keeps their display names and bindings, drops out of the prompt
    roster, and does not make their character look unplayed.

    ``dndbeyond_id`` is recorded and **read by nothing** here. Eight exports on
    disk are named ``<account>_<id>.pdf`` and no code has ever looked at the
    number; using it as the sheet-attribution key is issue #312.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    display_names: list[str] = Field(default_factory=list)
    plays: list[str] = Field(default_factory=list)
    gm: bool = False
    active: bool = True
    dndbeyond_id: str | None = None


class PlayersConfig(BaseModel):
    """Root model — the ``<config>/players.yaml`` shape.

    No ``selection`` field, unlike every sibling service's config. This service
    spends no tokens, so it has no model or backend override to carry.
    """

    model_config = ConfigDict(extra="forbid")

    players: list[Player] = Field(default_factory=list)


def norm_name(value: str) -> str:
    """Fold a **character** name for comparison — casefold + whitespace collapse.

    THE rule, exported so `speaker_map`, `speaker_map_from_configs`,
    `player_name_for`, `PlayersConfigService._with_problems` and
    `players check` all fold identically. They did not: three used exact
    equality and one lowercased, so a `plays: [gyrgum]` against a roster's
    `Gyrgum` made the check report "Clean" while the render refused with
    "no player bound". A check that disagrees with the run is worse than no
    check.

    Folding is not approximate matching. `Gyrgum` and `gyrgum` are one name
    typed two ways; `Gyrgum` and `Grygum` are two names, and nothing here will
    ever join them.
    """
    return " ".join(value.split()).casefold()


def _norm_display(value: str) -> str:
    """Collapse a display name for *collision detection only*.

    Matching against a transcript is exact (``normalize_vtt_speakers`` compares
    a literal prefix), but two rows differing only by case or padding are one
    label to a human, and refusing the pair is the safe direction: the cost of
    a false refusal is the GM renaming a row, and the cost of a false accept is
    a player's lines silently landing on somebody else's character.
    """
    return " ".join(value.split()).casefold()


def _check_uniqueness(players: list[Player], where: str) -> None:
    """Enforce the two rules that cannot be reported instead of refused."""
    seen_ids: dict[str, str] = {}
    for p in players:
        if p.id in seen_ids:
            raise ValueError(
                f"{where}: duplicate player id {p.id!r} — held by "
                f"{seen_ids[p.id]!r} and {p.name!r}. An id identifies one "
                f"person; give one of them a different slug."
            )
        seen_ids[p.id] = p.name

    seen_names: dict[str, tuple[str, str]] = {}
    for p in players:
        for raw in p.display_names:
            key = _norm_display(raw)
            if key in seen_names:
                other_id, other_raw = seen_names[key]
                if other_id == p.id:
                    # Same player listing it twice is noise, not ambiguity.
                    continue
                raise ValueError(
                    f"{where}: display name {raw!r} is held by two players — "
                    f"{other_id!r} (as {other_raw!r}) and {p.id!r}. A "
                    f"transcript line starting with it would have two valid "
                    f"answers; record it under exactly one player."
                )
            seen_names[key] = (p.id, raw)


def _validate(players: list[Player], where: str) -> None:
    for i, p in enumerate(players):
        if not p.id.strip():
            raise ValueError(f"{where}: player #{i + 1} has an empty 'id'")
        if not p.name.strip():
            raise ValueError(f"{where}: player {p.id!r} has an empty 'name'")
        for raw in p.display_names:
            if not raw.strip():
                raise ValueError(
                    f"{where}: player {p.id!r} has an empty display name. An "
                    f"empty label would match the start of every line."
                )
    _check_uniqueness(players, where)


def load_players_config(path: Path) -> PlayersConfig:
    """Load ``players.yaml`` and validate it.

    A missing file, or one that parses to an empty or null document, returns an
    empty :class:`PlayersConfig` rather than raising. A campaign that has not
    recorded its players yet is a legitimate state, and the "an emptied file
    reads back as 400" bug ``docs/config/planning-isolation.md`` had to fix
    twice is not worth re-introducing. Callers that require a non-empty roster
    check for themselves and say which one they needed.

    Raises ``ValueError`` on malformed YAML, an unknown key, an empty ``id`` or
    ``name``, a duplicate ``id``, or a display name held by two players.
    """
    if not path.exists():
        return PlayersConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not raw:
        return PlayersConfig()
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a mapping")

    unknown = sorted(set(raw) - {"players"})
    if unknown:
        raise ValueError(
            f"{path}: unknown top-level key(s) {', '.join(unknown)} — the only "
            f"key this document has is 'players'."
        )

    entries = raw.get("players") or []
    if not isinstance(entries, list):
        raise ValueError(f"{path}: 'players' must be a list")

    players: list[Player] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"each player entry in {path} must be a mapping")
        if not entry.get("id"):
            raise ValueError(
                f"player entry #{i + 1} in {path} is missing 'id': {entry}"
            )
        try:
            players.append(Player.model_validate(entry))
        except Exception as exc:  # pydantic ValidationError is a ValueError
            raise ValueError(
                f"{path}: player {entry.get('id')!r} is invalid: {exc}"
            ) from exc

    _validate(players, str(path))
    # See load_party_config: loader and saver both hand-build, so a new field
    # must be named in BOTH or it round-trips to nothing. `party.yaml`'s
    # `selection` went through that door once — the write reported success and
    # persisted nothing.
    return PlayersConfig(players=players)


def save_players_config(path: Path, cfg: PlayersConfig) -> None:
    """Write ``cfg`` to ``path`` atomically, preserving what the GM authored.

    Atomic (:func:`campaignlib.util.atomic_write_text`) so a crash mid-write
    leaves the previous roster intact rather than a truncated file the next
    load would reject.

    Defaults are omitted rather than emitted. Stamping ``gm: false`` and
    ``active: true`` onto every row would be a rewrite of a hand-authored file,
    which is the thing a load/save round-trip must never do.

    The uniqueness rules are re-checked here as well as at load, so a service
    holding an in-memory config cannot write a document its own loader would
    reject.
    """
    _validate(cfg.players, str(path))
    entries: list[dict[str, Any]] = []
    for p in cfg.players:
        entry: dict[str, Any] = {"id": p.id, "name": p.name}
        if p.display_names:
            entry["display_names"] = list(p.display_names)
        if p.plays:
            entry["plays"] = list(p.plays)
        if p.gm:
            entry["gm"] = True
        if not p.active:
            entry["active"] = False
        if p.dndbeyond_id:
            entry["dndbeyond_id"] = p.dndbeyond_id
        entries.append(entry)
    atomic_write_text(
        path,
        yaml.safe_dump(
            {"players": entries},
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        ),
    )


def speaker_map(players: PlayersConfig, party: "Any") -> dict[str, str]:
    """Display name -> the label a transcript line becomes.

    ``party`` is a :class:`campaignlib.party_config.PartyConfig` or its resolved
    form — anything with a ``characters`` list of objects carrying ``name``.
    Typed loosely to keep the import one-way; the two modules are siblings and
    only this direction is needed.

    Built in two passes, and the order is the whole point:

    1. every player's display names map to the first of their ``plays`` that
       the roster actually has;
    2. **then** every game master's display names map to :data:`GM_LABEL`,
       overwriting whatever pass 1 left.

    Pass 2 is last so a person who both runs the game and plays a character
    gets the game-master label on every line and the character label on none
    (spec FR-021a). A transcript label records *who spoke*, not in what
    capacity; labelling that person's lines with their character's name would
    attribute narration and NPC speech to a player character, and a false
    attribution is the most expensive failure this system can produce.
    ``normalize_vtt_speakers`` used to arrange the same precedence itself with
    ``full_map[gm_player] = "GM"`` after building the player map — the ordering
    is preserved behaviour, stated once here instead of assembled at three call
    sites.

    A binding to a character the roster does not have contributes **nothing**
    rather than inventing a label: nothing here asserts an identity from a name
    that merely looks right (FR-025). ``players check`` reports it.

    Inactive players are included. Their labels still appear in the archived
    transcripts this map is applied to, which is why they are marked rather
    than deleted.
    """
    by_norm = {norm_name(c.name): c.name for c in getattr(party, "characters", [])}
    mapped: dict[str, str] = {}
    for p in players.players:
        character = next(
            (by_norm[norm_name(c)] for c in p.plays if norm_name(c) in by_norm), None
        )
        if character is None:
            continue
        for raw in p.display_names:
            mapped[raw] = character
    for p in players.players:
        if not p.gm:
            continue
        for raw in p.display_names:
            mapped[raw] = GM_LABEL
    return mapped


def load_players_config_arg(path_str: str | None) -> PlayersConfig | None:
    """CLI convenience for an optional ``--players-config PATH`` flag.

    Mirrors :func:`campaignlib.party_config.load_party_config_arg`: a missing
    path or a malformed document degrades to ``None`` with a message on stderr
    rather than raising, so the caller can compose one refusal out of "what was
    missing" and "what to do about it" instead of dying on a bare traceback.
    """
    if not path_str:
        return None
    path = Path(path_str).expanduser()
    if not path.exists():
        print(f"Error: --players-config not found: {path}", file=sys.stderr)
        return None
    try:
        return load_players_config(path)
    except ValueError as exc:
        print(f"Warning: --players-config unreadable ({exc})", file=sys.stderr)
        return None


def speaker_map_from_configs(
    players: PlayersConfig | None, party: "Any"
) -> dict[str, str] | None:
    """The strict, CLI-facing wrapper around :func:`speaker_map`.

    Returns the map, or ``None`` when the entity cannot answer — which is a
    **refusal**, not an empty result. ``require_from_config`` turns it into an
    exit(1), so a run either knows who is speaking or does not start.

    ``None`` is returned when a character in the roster has **no player bound
    to it at all**. That is an incomplete configuration: the run would proceed
    with a partial map and that character's lines would keep a raw transcript
    label, which is the silent half of the failure this feature removes
    (FR-024). Every unbound character is named on stderr, not just the first.

    An **empty map is not a failure.** A campaign whose players are all
    recorded but carry no display names — Hillsfar records a placeholder for
    all four of its characters — legitimately contributes nothing to rewrite,
    exactly as an empty ``party.md`` Player slot always did. The distinction is
    the whole point: "nobody is bound" is broken, "bound but unlabelled" is a
    real state a GM can be in.
    """
    if players is None:
        # Distinct from "recorded, but nobody is bound", and the caller cannot
        # tell them apart from a bare None — `require_from_config`'s message
        # names --party-config, which is the wrong file to go and look at.
        print(
            "speaker_map_from_configs: no player entity was given.\n"
            "  -> pass --players-config <campaign>/config/players.yaml. If the "
            "campaign has not been adopted yet, run:\n"
            "     python -m server.migrate_players_config --campaign-dir DIR",
            file=sys.stderr,
        )
        return None
    characters = [c.name for c in getattr(party, "characters", [])]
    bound = {norm_name(c) for p in players.players for c in p.plays}
    unbound = [c for c in characters if norm_name(c) not in bound]
    if unbound:
        print(
            "speaker_map_from_configs: no usable speaker map — these "
            "characters have no player bound to them:\n"
            + "\n".join(f"  - {c}" for c in unbound)
            + "\n  -> record who plays them in players.yaml (Setup -> Players), "
            "or run `python -m server.migrate_players_config --campaign-dir DIR`.",
            file=sys.stderr,
        )
        return None
    return speaker_map(players, party)


def player_name_for(players: PlayersConfig, character: str) -> str | None:
    """The person's name to render for ``character``, or ``None``.

    Only **active** players are considered: the prompt roster describes the
    table as it is now, while an inactive player is kept so the transcript
    archive still resolves (FR-011a, FR-019). A character played by two people
    renders the first of them, in authored order.
    """
    wanted = norm_name(character)
    for p in players.players:
        if p.active and any(norm_name(c) == wanted for c in p.plays):
            return p.name
    return None
