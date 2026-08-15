"""Service owning the player roster's configuration.

Feature 009. Storage is ``<config>/players.yaml``, which this service owns
exclusively — it is the one place a player's identity is authored, and every
other copy of that identity is rendered from it or reported as drift.

Mirrors :class:`server.party_config_service.PartyConfigService`: same
composition of ``PlatformConfigService`` for ``config_path_base``, same
404/409/400 contract, same "an emptied file reads back as an empty collection,
not a 400" behaviour, and the same whole-document ``replace_all`` write.

**The lenient/strict split** is the one thing worth reading twice, because this
service draws the line in a different place from its siblings:

* **Refused** — shape, and the two uniqueness rules. A duplicate ``id`` makes
  every reference to that player ambiguous. A display name held by two players
  leaves :func:`campaignlib.players_config.speaker_map` with two valid answers
  and no way to choose, which is exactly the silent misattribution feature 009
  exists to remove. Neither is a configuration a GM could mean.
* **Reported** — references. A binding to a character that does not exist yet,
  or a player with no display names, rides back on the response as a
  ``problems`` entry and never blocks the write. The GM must be able to name a
  character they are about to add (D4 in ``docs/config/grounding-isolation.md``,
  the same rule ``PartyConfigService._with_missing`` follows).

There are deliberately **no ``/selection`` accessors**. Every sibling service
carries a model/backend override; this one spends no tokens, so it has nothing
to override.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from campaignlib.party_config import PARTY_CONFIG_FILENAME, load_party_config
from campaignlib.players_config import (
    PLAYERS_CONFIG_FILENAME,
    Player,
    PlayersConfig,
    load_players_config,
    norm_name,
    save_players_config,
)


class PlayersConfigService:
    """Owns ``<config>/players.yaml``."""

    def __init__(self, platform) -> None:
        self.platform = platform
        self.players_path = platform.config_path_base / PLAYERS_CONFIG_FILENAME
        self.party_path = platform.config_path_base / PARTY_CONFIG_FILENAME

    # ── Load / save ───────────────────────────────────────────────────

    def _load(self) -> PlayersConfig:
        try:
            return load_players_config(self.players_path)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Failed to load players config: {exc}"
            ) from exc

    def _save(self, config: PlayersConfig) -> None:
        try:
            save_players_config(self.players_path, config)
        except ValueError as exc:
            # The two uniqueness rules land here. They are conflicts between
            # what is on disk and what is being written, so 409 rather than
            # 400 — the same code the duplicate-name guards use above.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — an I/O failure is still a 400
            raise HTTPException(
                status_code=400, detail=f"Failed to save players config: {exc}"
            ) from exc

    # ── Cross-reading the roster ──────────────────────────────────────

    def _character_names(self) -> set[str] | None:
        """Character names from ``party.yaml``, or ``None`` when there is no
        usable roster to check against.

        ``None`` and ``set()`` mean different things and the caller relies on
        it: an absent or unloadable roster means "cannot check", while an empty
        roster means "checked, and it has nobody". obelisk's ``party.yaml``
        does not load at all — it is a PC-name exclusion list, not a roster —
        and the Players page must keep working there rather than 500.
        """
        if not self.party_path.exists():
            return None
        try:
            return {
                norm_name(c.name)
                for c in load_party_config(self.party_path).characters
            }
        except ValueError:
            return None

    def _with_problems(
        self, player: Player, known: set[str] | None
    ) -> dict[str, Any]:
        """Serialize one player plus its reference report.

        Never refuses. See the module docstring's lenient/strict split.
        """
        problems: list[dict[str, str]] = []
        if known is not None:
            for character in player.plays:
                if norm_name(character) not in known:
                    problems.append({
                        "kind": "unknown_character",
                        "value": character,
                        "detail": (
                            f"no character named {character!r} in "
                            f"{PARTY_CONFIG_FILENAME}"
                        ),
                    })
        elif player.plays:
            # No usable roster: say the binding is unchecked rather than
            # silently passing it, which is how a stale binding survives.
            for character in player.plays:
                problems.append({
                    "kind": "unknown_character",
                    "value": character,
                    "detail": (
                        f"{PARTY_CONFIG_FILENAME} is absent or unreadable, so "
                        f"{character!r} could not be checked"
                    ),
                })
        if not player.display_names:
            problems.append({
                "kind": "no_display_name",
                "value": player.id,
                "detail": (
                    "no display name recorded — this player resolves in no "
                    "transcript"
                ),
            })
        return {**player.model_dump(mode="json"), "problems": problems}

    # ── Read ──────────────────────────────────────────────────────────

    def get_players(self) -> list[dict[str, Any]]:
        known = self._character_names()
        return [self._with_problems(p, known) for p in self._load().players]

    def get_player(self, player_id: str) -> dict[str, Any]:
        known = self._character_names()
        for p in self._load().players:
            if p.id == player_id:
                return self._with_problems(p, known)
        raise HTTPException(
            status_code=404, detail=f"Player '{player_id}' not found"
        )

    # ── Write ─────────────────────────────────────────────────────────

    def create_player(self, player: Player) -> dict[str, Any]:
        config = self._load()
        if any(p.id == player.id for p in config.players):
            raise HTTPException(
                status_code=409, detail=f"Player '{player.id}' already exists"
            )
        config.players.append(player)
        self._save(config)
        return self._with_problems(player, self._character_names())

    def update_player(self, player_id: str, player: Player) -> dict[str, Any]:
        if player_id != player.id:
            raise HTTPException(
                status_code=400, detail="Player id mismatch between URL and body"
            )
        config = self._load()
        for i, existing in enumerate(config.players):
            if existing.id == player_id:
                config.players[i] = player
                self._save(config)
                return self._with_problems(player, self._character_names())
        raise HTTPException(
            status_code=404, detail=f"Player '{player_id}' not found"
        )

    def delete_player(self, player_id: str) -> None:
        config = self._load()
        before = len(config.players)
        config.players = [p for p in config.players if p.id != player_id]
        if len(config.players) == before:
            raise HTTPException(
                status_code=404, detail=f"Player '{player_id}' not found"
            )
        self._save(config)

    def replace_all(self, players: list[Player]) -> list[dict[str, Any]]:
        """Overwrite the whole roster in one write.

        The page is a table the GM edits as a unit — reordering rows is a real
        operation, and per-row CRUD cannot express it. ``PlanningConfigEditor``
        works around the same problem with a delete-all-then-recreate sync,
        which is several writes wide and leaves the file empty in the middle.
        One atomic write instead.
        """
        ids = [p.id for p in players]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise HTTPException(
                status_code=409, detail=f"duplicate player ids: {', '.join(dupes)}"
            )
        config = PlayersConfig(players=players)
        self._save(config)
        known = self._character_names()
        return [self._with_problems(p, known) for p in config.players]
