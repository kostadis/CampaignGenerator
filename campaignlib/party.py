"""party.py — player-character (PC) name helpers.

PCs live in ``party.yaml``, NOT the entity registry: the registry importers
deliberately exclude them (players aren't module NPCs). But a registry-driven
run still has to treat PC names as *known*, or PC-named fact subjects look
"unknown" to ``Registry.known_names`` and fragment by chapter location — the
exact bug the registry rollout fixes for every other entity. So the single
consolidated home for "get the PC names for this campaign" lives here, and
``facts_to_state`` / ``registry`` both fold the result into ``known_names``.

``load_party_names`` is the path-level parser (one party.yaml file);
``load_pc_names`` is the campaign-level convenience (find the campaign's
party.yaml under docs/ or config/ and parse it).
"""

from __future__ import annotations

from pathlib import Path

import yaml


def load_party_names(path: "Path | None") -> list[str]:
    """Pull PC names out of a party.yaml file (``characters: [{name: ...}]``).

    Returns [] if ``path`` is None or does not exist.
    """
    if path is None or not Path(path).exists():
        return []
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    names: list[str] = []
    for c in data.get("characters", []):
        name = (c or {}).get("name")
        if name:
            names.append(str(name))
    return names


def load_pc_names(campaign_dir: "Path | str") -> list[str]:
    """PC names for a campaign: ``<campaign_dir>/docs/party.yaml`` if present,
    else ``<campaign_dir>/config/party.yaml``. Returns [] if neither exists.
    """
    campaign_dir = Path(campaign_dir)
    for rel in ("docs/party.yaml", "config/party.yaml"):
        candidate = campaign_dir / rel
        if candidate.exists():
            return load_party_names(candidate)
    return []
