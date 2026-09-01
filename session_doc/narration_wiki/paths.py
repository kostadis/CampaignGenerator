"""Explicit scope resolution and mutation-target containment policy."""

from __future__ import annotations

from pathlib import Path

from .models import CampaignScope, ScopeError, UsageError, require_stable_id


def _has_symlink_component(path: Path, *, stop: Path | None = None) -> bool:
    current = path
    boundary = stop.parent if stop else None
    while True:
        if current.is_symlink():
            return True
        if current == boundary or current.parent == current:
            return False
        current = current.parent


def _strict_directory(value: str | Path, label: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise UsageError(f"{label} must be explicit and non-empty")
    try:
        path = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ScopeError(f"{label} cannot be resolved: {exc}") from exc
    if not path.is_dir():
        raise ScopeError(f"{label} is not a directory")
    return path


def campaign_identity(campaign_root: Path) -> str:
    """Return the stable configured identity without consulting another campaign."""
    for candidate in (campaign_root / "config" / "campaign.yaml", campaign_root / "campaign.yaml"):
        if not candidate.is_file():
            continue
        try:
            import yaml

            value = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            for key in ("campaign_id", "name", "campaign"):
                if str(value.get(key, "")).strip():
                    return str(value[key]).strip()
    return campaign_root.name


def resolve_scope(
    campaign_dir: str | Path,
    session_dir: str | Path,
    iteration_id: str,
    *,
    portable_root: Path | None = None,
) -> CampaignScope:
    campaign = _strict_directory(campaign_dir, "campaign-dir")
    session_value = str(session_dir or "").strip()
    if not session_value:
        raise UsageError("session-dir must be explicit and non-empty")
    session_raw = Path(session_value).expanduser()
    if not session_raw.is_absolute():
        session_raw = campaign / session_raw
    session = _strict_directory(session_raw, "session-dir")
    try:
        relative = session.relative_to(campaign)
    except ValueError as exc:
        raise ScopeError("session-dir must be contained by campaign-dir") from exc
    if relative == Path("."):
        raise ScopeError("session-dir must be a proper descendant, not the campaign root")
    # Links are permitted only when their resolved destination remains in scope.
    unresolved = session_raw.absolute()
    try:
        unresolved.resolve(strict=True).relative_to(campaign)
    except ValueError as exc:
        raise ScopeError("session-dir contains an escaping symlink") from exc
    return CampaignScope(
        campaign_root=campaign,
        campaign_id=campaign_identity(campaign),
        session_root=session,
        session_relative=relative.as_posix(),
        iteration_id=require_stable_id(iteration_id, "iteration-id"),
        portable_root=portable_root or Path.home() / ".claude" / "narration-wiki",
    )


def contained_path(root: Path, relative: str | Path, *, mutation: bool = False) -> Path:
    value = Path(relative)
    if value.is_absolute():
        candidate = value
    else:
        candidate = root / value
    if mutation and _has_symlink_component(candidate, stop=root):
        raise ScopeError(f"mutation target contains a symlink component: {relative}")
    try:
        resolved = candidate.resolve(strict=candidate.exists())
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ScopeError(f"path escapes authorized root: {relative}") from exc
    return candidate


def authorized_target(scope: CampaignScope, kind: str, relative: str) -> Path:
    if scope.guidance is None:
        raise ScopeError("campaign guidance has not been resolved")
    allowed = scope.guidance.authorized_targets.get(kind, ())
    normalized = Path(relative).as_posix()
    if normalized not in allowed:
        raise ScopeError(f"{kind} target is not configured for this campaign: {relative}")
    return contained_path(scope.campaign_root, normalized, mutation=True)
