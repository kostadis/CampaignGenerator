"""Safe filesystem boundary for managed grounding bundles."""

from __future__ import annotations

import hashlib
import os
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Iterator, Mapping, Sequence

from pipelines.summary_native.authority import AuthorityError
from pipelines.summary_native.authority_apply import authority_lock
from pipelines.summary_native.promotion.errors import (
    PromotionError,
    PromotionMigrationRequired,
    PromotionPathError,
    PromotionRecoveryRequired,
)
from pipelines.summary_native.review.models import canonical_digest


MANAGED_FILES = frozenset(
    {
        "world_state.md",
        "campaign_state.md",
        "party.md",
        "planning.md",
        "canon_events_timeline.md",
    }
)
REFERENCE_NAME = "reference"
GROUNDING_RELATIVE = Path("docs/grounding")
NOT_PUBLISHED_CODE = "PROMOTION_NO_GENERATION"


class GroundingNotPublished(PromotionMigrationRequired):
    """A completed ``absent`` migration: managed, but nothing published yet.

    This is a valid migrated layout, not a migration request. Unrelated reads
    proceed; only a read that selects a managed member refuses, because there is
    no generation to read it from. It subclasses ``PromotionMigrationRequired``
    so promotion preview keeps treating the initialized absent baseline as the
    parent of a first publication, but it carries its own code and message.
    """

    def __init__(self, message: str | None = None, *, campaign_dir: object | None = None) -> None:
        self.campaign_dir = campaign_dir
        PromotionError.__init__(
            self,
            message
            or (
                "no published grounding generation yet: this campaign was migrated with an "
                "absent baseline. Publish the first whole bundle with `summary_native promote` "
                "(or the Summary-native Promotion panel) before reading managed grounding."
            ),
            code=NOT_PUBLISHED_CODE,
        )


@dataclass(frozen=True)
class GroundingLayout:
    campaign_dir: Path
    docs_dir: Path
    grounding_dir: Path
    current_link: Path
    generation_id: str
    live_dir: Path


@dataclass(frozen=True)
class GroundingSnapshot:
    generation_id: str
    live_digest: str
    members: Mapping[str, bytes]
    edited_since_publication: bool

    def read(self, relative_path: str) -> bytes:
        try:
            return self.members[relative_path]
        except KeyError as exc:
            raise PromotionPathError(f"snapshot does not contain {relative_path}") from exc


def _raw_no_symlink(path: Path, stop: Path) -> None:
    """Reject symlink components without resolving away the evidence."""
    absolute = path.absolute()
    root = stop.absolute()
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise PromotionPathError(f"path is outside campaign: {path}") from exc
    cursor = root
    if cursor.is_symlink():
        raise PromotionPathError(f"managed root is a symlink: {cursor}")
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise PromotionPathError(f"unexpected symlink component: {cursor}")


