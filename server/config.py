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
persisted state to isolate. ``MODELS``/``DEFAULT_MODEL`` stay untouched
deliberately — Phase 5 (O4) relocates the model registry to ``wiring.yaml``,
and this module shrinks further then.
"""

import os
from pathlib import Path

MODELS = [
    "claude-sonnet-4-6",
    "claude-sonnet-4-20250514",
    "claude-opus-4-8",
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
]

# Mirror campaignlib's CAMPAIGN_MODEL override so the UI's default model
# matches whatever the CLI scripts default to.
DEFAULT_MODEL = os.environ.get("CAMPAIGN_MODEL") or "claude-sonnet-4-6"


def api_key_present() -> bool:
    """Check if ANTHROPIC_API_KEY is set."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def path_exists(path_str: str) -> bool:
    """Check if a file or directory exists."""
    if not path_str or not path_str.strip():
        return False
    return Path(path_str).expanduser().exists()
