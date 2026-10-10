"""Strict configuration shared by every review entry point.

The review CLI, the local application adapter, and the dedicated capability
service all import this module.  Defaults therefore have one owner and an
unknown configuration key is always an error rather than a silently ignored
spelling variant.
"""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from campaignlib.config import (
    ConfigLocationError,
    campaign_root_for_config,
    find_default_config,
)


REVIEW_CONFIG_FILENAME = "review.yaml"

DEFAULT_GRANT_EXPIRY_SECONDS = 24 * 60 * 60
DEFAULT_MAX_REQUEST_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_NOTE_CHARS = 16 * 1024
DEFAULT_MAX_BATCH_DECISIONS = 100
DEFAULT_MAX_PAGE_ITEMS = 50
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_SECTION_BYTES = 64 * 1024
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0
DEFAULT_PORT = 8766

_TAILSCALE_V4 = ip_network("100.64.0.0/10")


class ReviewConfigError(ValueError):
    """A deliberate refusal while loading or resolving review configuration."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


class ReviewConfig(BaseModel):
    """The complete ``config/review.yaml`` schema.

    ``bind_host`` and ``origin`` intentionally have no operational default.
    Supplying either requires supplying both; service commands may provide the
    pair explicitly without writing it to the campaign configuration.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    bind_host: str | None = None
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)
    origin: str | None = None
    grant_expiry_seconds: int = Field(
        default=DEFAULT_GRANT_EXPIRY_SECONDS,
        ge=60,
        le=31 * 24 * 60 * 60,
    )
    max_request_bytes: int = Field(default=DEFAULT_MAX_REQUEST_BYTES, ge=1024)
    max_note_chars: int = Field(default=DEFAULT_MAX_NOTE_CHARS, ge=1)
    max_batch_decisions: int = Field(default=DEFAULT_MAX_BATCH_DECISIONS, ge=1)
    max_page_items: int = Field(default=DEFAULT_MAX_PAGE_ITEMS, ge=1)
    max_response_bytes: int = Field(default=DEFAULT_MAX_RESPONSE_BYTES, ge=1024)
    max_section_bytes: int = Field(default=DEFAULT_MAX_SECTION_BYTES, ge=1024, le=1024 * 1024)
    command_timeout_seconds: float = Field(
        default=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        gt=0,
        le=300,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def _endpoint_is_explicit_and_private(self):
        if (self.bind_host is None) != (self.origin is None):
            raise ValueError("bind_host and origin must be configured together")
        if self.bind_host is None:
            return self

        host = self.bind_host.strip()
        if host != self.bind_host or not host:
            raise ValueError("bind_host must be a nonblank IP address without padding")
        try:
            address = ip_address(host)
        except ValueError as exc:
            raise ValueError("bind_host must be an explicit IP address") from exc
        if address.is_unspecified or address.is_multicast:
            raise ValueError("bind_host cannot be wildcard, unspecified, or multicast")
        is_tailnet = address.version == 4 and address in _TAILSCALE_V4
        if not (address.is_loopback or address.is_private or address.is_link_local or is_tailnet):
            raise ValueError("bind_host must be loopback or a private LAN/Tailscale address")

        assert self.origin is not None
        parsed = urlsplit(self.origin)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("origin must be an absolute http(s) browser origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("origin cannot contain credentials, query, or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError("origin must not contain a path")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("origin contains an invalid port") from exc
        if self.origin.endswith("/"):
            raise ValueError("origin must use its exact no-trailing-slash spelling")
        return self


def load_review_config(path: Path | str) -> ReviewConfig:
    """Load one strict review config; a missing or empty file means defaults."""

    config_path = Path(path)
    if not config_path.is_file():
        return ReviewConfig()
    try:
        raw = yaml.load(config_path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ReviewConfigError(f"{config_path.name}: invalid YAML: {exc}") from exc
    if raw is None:
        return ReviewConfig()
    if not isinstance(raw, dict):
        raise ReviewConfigError(f"{config_path.name}: must be a mapping")
    try:
        return ReviewConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ReviewConfigError(f"{config_path.name}: {problems}") from None


def resolve_campaign_scope(
    *,
    config: Path | str | None = None,
    campaign_dir: Path | str | None = None,
) -> tuple[Path, Path | None]:
    """Resolve exactly one canonical campaign root and optional main config.

    An explicit ``campaign_dir`` is sufficient for administrative review
    commands.  If ``config`` is also supplied, it must be the declared
    ``<campaign>/config/config.yaml`` belonging to that same campaign.
    Without either argument the existing default-config discovery rule owns
    resolution.
    """

    resolved_campaign = (
        Path(campaign_dir).expanduser().resolve() if campaign_dir is not None else None
    )
    resolved_config = Path(config).expanduser().resolve() if config is not None else None

    if resolved_config is None and resolved_campaign is None:
        try:
            resolved_config = Path(find_default_config()).expanduser().resolve()
        except ConfigLocationError as exc:
            raise ReviewConfigError(str(exc)) from exc

    config_campaign: Path | None = None
    if resolved_config is not None:
        if not resolved_config.is_file():
            raise ReviewConfigError(f"config file does not exist: {resolved_config}")
        try:
            config_campaign = campaign_root_for_config(resolved_config).resolve()
        except ConfigLocationError as exc:
            raise ReviewConfigError(str(exc)) from exc

    if resolved_campaign is not None and config_campaign is not None:
        if resolved_campaign != config_campaign:
            raise ReviewConfigError("--config and --campaign-dir name different campaigns")
    campaign = resolved_campaign or config_campaign
    assert campaign is not None
    if not campaign.is_dir():
        raise ReviewConfigError(f"campaign directory does not exist: {campaign}")
    return campaign, resolved_config


def load_campaign_review_config(campaign_dir: Path | str) -> ReviewConfig:
    """Load the one declared campaign-local review configuration file."""

    return load_review_config(Path(campaign_dir) / "config" / REVIEW_CONFIG_FILENAME)


# The longer spelling reads naturally in CLI adapters; keep both names on the
# same implementation so campaign resolution cannot drift between consumers.
resolve_review_scope = resolve_campaign_scope
