"""Model registry, default model, and stateless environment/filesystem probes.

Phase 4 (``docs/config/platform-isolation.md`` O2) moved this module's other
two roles out: ``derive_campaign_paths``'s discovery half became
``PlatformConfigService.discover_campaign_paths`` (its derivation half —
``output_dir``, ``DERIVED_SUBDIRS``, the hardcoded ``docs/``/``voice/``/
``examples/`` layout — was deleted outright: it duplicated
``resolve_path``/``_PATH_FIELDS`` and had already drifted, still emitting
``roleplay_extract_dir``/``summary_extract_dir``, the pre-Phase-5 names the
session editor renamed to ``*_extractions_dir``). ``derive_session_paths``
(a one-line wrapper with no caller) and ``get_campaign_dir_from_request``
(folded into ``platform_config_service.require_platform``, the one "give me
the live PlatformConfigService or 503" accessor every router now shares) are
both gone too.

What is left has no natural service ownership boundary: ``MODELS``/
``DEFAULT_MODEL`` and the two probes below are free functions with no
persisted state to isolate.

Phase 5a (``docs/config/platform-isolation.md`` O4's non-wiring half)
removes the second independent ``DEFAULT_MODEL`` definition that used to
live here: this module now imports ``campaignlib.constants.DEFAULT_MODEL``
— the single definition every CLI script reads, and the one
``server/platform_config_shared.py``'s ``PlatformRuntime.default_model``
field also now reads via its ``default_factory`` — instead of re-deriving
``os.environ.get("CAMPAIGN_MODEL") or "claude-sonnet-4-6"`` a third time.
Re-exported here (not renamed/removed) because ``server/routers/
config_routes.py`` and ``server/routers/setup.py`` already import it as
``from server.config import DEFAULT_MODEL`` / ``from campaignlib import
DEFAULT_MODEL`` respectively — both now resolve to the same object.

``MODELS`` is refreshed to the current model family — it had drifted to
missing Opus 5 / Sonnet 5 / Fable 5 entirely, while still carrying
``claude-sonnet-4-20250514`` (deprecated, retiring 2026-06-15) and a
needlessly date-suffixed ``claude-haiku-4-5-20251001`` (the bare alias
``claude-haiku-4-5`` is the correct id — model ids in this list are never
date-suffixed). ``claude-mythos-5`` is deliberately excluded: it is
available only to Project Glasswing participants, not general release.

``MODELS`` stays a hardcoded Python list, deliberately: relocating its
*source* into ``wiring.yaml`` (mneme-rendered per-install config, so adding
a model needs no CampaignGenerator release) is Phase 5b — deferred, needs a
template change in the separate ``mneme`` repo, not done here.
"""

from pathlib import Path

from campaignlib import DEFAULT_MODEL

MODELS = [
    "claude-opus-5",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]


def path_exists(path_str: str) -> bool:
    """Check if a file or directory exists."""
    if not path_str or not path_str.strip():
        return False
    return Path(path_str).expanduser().exists()
