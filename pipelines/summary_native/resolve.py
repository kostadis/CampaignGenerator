"""The one place the registry and canon paths are decided (feature 031).

Precedence, everywhere: command-line flag > ``grounding.yaml``
``summary_native.<key>`` > default. ``validate``, ``build`` and ``synth`` (and
so synth's registry-staleness hash) all call these, so a registry configured in
``grounding.yaml`` hashes identically at build and at synth.
"""

from __future__ import annotations

from pathlib import Path

from campaignlib.registry import find_registry

from . import schema


class PathRefusal(ValueError):
    """A configured/flagged path that cannot be used; the message is user-facing."""


def _configured(flag, cfg, key: str) -> str | None:
    """The flag, else the grounding.yaml value; a hand-edited non-string is refused."""
    if flag:
        return flag
    value = (cfg or {}).get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise PathRefusal(f"grounding.yaml summary_native.{key} must be a path string, got {value!r}")
    return value


def resolve_canon_path(root, out_root, flag, cfg) -> Path:
    """``--canon`` > ``summary_native.canon_file`` > ``<out_root>/canon.yaml``.

    The default may be absent (no rulings yet). A path the GM named explicitly
    must exist: silently reading a typo'd path as "no rulings" would re-flag
    every pair already ruled distinct.
    """
    given = _configured(flag, cfg, "canon_file")
    if not given:
        return Path(out_root) / "canon.yaml"
    p = schema.resolve_under(root, given)
    if not p.is_file():
        raise PathRefusal(f"canon file {p}: not found (set explicitly via --canon or summary_native.canon_file)")
    return p


def resolve_registry_path(root, flag, cfg) -> Path | None:
    """``--registry`` > ``summary_native.registry`` > auto-discover under ``root``.

    A value may be a file or a directory (a directory is searched for
    ``docs/entity_registry.yaml``). Auto-discovery returns None when absent.
    """
    given = _configured(flag, cfg, "registry")
    if not given:
        return find_registry(root)  # the campaign root, not the cwd
    p = schema.resolve_under(root, given)
    if p.is_dir():
        found = find_registry(p)
        if found is None:
            raise PathRefusal(f"registry {p}: no entity_registry.yaml found under {p}/docs/")
        return found
    if not p.is_file():
        raise PathRefusal(f"registry {p}: not found (set explicitly via --registry or summary_native.registry)")
    return p
