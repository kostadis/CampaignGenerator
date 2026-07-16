"""Shared CLI-flag builder for forwarding a chosen LLM backend to a subprocess.

Replaces three independently-reimplemented `_llm_env()` translators
(grounding.py, scene_editor.py, ensemble.py) that forwarded backend choice
as subprocess env vars — one of which forgot to handle "openrouter",
silently billing the metered Anthropic API instead of the user's choice.

Config *resolution* (where the backend/model/endpoint values come from)
stays per-router, since the three routers genuinely have different config
shapes (a FastAPI Request's config_service, a module-level CONFIG dict,
explicit per-call params from the ensemble UI). Only flag *building* is
shared here, mirroring campaignlib.api.client.add_backend_args's vocabulary
so every downstream script (which all now accept --backend/--endpoint(s)/
--model via that seam) receives exactly what it expects.
"""

from __future__ import annotations


def backend_cli_args(backend: str | None, model: str | None = None, *,
                     endpoint: str | None = None,
                     endpoints: list[str] | None = None) -> list[str]:
    """Build --backend/--endpoint(s)/--model flags for a subprocess cmd list.

    backend in (None, "anthropic") -> [] — the script's own argparse default
    applies, so a subprocess invoked with no flags at all still runs exactly
    as if a human had typed it with no --backend.

    Pass `endpoint` for a single-target script, `endpoints` (plural) for a
    DGX fan-out script — never both; `endpoints` wins if both are given.
    """
    if not backend or backend == "anthropic":
        return []
    args = ["--backend", backend]
    if endpoints:
        args += ["--endpoints", *endpoints]
    elif endpoint:
        args += ["--endpoint", endpoint]
    if model:
        args += ["--model", model]
    return args
