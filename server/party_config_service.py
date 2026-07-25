"""Service owning the party roster's configuration slice.

Phase 5 of ``docs/config/grounding-isolation.md``. Storage is
``<config>/party.yaml``, which this service owns exclusively. Mirrors
``PlanningConfigService`` — same composition of ``PlatformConfigService`` for
``config_path_base``, same 404/409/400 contract, same "an emptied file reads
back as an empty collection, not a 400" behaviour.

What it replaces: ``config_routes.py``'s ``GET/PUT /api/config/party-yaml``,
which took the target file as a **parameter from the browser**, re-implemented
the three-state ``arc_score`` encoding in raw YAML, validated nothing beyond
"name and sheet are non-empty", and wrote with a bare ``write_text``. Every
isolated sibling derives its own path from ``config_path_base``; that pair was
an arbitrary-path read/write endpoint with no owner.

**Validation policy (D4).** Saves validate *shape* only and report referenced
files that don't exist rather than refusing the write — the GM must be able to
name a sheet they are about to create. Reads report the same. The CLI keeps
its strict behaviour at run time, where a missing file actually breaks
something. See :meth:`_with_missing`.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from campaignlib.party_config import (
    PARTY_CONFIG_FILENAME,
    PartyCharacter,
    PartyConfig,
    load_party_config,
    missing_files,
    save_party_config,
)


class PartyConfigService:
    """Owns ``<config>/party.yaml``."""

    def __init__(self, platform) -> None:
        self.platform = platform
        self.party_path = platform.config_path_base / PARTY_CONFIG_FILENAME

    # ── Load / save ───────────────────────────────────────────────────

    def _load(self) -> PartyConfig:
        try:
            return load_party_config(self.party_path)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Failed to load party config: {exc}"
            ) from exc

    def _save(self, config: PartyConfig) -> None:
        try:
            save_party_config(self.party_path, config)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Failed to save party config: {exc}"
            ) from exc

    def _with_missing(self, pc: PartyCharacter) -> dict[str, Any]:
        """Serialize one character plus its ``missing_files`` report.

        Paths resolve against the **campaign root**, matching the loader
        (Phase 2 / issues #145/#146) — not against ``party.yaml``'s directory.
        """
        report = missing_files(
            PartyConfig(characters=[pc]), self.platform.campaign_dir
        )
        return {**pc.model_dump(mode="json"), "missing_files": report.get(pc.name, [])}

    # ── Read ──────────────────────────────────────────────────────────

    def get_characters(self) -> list[dict[str, Any]]:
        return [self._with_missing(pc) for pc in self._load().characters]

    def get_character(self, name: str) -> dict[str, Any]:
        for pc in self._load().characters:
            if pc.name == name:
                return self._with_missing(pc)
        raise HTTPException(status_code=404, detail=f"Character '{name}' not found")

    # ── Write ─────────────────────────────────────────────────────────

    def create_character(self, pc: PartyCharacter) -> dict[str, Any]:
        config = self._load()
        if any(c.name == pc.name for c in config.characters):
            raise HTTPException(
                status_code=409, detail=f"Character '{pc.name}' already exists"
            )
        config.characters.append(pc)
        self._save(config)
        return self._with_missing(pc)

    def update_character(self, name: str, pc: PartyCharacter) -> dict[str, Any]:
        if name != pc.name:
            raise HTTPException(
                status_code=400, detail="Character name mismatch between URL and body"
            )
        config = self._load()
        for i, existing in enumerate(config.characters):
            if existing.name == name:
                config.characters[i] = pc
                self._save(config)
                return self._with_missing(pc)
        raise HTTPException(status_code=404, detail=f"Character '{name}' not found")

    def delete_character(self, name: str) -> None:
        config = self._load()
        before = len(config.characters)
        config.characters = [c for c in config.characters if c.name != name]
        if len(config.characters) == before:
            raise HTTPException(status_code=404, detail=f"Character '{name}' not found")
        self._save(config)

    def replace_all(self, characters: list[PartyCharacter]) -> list[dict[str, Any]]:
        """Overwrite the whole roster in one write.

        The editor is a table the GM edits as a unit — reordering rows is a
        real operation, and per-row CRUD cannot express it. ``PlanningConfig
        Editor`` works around the same problem with a delete-all-then-recreate
        sync, which is several writes wide and leaves the file empty in the
        middle. One atomic write instead.
        """
        names = [c.name for c in characters]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise HTTPException(
                status_code=409, detail=f"duplicate character names: {', '.join(dupes)}"
            )
        config = PartyConfig(characters=characters)
        self._save(config)
        return [self._with_missing(pc) for pc in config.characters]
