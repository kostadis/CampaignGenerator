"""One reading of ``--config`` and ``out_root`` for promote, promotion and claims.

``--config`` names ``<campaign>/config/config.yaml`` on every ``summary_native``
subcommand, auto-detected from the working directory when omitted (Principle
XII). ``grounding.yaml`` is found beside it, as the build commands find it, and
``summary_native.out_root`` resolves against the campaign root through the same
``schema.resolve_under`` the build and synth commands use, so drafts are looked
for where they were written.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from campaignlib.config import ConfigLocationError, campaign_root_for_config, find_default_config
from pipelines.summary_native import schema
from pipelines.summary_native.promotion.errors import PromotionError


@dataclass(frozen=True)
class PromotionSettings:
    root: Path
    config_path: Path
    grounding_path: Path
    summary_native: dict[str, Any] | None


def load_settings(config_arg: str | None, *, code: str = "PROMOTION_CONFIG_INVALID") -> PromotionSettings:
    """Resolve ``--config`` (config.yaml) and read ``grounding.yaml`` beside it."""
    try:
        config_path = Path(config_arg).expanduser() if config_arg else Path(find_default_config())
    except ConfigLocationError as exc:
        raise PromotionError(str(exc), code=code) from exc
    if config_path.name == "grounding.yaml":
        raise PromotionError(
            "--config names config/config.yaml, as on every summary_native command; "
            "grounding.yaml is read from beside it",
            code=code,
        )
    config_path = config_path.resolve()
    try:
        root = campaign_root_for_config(config_path)
    except ConfigLocationError as exc:
        raise PromotionError(str(exc), code=code) from exc
    grounding = config_path.parent / "grounding.yaml"
    raw: Any = {}
    if grounding.is_file():
        try:
            raw = yaml.safe_load(grounding.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise PromotionError(f"grounding.yaml is not valid YAML: {exc}", code=code) from exc
    summary = raw.get("summary_native") if isinstance(raw, dict) else None
    if summary is not None and not isinstance(summary, dict):
        raise PromotionError("grounding.yaml summary_native must be a mapping", code=code)
    return PromotionSettings(root=root, config_path=config_path, grounding_path=grounding, summary_native=summary)


def resolve_out_root(settings: PromotionSettings, explicit: str | None, *, code: str = "PROMOTION_PATH_CONFLICT") -> str:
    """``--out-root`` > ``summary_native.out_root`` > the schema default, campaign-relative."""
    configured = (settings.summary_native or {}).get("out_root")
    value = explicit or (configured if isinstance(configured, str) and configured else schema.DEFAULT_OUT_ROOT)
    resolved = schema.resolve_under(settings.root, value).resolve()
    try:
        return resolved.relative_to(settings.root).as_posix()
    except ValueError as exc:
        raise PromotionError("summary_native out_root escapes campaign", code=code) from exc