def _contained_relative(value: str) -> PurePosixPath:
    if not value or value == "." or "\\" in value or "\x00" in value:
        raise PromotionPathError("managed member must be a POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise PromotionPathError(f"unsafe managed member path: {value}")
    if path.name in MANAGED_FILES and len(path.parts) == 1:
        return path
    if path.parts and path.parts[0] == REFERENCE_NAME and len(path.parts) > 1:
        return path
    raise PromotionPathError(f"path is not a managed bundle member: {value}")


def _absent_baseline_committed(grounding: Path) -> bool:
    """True only for a layout the migrator committed with an absent baseline."""
    layout_path = grounding / "layout.json"
    if layout_path.is_symlink() or not layout_path.is_file():
        return False
    try:
        metadata = json.loads(layout_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if (
        not isinstance(metadata, dict)
        or metadata.get("version") != 1
        or metadata.get("state") != "absent"
        or metadata.get("generation_id") is not None
    ):
        return False
    operation = metadata.get("migration_operation_id")
    if not isinstance(operation, str) or not operation or "/" in operation or operation in {".", ".."}:
        return False
    receipt_path = grounding / "migrations" / operation / "receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        return False
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(receipt, dict)
        and receipt.get("state") == "committed"
        and receipt.get("baseline") == "absent"
        and receipt.get("operation_id") == operation
    )


def layout_state(campaign_dir: Path) -> GroundingLayout | None:
    """Inspect a managed layout, returning ``None`` for a valid absent baseline.

    Use this where the caller has not selected a managed member yet and must
    still surface pending migration or unreconciled activation: an absent
    baseline is a healthy layout with nothing published, so it is not an error
    until a managed member is actually requested.
    """
    try:
        return inspect_layout(campaign_dir)
    except GroundingNotPublished:
        return None


def inspect_layout(campaign_dir: Path) -> GroundingLayout:
    """Resolve the active generation once without creating state."""
    raw_root = Path(campaign_dir).absolute()
    _raw_no_symlink(raw_root / "docs", raw_root)
    docs = raw_root / "docs"
    grounding = docs / "grounding"
    _raw_no_symlink(grounding, raw_root)
    if (grounding / "migration-pending.json").exists():
        raise PromotionRecoveryRequired("grounding migration is pending; run migrate_grounding_bundle --recover")
    operations = grounding / "operations"
    if operations.is_dir():
        for state_path in sorted(operations.glob("*/state.json")):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8")).get("state")
            except (OSError, ValueError):
                raise PromotionRecoveryRequired("promotion operation state is unreadable")
            if state in {"activation_pending", "commit_unknown", "intervention_required"}:
                raise PromotionRecoveryRequired(
                    f"promotion operation {state_path.parent.name} requires explicit recovery"
                )
    current = grounding / "current"
    if not grounding.is_dir() or not current.is_symlink():
        if grounding.is_dir() and not os.path.lexists(current) and _absent_baseline_committed(grounding):
            raise GroundingNotPublished(campaign_dir=raw_root)
        raise PromotionMigrationRequired(campaign_dir=raw_root)
    target_text = os.readlink(current)
    target = PurePosixPath(target_text)
    if target.is_absolute() or any(part in {"", ".", ".."} for part in target.parts):
        raise PromotionPathError("current must be a contained relative symlink")
    expected_prefix = ("generations",)
    if target.parts[:1] != expected_prefix or len(target.parts) != 3 or target.parts[2] != "live":
        raise PromotionPathError("current must name generations/<id>/live")
    generation_id = target.parts[1]
    live = grounding.joinpath(*target.parts)
    # The current link is the one allowed symlink. Its target and every target
    # component must otherwise be real contained directories.
    _raw_no_symlink(live, raw_root)
    if not live.is_dir():
        raise PromotionPathError("current generation live tree is missing")
    layout_path = grounding / "layout.json"
    if layout_path.is_symlink() or not layout_path.is_file():
        raise PromotionRecoveryRequired("managed layout metadata is missing")
    try:
        metadata = json.loads(layout_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PromotionRecoveryRequired("managed layout metadata is unreadable") from exc
    if (metadata.get("version") != 1 or metadata.get("state") != "active"
            or metadata.get("generation_id") != generation_id):
        raise PromotionRecoveryRequired("managed layout is not active")
    manifest_path = live.parent / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PromotionRecoveryRequired("active generation manifest is missing")
    try:
        from pipelines.summary_native.promotion.models import GenerationManifest
        from pipelines.summary_native.review.models import canonical_digest
        manifest = GenerationManifest.model_validate_json(manifest_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise PromotionRecoveryRequired("active generation manifest is invalid") from exc
    if manifest.generation_id != generation_id or manifest.manifest_sha256 != canonical_digest(
        manifest, exclude_fields=frozenset({"manifest_sha256"})
    ):
        raise PromotionRecoveryRequired("active generation manifest identity is invalid")
    try:
        from pipelines.summary_native.promotion.history import current_activation
        current_activation(raw_root, generation_id)
    except Exception as exc:
        if isinstance(exc, PromotionRecoveryRequired):
            raise
        raise PromotionRecoveryRequired("active generation has no reconciled activation") from exc
    return GroundingLayout(raw_root.resolve(), docs.resolve(), grounding.resolve(), current, generation_id, live.resolve())


def classify_managed_path(
    path: Path,
    campaign_dir: Path,
    layout: GroundingLayout | None = None,
    *,
    allow_unpublished: bool = False,
) -> str | None:
    """Return member-relative identity or ``None`` for a nonmanaged path.

    Only the six compatibility aliases, the pinned current spelling, and the
    pinned live tree are accepted. No caller follows ``current`` independently.

    On a valid absent baseline a managed path names a member that has not been
    published: readers get ``GroundingNotPublished``; write guards pass
    ``allow_unpublished=True`` and receive the member identity so they can
    refuse the write rather than create a loose file where an alias belongs.
    """
    raw_root = Path(campaign_dir).absolute()
    supplied = Path(path)
    if any(part == ".." for part in supplied.parts):
        raise PromotionPathError(f"path traversal is not allowed: {path}")
    lexical = supplied.absolute() if supplied.is_absolute() else (raw_root / supplied).absolute()
    docs = raw_root / "docs"
    try:
        docs_relative = lexical.relative_to(docs)
    except ValueError:
        return None
    parts = docs_relative.parts
    if not parts:
        return None

    def active() -> GroundingLayout | None:
        if layout is not None:
            return layout
        try:
            return inspect_layout(raw_root)
        except GroundingNotPublished:
            if allow_unpublished:
                return None
            raise

    if parts[0] in MANAGED_FILES and len(parts) == 1:
        if active() is None:
            return _contained_relative(parts[0]).as_posix()
        expected = f"grounding/current/{parts[0]}"
        if not lexical.is_symlink() or os.readlink(lexical) != expected:
            raise PromotionPathError(f"managed compatibility alias is detached: {lexical}")
        return _contained_relative(parts[0]).as_posix()
    if parts[0] == REFERENCE_NAME and len(parts) > 1:
        if active() is None:
            return _contained_relative(PurePosixPath(*parts).as_posix()).as_posix()
        alias = docs / REFERENCE_NAME
        if not alias.is_symlink() or os.readlink(alias) != "grounding/current/reference":
            raise PromotionPathError(f"managed compatibility alias is detached: {alias}")
        return _contained_relative(PurePosixPath(*parts).as_posix()).as_posix()
    # A docs-relative path outside the managed aliases and grounding namespace
    # is provably unrelated and must not force migration.
    if parts[0] != "grounding":
        return None
    current_prefix = Path("grounding/current")
    try:
        pinned = layout if layout is not None else inspect_layout(raw_root)
    except GroundingNotPublished:
        # Grounding bookkeeping (layout.json, migrations/) is unrelated; only
        # the current spelling names an unpublished member.
        try:
            relative = docs_relative.relative_to(current_prefix)
        except ValueError:
            return None
        if not allow_unpublished:
            raise
        return _contained_relative(PurePosixPath(*relative.parts).as_posix()).as_posix()
    for prefix in (
        current_prefix,
        Path("grounding/generations") / pinned.generation_id / "live",
    ):
        try:
            relative = docs_relative.relative_to(prefix)
        except ValueError:
            continue
        return _contained_relative(PurePosixPath(*relative.parts).as_posix()).as_posix()
    retired_prefix = Path("grounding/generations")
    try:
        retired = docs_relative.relative_to(retired_prefix)
    except ValueError:
        retired = None
    if retired is not None and len(retired.parts) >= 3 and retired.parts[1] == "live":
        raise PromotionPathError(
            f"managed path names a retired generation: {lexical}"
        )
    return None


def lexical_campaign_path(path: Path | str) -> Path:
    """``Path.resolve()`` that does not follow a managed grounding link.

    ``resolve()`` follows ``docs/<member>``, ``docs/reference`` and
    ``docs/grounding/current`` into ``generations/<id>/live``, so a stored
    resolved path silently pins one generation and keeps reading it after the
    next promotion retires it. This resolves exactly as before, except that it
    stops at a compatibility alias (or ``current``) whose target is exactly the
    managed one: everything above it is resolved, the alias and everything
    below it are kept as spelled (lexically normalized).
    """
    absolute = Path(path).expanduser().absolute()
    parts = absolute.parts
    for index in range(1, len(parts)):
        candidate = Path(*parts[: index + 1])
        if not candidate.is_symlink():
            continue
        parent, name = candidate.parent, candidate.name
        managed = False
        if parent.name == "docs" and (name in MANAGED_FILES or name == REFERENCE_NAME):
            managed = os.readlink(candidate) == f"grounding/current/{name}"
        elif name == "current" and parent.name == "grounding" and parent.parent.name == "docs":
            target = PurePosixPath(os.readlink(candidate))
            managed = (
                not target.is_absolute()
                and len(target.parts) == 3
                and target.parts[0] == "generations"
                and target.parts[2] == "live"
            )
        if managed:
            return Path(os.path.normpath(parent.resolve().joinpath(*parts[index:])))
    return absolute.resolve()


def _collect_members(live: Path, requested: Sequence[str] | None) -> dict[str, bytes]:
    names = tuple(requested) if requested is not None else tuple(sorted(MANAGED_FILES))
    paths: list[PurePosixPath] = [_contained_relative(name) for name in names]
    if requested is None:
        reference = live / REFERENCE_NAME
        if reference.is_symlink() or not reference.is_dir():
            raise PromotionPathError("active generation reference directory is missing")
        for item in sorted(reference.rglob("*")):
            if item.is_symlink():
                raise PromotionPathError(f"reference contains symlink: {item}")
            if item.is_file():
                paths.append(PurePosixPath(item.relative_to(live).as_posix()))
            elif not item.is_dir():
                raise PromotionPathError(f"reference contains special file: {item}")
    result: dict[str, bytes] = {}
    for relative in paths:
        item = live.joinpath(*relative.parts)
        _raw_no_symlink(item, live)
        if not item.is_file():
            raise PromotionPathError(f"managed member is missing: {relative.as_posix()}")
        result[relative.as_posix()] = item.read_bytes()
    return result


def _tree_digest(members: Mapping[str, bytes]) -> str:
    identities = [
        {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        for path, data in sorted(members.items())
    ]
    return canonical_digest(identities)


@contextmanager
def open_grounding_snapshot(
    campaign_dir: Path, requested: Sequence[str] | None = None
) -> Iterator[GroundingSnapshot]:
    """Capture immutable member bytes under one shared campaign lock."""
    root = Path(campaign_dir).absolute()
    try:
        with authority_lock(root, exclusive=False, create=False):
            layout = inspect_layout(root)
            members = _collect_members(layout.live_dir, requested)
            published = layout.live_dir.parent / "published"
            edited = False
            if published.is_dir():
                for relative, data in members.items():
                    peer = published.joinpath(*PurePosixPath(relative).parts)
                    if not peer.is_file() or peer.read_bytes() != data:
                        edited = True
                        break
            snapshot = GroundingSnapshot(
                layout.generation_id,
                _tree_digest(members),
                MappingProxyType(dict(members)),
                edited,
            )
    except AuthorityError as exc:
        if exc.code == "AUTH_LOCK_MISSING":
            raise PromotionMigrationRequired(campaign_dir=root) from exc
        raise
    yield snapshot


def refuse_managed_write(path: Path, campaign_dir: Path, *, draft_hint: str) -> None:
    """Refuse legacy per-file writers that target one managed member.

    An absent baseline is a migrated layout: its alias and ``current`` paths
    are managed members that have not been published, so a generated write to
    them refuses exactly like one to a published member. Only a genuinely
    unmigrated campaign (``PromotionMigrationRequired`` proper) keeps its loose
    files writable.
    """
    target = Path(os.path.normpath(Path(path).absolute()))
    roots = [Path(campaign_dir).resolve()]
    roots.extend(parent.parent for parent in target.parents if parent.name == "docs")
    for root in dict.fromkeys(roots):
        if not (root / GROUNDING_RELATIVE).exists():
            continue
        try:
            managed = classify_managed_path(target, root, allow_unpublished=True)
        except GroundingNotPublished:
            raise
        except PromotionMigrationRequired:
            continue
        if managed is not None:
            raise PromotionPathError(
                f"managed grounding member {managed} cannot be replaced individually; "
                f"write a draft at {draft_hint}"
            )


def write_managed_member(
    campaign_dir: Path,
    relative_path: str,
    data: bytes,
    *,
    expected_sha256: str | None = None,
) -> str:
    """Replace one editable live member under the shared exclusive lock."""
    import tempfile

    root = Path(campaign_dir).resolve()
    relative = _contained_relative(relative_path)
    with authority_lock(root, exclusive=True, create=False):
        layout = inspect_layout(root)
        target = layout.live_dir.joinpath(*relative.parts)
        _raw_no_symlink(target, layout.live_dir)
        if not target.is_file():
            raise PromotionPathError(f"managed member is missing: {relative_path}")
        before = target.read_bytes()
        before_sha = hashlib.sha256(before).hexdigest()
        if expected_sha256 is not None and before_sha != expected_sha256:
            raise PromotionPathError(f"managed member changed before write: {relative_path}")
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return hashlib.sha256(data).hexdigest()
