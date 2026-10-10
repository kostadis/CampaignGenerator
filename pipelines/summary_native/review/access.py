"""Persistent, capability-scoped access grants for one prepared review."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from campaignlib.review_config import load_campaign_review_config
from pipelines.summary_native.authority_apply import authority_lock, require_no_pending_transaction
from pipelines.summary_native.review.models import (
    AccessAction,
    AccessGrant,
    canonical_bytes,
    model_from_json,
)
from pipelines.summary_native.review.store import (
    ReviewStoreError,
    load_campaign_identity,
    read_snapshot,
    review_root,
)


TOKEN_BYTES = 32


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _access_dir(root: Path, review_id: str) -> Path:
    # read_snapshot applies the canonical review-id and symlink checks before
    # callers reach this private credential directory.
    return review_root(root) / review_id / "access"


def _reject_symlink_components(root: Path, path: Path) -> None:
    root = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ReviewStoreError("REVIEW_ACCESS_INVALID: credential path escapes campaign") from exc
    cursor = root
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise ReviewStoreError("REVIEW_ACCESS_INVALID: symlink in credential path")


def _grant_path(root: Path, review_id: str, grant_id: str) -> Path:
    if not grant_id or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for char in grant_id
    ):
        raise ReviewStoreError("REVIEW_ACCESS_INVALID: invalid grant id")
    path = _access_dir(root, review_id) / f"{grant_id}.json"
    _reject_symlink_components(root, path)
    return path


def _write_private(path: Path, data: bytes) -> None:
    path = Path(path)
    if len(path.parents) < 5 or path.parents[3].name != "docs":
        raise ReviewStoreError("REVIEW_ACCESS_INVALID: credential path is not campaign-local")
    root = path.parents[4].resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ReviewStoreError("REVIEW_ACCESS_INVALID: credential path escapes campaign") from exc
    if (
        len(relative.parts) != 5
        or relative.parts[:2] != ("docs", "reviews")
        or relative.parts[3] != "access"
    ):
        raise ReviewStoreError("REVIEW_ACCESS_INVALID: credential path is not campaign-local")

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(root, directory_flags)
    try:
        for index, component in enumerate(relative.parts[:-1]):
            if index == len(relative.parts[:-1]) - 1:
                try:
                    os.mkdir(component, 0o700, dir_fd=directory_fd)
                except FileExistsError:
                    pass
            try:
                child_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            except OSError as exc:
                raise ReviewStoreError(
                    "REVIEW_ACCESS_INVALID: credential directory must be a private real directory"
                ) from exc
            os.close(directory_fd)
            directory_fd = child_fd
        os.fchmod(directory_fd, 0o700)

        temporary = f".{path.name}.{secrets.token_hex(8)}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                existing = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                existing = None
            if existing is not None and stat.S_ISLNK(existing.st_mode):
                raise ReviewStoreError("REVIEW_ACCESS_INVALID: credential file cannot be a symlink")
            os.replace(
                temporary,
                path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            credential_fd = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            try:
                os.fchmod(credential_fd, 0o600)
            finally:
                os.close(credential_fd)
            os.fsync(directory_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory_fd)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _runtime_handle(root: Path, review_id: str) -> dict:
    path = root / ".review-runtime" / f"{review_id}.json"
    _reject_symlink_components(root, path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewStoreError(
            "REVIEW_SERVICE_REQUIRED: start the review service before issuing a link"
        ) from exc
    if not isinstance(value, dict) or value.get("review_id") != review_id:
        raise ReviewStoreError("REVIEW_SERVICE_REQUIRED: active service handle is invalid")
    from pipelines.summary_native.review.service import _is_live

    if not _is_live(value):
        raise ReviewStoreError("REVIEW_SERVICE_REQUIRED: review service is not running")
    origin = value.get("origin")
    if not isinstance(origin, str) or not origin:
        raise ReviewStoreError("REVIEW_SERVICE_REQUIRED: active service has no advertised origin")
    return value


def issue_grant(
    campaign_dir: Path,
    review_id: str,
    *,
    expires_in: int | None = None,
    origin: str | None = None,
) -> dict:
    """Create a grant and return its raw capability exactly once."""

    root = Path(campaign_dir).resolve()
    manifest, _, _ = read_snapshot(root, review_id)
    identity = load_campaign_identity(root)
    config = load_campaign_review_config(root)
    duration = config.grant_expiry_seconds if expires_in is None else expires_in
    if not isinstance(duration, int) or isinstance(duration, bool) or not 60 <= duration <= 31 * 86400:
        raise ReviewStoreError("REVIEW_ACCESS_INVALID: --expires-in must be between 60 and 2678400 seconds")
    advertised_origin = origin or str(_runtime_handle(root, review_id)["origin"])
    token = secrets.token_urlsafe(TOKEN_BYTES)
    grant_id = f"grant-{secrets.token_hex(16)}"
    now = _utcnow()
    grant = AccessGrant(
        grant_id=grant_id,
        campaign_id=identity.campaign_id,
        review_id=manifest.review_id,
        token_sha256=_token_digest(token),
        allowed_actions={AccessAction.READ_REVIEW, AccessAction.SAVE_DECISION},
        issued_at=now,
        expires_at=now + timedelta(seconds=duration),
    )
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        _write_private(_grant_path(root, review_id, grant_id), canonical_bytes(grant))
    return {
        "grant_id": grant_id,
        "review_id": review_id,
        "expires_at": grant.expires_at.isoformat().replace("+00:00", "Z"),
        "url": f"{advertised_origin}/r/{token}/",
    }


def revoke_grant(campaign_dir: Path, review_id: str, grant_id: str) -> dict:
    root = Path(campaign_dir).resolve()
    read_snapshot(root, review_id)
    path = _grant_path(root, review_id, grant_id)
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        try:
            grant = model_from_json(AccessGrant, path.read_bytes())
        except (OSError, ValueError) as exc:
            raise ReviewStoreError("REVIEW_ACCESS_UNKNOWN: grant does not exist") from exc
        identity = load_campaign_identity(root)
        if grant.review_id != review_id or grant.campaign_id != identity.campaign_id:
            raise ReviewStoreError("REVIEW_ACCESS_UNKNOWN: grant does not exist")
        if grant.revoked:
            return {"grant_id": grant_id, "revoked": True}
        revoked = grant.model_copy(update={"revoked": True, "revoked_at": _utcnow()})
        _write_private(path, canonical_bytes(revoked))
    return {"grant_id": grant_id, "revoked": True}


def _load_grants(root: Path, review_id: str) -> Iterable[AccessGrant]:
    directory = _access_dir(root, review_id)
    try:
        _reject_symlink_components(root, directory)
    except ReviewStoreError:
        return ()
    if not directory.is_dir() or directory.is_symlink():
        return ()
    result: list[AccessGrant] = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink():
            continue
        try:
            result.append(model_from_json(AccessGrant, path.read_bytes()))
        except (OSError, ValueError):
            # A malformed credential is unusable and must not turn a guessed
            # token into an existence oracle.
            continue
    return tuple(result)


def _active(grant: AccessGrant, *, review_id: str, action: AccessAction) -> bool:
    now = _utcnow()
    return (
        grant.review_id == review_id
        and not grant.revoked
        and grant.issued_at <= now < grant.expires_at
        and action in grant.allowed_actions
    )


def authenticate_token(
    campaign_dir: Path,
    review_id: str,
    token: str,
    *,
    action: AccessAction = AccessAction.READ_REVIEW,
) -> AccessGrant | None:
    """Return the matching live grant without disclosing why auth failed."""

    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        return None
    try:
        supplied = _token_digest(token)
        campaign_id = load_campaign_identity(campaign_dir).campaign_id
    except (UnicodeEncodeError, ValueError):
        return None
    match: AccessGrant | None = None
    for grant in _load_grants(Path(campaign_dir).resolve(), review_id):
        equal = hmac.compare_digest(grant.token_sha256, supplied)
        if (
            equal
            and grant.campaign_id == campaign_id
            and _active(grant, review_id=review_id, action=action)
        ):
            match = grant
    return match


def validate_grant(
    campaign_dir: Path,
    review_id: str,
    grant_id: str,
    token: str,
    *,
    action: AccessAction = AccessAction.SAVE_DECISION,
) -> None:
    """Validate an exact grant; safe to call while the writer lock is held."""

    root = Path(campaign_dir).resolve()
    try:
        grant = model_from_json(AccessGrant, _grant_path(root, review_id, grant_id).read_bytes())
        supplied = _token_digest(token)
        campaign_id = load_campaign_identity(root).campaign_id
    except (OSError, ValueError, UnicodeEncodeError) as exc:
        raise ReviewStoreError(
            "REVIEW_ACCESS_DENIED: capability is unavailable",
            "REVIEW_ACCESS_DENIED",
        ) from exc
    if (
        grant.campaign_id != campaign_id
        or not hmac.compare_digest(grant.token_sha256, supplied)
        or not _active(grant, review_id=review_id, action=action)
    ):
        raise ReviewStoreError(
            "REVIEW_ACCESS_DENIED: capability is unavailable",
            "REVIEW_ACCESS_DENIED",
        )
