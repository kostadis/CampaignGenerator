"""The six compatibility aliases a managed grounding bundle owns in ``docs/``.

``docs/world_state.md`` (and its four siblings, plus ``docs/reference``) is a
relative symlink to ``grounding/current/<name>``. Migration installs them for a
legacy baseline; the first publication from an absent baseline installs them as
part of activation. An editor that saves over an alias replaces the link with a
loose copy (it *detaches*): promotion refuses while that conflict exists and
names both the detached path and the managed one, never repairing or
discarding either.
"""

from __future__ import annotations

import os
from pathlib import Path

from campaignlib.grounding_bundle import MANAGED_FILES, REFERENCE_NAME
from pipelines.summary_native.promotion.errors import PromotionPathError


# The same six paths the migrator plans and ``classify_managed_path`` accepts.
ALIAS_NAMES: tuple[str, ...] = (*sorted(MANAGED_FILES), REFERENCE_NAME)


def alias_target(name: str) -> str:
    return f"grounding/current/{name}"


def _kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.exists():
        return "file"
    return "absent"


def alias_states(campaign_dir: Path) -> dict[str, str]:
    """``docs/<name>`` -> ``exact`` | ``absent`` | ``file`` | ``directory`` | ``symlink`` (foreign)."""
    docs = Path(campaign_dir).absolute() / "docs"
    states: dict[str, str] = {}
    for name in ALIAS_NAMES:
        path = docs / name
        kind = _kind(path)
        if kind == "symlink" and os.readlink(path) == alias_target(name):
            kind = "exact"
        states[f"docs/{name}"] = kind
    return states


def loose_alias_paths(campaign_dir: Path) -> list[str]:
    """Paths occupied by anything but the exact alias (an absent baseline must have none)."""
    return [
        f"{path} ({kind})" for path, kind in alias_states(campaign_dir).items()
        if kind not in {"absent", "exact"}
    ]


def detached_aliases(campaign_dir: Path) -> list[str]:
    """Every alias of an active bundle that is not the exact expected symlink."""
    problems = []
    for path, kind in alias_states(campaign_dir).items():
        if kind == "exact":
            continue
        name = path.removeprefix("docs/")
        managed = f"docs/{alias_target(name)}"
        state = "missing" if kind == "absent" else f"detached ({kind})"
        problems.append(f"{path} is {state}; the managed member is {managed}")
    return problems


def install_aliases(campaign_dir: Path) -> None:
    """Create each missing alias; never replace anything that occupies an alias path.

    ``os.symlink`` either creates the link or fails, so an editor's file that
    appeared after the locked preview is refused, not clobbered.
    """
    docs = Path(campaign_dir).absolute() / "docs"
    created = False
    for name in ALIAS_NAMES:
        path = docs / name
        target = alias_target(name)
        if path.is_symlink() and os.readlink(path) == target:
            continue
        try:
            os.symlink(target, path)
        except FileExistsError as exc:
            raise PromotionPathError(
                f"docs/{name} is occupied by a {_kind(path)}; it must be the alias "
                f"to docs/{target} (move it aside, then run explicit recovery)"
            ) from exc
        created = True
    if created:
        descriptor = os.open(docs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
