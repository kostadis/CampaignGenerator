"""Resolve summary-native per-endpoint concurrency with stable provenance."""
from __future__ import annotations

from dataclasses import dataclass

FALLBACK_CONCURRENCY = 6


@dataclass(frozen=True)
class ConcurrencyResolution:
    value: int
    source: str  # explicit | dgxlib | fallback
    model: str | None = None
    declared_max: int | None = None


def resolve_concurrency(*, explicit: int | None, backend: str, model: str | None) -> ConcurrencyResolution:
    """Apply explicit > selected DGX registry model > compatible fallback.

    A malformed registry declaration is an operator/configuration error.  An
    older dgxlib without this optional field remains compatible through 6.
    """
    if explicit is not None:
        if isinstance(explicit, bool) or not isinstance(explicit, int) or explicit <= 0:
            raise ValueError("--parallel must be a positive integer")
        return ConcurrencyResolution(explicit, "explicit", model)
    if backend == "dgx" and model:
        try:
            import dgxlib
            cfg = dgxlib.resolve_model_config(model)
        except ImportError:
            cfg = None
        if cfg is not None and hasattr(cfg, "max_concurrency"):
            declared = cfg.max_concurrency
            if declared is not None:
                if isinstance(declared, bool) or not isinstance(declared, int) or declared <= 0:
                    raise ValueError(f"dgxlib max_concurrency for {model!r} must be a positive integer")
                return ConcurrencyResolution(declared, "dgxlib", model, declared)
    return ConcurrencyResolution(FALLBACK_CONCURRENCY, "fallback", model)
