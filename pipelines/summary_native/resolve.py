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


def resolve_canon_path(root, out_root, flag, cfg) -> Path:
    """``--canon`` > ``summary_native.canon_file`` > ``<out_root>/canon.yaml``."""
    given = flag or (cfg or {}).get("canon_file")
    return schema.resolve_under(root, given) if given else Path(out_root) / "canon.yaml"


def resolve_registry_path(root, flag, cfg) -> Path | None:
    """``--registry`` > ``summary_native.registry`` > auto-discover under ``root``.

    A value may be a file or a directory (a directory is searched for
    ``docs/entity_registry.yaml``). Auto-discovery returns None when absent.
    """
    given = flag or (cfg or {}).get("registry")
    if not given:
        return find_registry(root)  # the campaign root, not the cwd
    p = schema.resolve_under(root, given)
    if p.is_dir():
        found = find_registry(p)
        if found is None:
            raise PathRefusal(f"registry {p}: no entity_registry.yaml found under {p}/docs/")
        return found
    return p
