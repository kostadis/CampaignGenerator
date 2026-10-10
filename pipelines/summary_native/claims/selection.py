"""Pure source closure and owner-only confirmed-selection persistence."""

from __future__ import annotations

import hashlib
import errno
import os
import secrets
import stat
import json
import re
from datetime import datetime
from pathlib import Path

from pipelines.summary_native.claims.models import (
    AuthorityClass, SelectedChunk, SourceEntry, SourceKind, SourceRole, SourceSelection,
)
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.models import BundleSelection, ContentIdentity
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest
from pipelines.summary_native.authority import NoteRecord, RulingRecord, load_ledger


_CITATION = re.compile(r"\[ch\s+(\d+)\s*/\s*([^\]]+)\]", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def bundle_source_digest(bundle: BundleSelection) -> str:
    """Review-independent source bundle identity used across the claims DAG."""
    return canonical_digest(bundle, exclude_fields=frozenset({"review_id"}))


def _identity_rows(bundle: BundleSelection):
    for item in bundle.documents:
        yield item, SourceKind.DRAFT, SourceRole.CLAIM, AuthorityClass.OPEN, "mapping_evidence", "whole-file", (), {}, "gm"
    yield bundle.timeline, SourceKind.SUPPORT, SourceRole.CONTEXT, AuthorityClass.TABLE, "mapping_evidence", "whole-file", (), {}, "gm"
    for item in bundle.references:
        yield item, SourceKind.SUPPORT, SourceRole.COUNTERPART, AuthorityClass.TABLE, "mapping_evidence", "whole-file", (), {}, "gm"
    for item in bundle.retained_records:
        yield item, SourceKind.RUN_RECORD, SourceRole.CONTEXT, AuthorityClass.OPEN, "context_only", "whole-file", (), {}, "gm"
    for item in bundle.dependencies:
        classification = AuthorityClass.CANON if item.path == "docs/authority.yaml" else AuthorityClass.OPEN
        applicability = "fact_authority" if classification is AuthorityClass.CANON else "context_only"
        yield item, SourceKind.SUPPORT, SourceRole.CONTEXT, classification, applicability, "whole-file", (), {}, "gm"
    yield bundle.config_identity, SourceKind.SUPPORT, SourceRole.CONTEXT, AuthorityClass.OPEN, "context_only", "whole-file", (), {}, "gm"


def _identity(root: Path, path: Path) -> ContentIdentity:
    data = path.read_bytes()
    return ContentIdentity(path=path.relative_to(root).as_posix(), sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def _audience_label(grants: frozenset[str]) -> str:
    if "players" in grants:
        return "players"
    if "characters" in grants:
        return "characters"
    return "gm"


def _discovered_rows(root: Path, bundle: BundleSelection):
    """Resolve only explicit citation and active authority links, never filename recency."""
    seen: set[tuple[str, str, str]] = set()
    linked_paths: set[str] = {item.path for item, *_ in _identity_rows(bundle)}
    manifest_path = root / bundle.selected_range.out_root / f"ch{bundle.selected_range.since:03d}-{bundle.selected_range.until:03d}" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    chapters = {
        int(item["chapter"]): item for item in manifest.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("chapter"), int) and isinstance(item.get("path"), str)
    }
    queue = [item for item, *_rest in _identity_rows(bundle)]
    queued = {item.path for item in queue}
    discovered: list[tuple] = []
    while queue:
        identity = queue.pop(0)
        try:
            text = (root / identity.path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for match in _CITATION.finditer(text):
            chapter = int(match.group(1))
            entry = chapters.get(chapter)
            if not entry:
                raise PromotionError(f"cited chapter {chapter} is absent from the selected corpus inventory", code="CLAIMS_SOURCE_MISSING")
            path = root / entry["path"]
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
                raise PromotionError("cited corpus source is stale or missing", code="CLAIMS_SOURCE_STALE")
            key = (entry["path"], f"ch {chapter} / {match.group(2).strip()}", "citation")
            if key in seen:
                continue
            seen.add(key)
            found_identity = _identity(root, path)
            row = (found_identity, SourceKind.SUMMARY, SourceRole.COUNTERPART,
                   AuthorityClass.TABLE, "mapping_evidence", key[1], (), {}, "gm")
            discovered.append(row)
            linked_paths.add(found_identity.path)
            if found_identity.path not in queued:
                queued.add(found_identity.path)
                queue.append(found_identity)
        for match in _MARKDOWN_LINK.finditer(text):
            raw_link = match.group(1).split("#", 1)[0]
            if not raw_link or "://" in raw_link:
                continue
            candidate = ((root / identity.path).parent / raw_link).resolve()
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError as exc:
                raise PromotionError("linked claim source escapes campaign", code="CLAIMS_SELECTION_INVALID") from exc
            if not candidate.is_file():
                raise PromotionError(f"linked claim source is missing: {relative}", code="CLAIMS_SOURCE_MISSING")
            linked_paths.add(relative)
            if relative not in queued:
                found_identity = _identity(root, candidate)
                queued.add(relative)
                queue.append(found_identity)
                discovered.append((found_identity, SourceKind.NOTE, SourceRole.CONTEXT,
                                   AuthorityClass.OPEN, "mapping_evidence", f"link:{raw_link}", (), {}, "gm"))

    ledger = load_ledger(root, required=False)
    if ledger is None:
        return discovered, []
    by_id = {record.id: record for record in ledger.records}
    relevant_ids = {
        record.id for record in ledger.records
        if isinstance(record, (NoteRecord, RulingRecord))
        and (record.source.resolved_path or record.source.path) in linked_paths
    }
    changed = True
    while changed:
        changed = False
        for record in ledger.records:
            if record.supersedes in relevant_ids and record.id not in relevant_ids:
                relevant_ids.add(record.id)
                changed = True
    ambiguities: list[str] = []
    ledger_identity = _identity(root, root / "docs/authority.yaml")
    for record in ledger.records:
        active = (isinstance(record, NoteRecord) and record.status == "active") or (
            isinstance(record, RulingRecord) and record.status in {"applied", "withdrawal_requested", "reversal_proposed"}
        )
        if not active or record.id not in relevant_ids or not record.audience.allows(bundle.audience):
            continue
        if not (record.projections & {item.document_id.value for item in bundle.documents}):
            continue
        source_path = record.source.resolved_path or record.source.path
        raw = Path(source_path)
        path = raw if raw.is_absolute() else root / raw
        if not path.is_file():
            raise PromotionError(f"authority source is missing: {source_path}", code="CLAIMS_SOURCE_MISSING")
        identity = _identity(root, path.resolve())
        classification = AuthorityClass.CANON if record.classification.value == "RULED" else AuthorityClass(record.classification.value)
        applicable = classification in {AuthorityClass.CANON, AuthorityClass.TABLE}
        if classification in {AuthorityClass.PREP, AuthorityClass.OVERLAY, AuthorityClass.OPEN}:
            ambiguities.append(f"Confirm applicability of {record.id} ({classification.value}) for {bundle.audience} through chapter {bundle.selected_range.until}.")
        key = (ledger_identity.path, f"authority-record:{record.id}:r{record.revision}", record.id)
        if key in seen:
            continue
        seen.add(key)
        record_digest = hashlib.sha256(canonical_bytes(record)).hexdigest()
        # The exact authority record lives in the ledger.  Its authored Markdown
        # source remains in the closure independently, but is never presented as
        # though canonical record JSON were a byte span from that Markdown file.
        discovered.append((ledger_identity, SourceKind.AUTHORITY, SourceRole.AUTHORITY, classification,
               "fact_authority" if applicable else "mapping_evidence", key[1],
               (record.id,), {record.id: record_digest}, _audience_label(record.audience.grants)))
    return discovered, ambiguities


def _read_bound(root: Path, identity: ContentIdentity) -> bytes:
    data = _read_private_regular(root, Path(identity.path), code="CLAIMS_SOURCE_INVALID")
    path = root / identity.path
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise PromotionError("claim source escapes campaign", code="CLAIMS_SELECTION_INVALID") from exc
    if hashlib.sha256(data).hexdigest() != identity.sha256 or len(data) != identity.size:
        raise PromotionError(f"claim source changed: {identity.path}", code="CLAIMS_SOURCE_STALE")
    return data


def _read_private_regular(root: Path, relative: Path, *, code: str) -> bytes:
    """Read a campaign file through no-follow handles and reject special files."""
    root = root.resolve()
    if relative.is_absolute() or ".." in relative.parts:
        raise PromotionError("private claim path escapes campaign", code=code)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(root, directory_flags)
    try:
        for component in relative.parts[:-1]:
            child = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd); directory_fd = child
        descriptor = os.open(
            relative.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_fd,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise PromotionError("private claim source is not a regular file", code="CLAIMS_PATH_INVALID")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                return stream.read()
        finally:
            if descriptor >= 0: os.close(descriptor)
    except OSError as exc:
        error_code = code if exc.errno == errno.ENOENT else "CLAIMS_PATH_INVALID"
        message = ("private claim source is missing" if exc.errno == errno.ENOENT
                   else "private claim source contains a symlink or unsafe component")
        raise PromotionError(message, code=error_code) from exc
    finally:
        os.close(directory_fd)


def mandatory_source_closure(
    campaign_dir: Path, bundle: BundleSelection, *, effective_horizon: str,
    audience: str, rule_versions: tuple[str, ...], unresolved_scope: tuple[str, ...] = (),
    linked_sources: tuple[tuple[ContentIdentity, SourceKind, SourceRole, tuple[str, ...]], ...] = (),
) -> SourceSelection:
    """Materialize every bundle dependency; never infer that an empty list means all."""
    root = Path(campaign_dir).resolve()
    sources: list[SourceEntry] = []
    chunks: list[SelectedChunk] = []
    discovered_rows, discovered_ambiguities = _discovered_rows(root, bundle)
    mandatory_rows = [*_identity_rows(bundle), *discovered_rows]
    for index, (identity, kind, role, authority_class, applicability, anchor, authority_ids, authority_digests, source_audience) in enumerate(mandatory_rows, 1):
        if kind is SourceKind.AUTHORITY and authority_ids:
            # The ledger is append-only mutable. load_ledger above validates its
            # complete chain; selection identity binds only the exact chosen
            # semantic records so unrelated decisions/signoffs cannot stale it.
            data = canonical_bytes({key: authority_digests[key] for key in sorted(authority_ids)})
            bound_sha = hashlib.sha256(data).hexdigest()
        else:
            data = _read_bound(root, identity)
            bound_sha = identity.sha256
        source_id = f"source-{index:04d}-{bound_sha[:12]}"
        digest = hashlib.sha256(data).hexdigest()
        sources.append(SourceEntry(
            source_id=source_id, path=identity.path, sha256=bound_sha,
            source_kind=kind, role=role, source_audience=source_audience, authority_class=authority_class,
            applicability=applicability, anchor=anchor, excerpt_sha256=digest,
            context_sha256=digest, authority_record_ids=authority_ids,
            authority_record_digests=authority_digests, required=True,
        ))
    suggestions: list[SourceEntry] = []
    for index, (identity, kind, role, authority_ids) in enumerate(linked_sources, 1):
        data = _read_bound(root, identity)
        digest = hashlib.sha256(data).hexdigest()
        suggestions.append(SourceEntry(
            source_id=f"suggestion-{index:04d}-{digest[:12]}", path=identity.path,
            sha256=identity.sha256, source_kind=kind, role=role, source_audience="gm",
            authority_class=AuthorityClass.CANON if authority_ids else AuthorityClass.OPEN,
            applicability="fact_authority" if authority_ids else "context_only", anchor="linked-source",
            excerpt_sha256=digest, context_sha256=digest,
            authority_record_ids=authority_ids, required=False,
        ))
    values = dict(
        campaign_id=bundle.campaign_id, bundle_digest=bundle_source_digest(bundle),
        out_root=bundle.selected_range.out_root,
        range_since=bundle.selected_range.since, range_until=bundle.selected_range.until,
        effective_horizon=effective_horizon, audience=audience, sources=tuple(sources),
        suggested_sources=tuple(suggestions),
        chunks=tuple(chunks), unresolved_scope=tuple((*unresolved_scope, *sorted(set(discovered_ambiguities)))),
        rule_versions=tuple(sorted(rule_versions)), selection_digest="0" * 64,
    )
    provisional = SourceSelection.model_construct(**values)
    values["selection_digest"] = canonical_digest(
        provisional, exclude_fields=frozenset({"selection_digest", "confirmed_by", "confirmed_at", "confirmed_digest"})
    )
    return SourceSelection.model_validate(values)


def confirm_selection(selection: SourceSelection, *, reviewer: str, confirmed_at: datetime) -> SourceSelection:
    if selection.unresolved_scope:
        raise PromotionError("selection has unresolved scope choices", code="CLAIMS_SCOPE_UNRESOLVED")
    values = selection.model_dump(mode="python")
    values.update(confirmed_by=reviewer, confirmed_at=confirmed_at, confirmed_digest="0" * 64)
    provisional = SourceSelection.model_construct(**values)
    values["confirmed_digest"] = canonical_digest(provisional, exclude_fields=frozenset({"confirmed_digest"}))
    return SourceSelection.model_validate(values)


def select_whole_source_chunks(
    campaign_dir: Path, selection: SourceSelection, source_ids: tuple[str, ...]
) -> SourceSelection:
    """Materialize an explicit whole-source chunk choice; an empty choice stays empty."""
    root = Path(campaign_dir).resolve()
    by_id = {item.source_id: item for item in selection.sources}
    chunks: list[SelectedChunk] = []
    for index, source_id in enumerate(source_ids, 1):
        if source_id not in by_id:
            raise PromotionError("selected chunk source is not in the closure", code="CLAIMS_SELECTION_INVALID")
        source = by_id[source_id]
        data = _read_bound(root, ContentIdentity(path=source.path, sha256=source.sha256, size=(root / source.path).stat().st_size))
        if not data:
            continue
        chunks.append(SelectedChunk(
            chunk_id=f"chunk-{index:04d}-{source.sha256[:12]}", source_id=source_id,
            start_byte=0, end_byte=len(data), sha256=hashlib.sha256(data).hexdigest(),
            locator=f"bytes:0-{len(data)}",
        ))
    values = selection.model_dump(mode="python")
    values.update(chunks=tuple(chunks), confirmed_by=None, confirmed_at=None, confirmed_digest=None, selection_digest="0" * 64)
    provisional = SourceSelection.model_construct(**values)
    values["selection_digest"] = canonical_digest(
        provisional, exclude_fields=frozenset({"selection_digest", "confirmed_by", "confirmed_at", "confirmed_digest"})
    )
    return SourceSelection.model_validate(values)


def selection_path(campaign_dir: Path, selection: SourceSelection) -> Path:
    range_dir = f"ch{selection.range_since:03d}-{selection.range_until:03d}"
    return Path(campaign_dir).resolve() / selection.out_root / range_dir / "state/promotion/selections" / f"{selection.selection_digest}.json"


def validate_selection_against_bundle(campaign_dir: Path, selection: SourceSelection, bundle: BundleSelection) -> None:
    if selection.campaign_id != bundle.campaign_id or selection.bundle_digest != bundle_source_digest(bundle):
        raise PromotionError("selection belongs to another campaign or bundle", code="CLAIMS_SELECTION_INVALID")
    expected = mandatory_source_closure(
        campaign_dir, bundle, effective_horizon=selection.effective_horizon,
        audience=selection.audience, rule_versions=selection.rule_versions,
        unresolved_scope=selection.unresolved_scope,
    )
    expected_required = {canonical_bytes(item) for item in expected.sources if item.required}
    actual_required = {canonical_bytes(item) for item in selection.sources if item.required}
    if actual_required != expected_required:
        raise PromotionError("selection omits or changes mandatory sources", code="CLAIMS_SOURCE_MISSING")


def save_confirmed_selection(campaign_dir: Path, selection: SourceSelection) -> Path:
    if selection.confirmed_digest is None:
        raise PromotionError("selection must be explicitly confirmed", code="CLAIMS_SELECTION_UNCONFIRMED")
    path = selection_path(campaign_dir, selection)
    data = canonical_bytes(selection)
    _write_owner_only(Path(campaign_dir).resolve(), path, data, conflict_code="CLAIMS_SELECTION_CONFLICT")
    return path


def existing_confirmation(
    campaign_dir: Path, selection: SourceSelection, *, reviewer: str
) -> SourceSelection | None:
    """Return an exact prior confirmation so UI retries remain idempotent."""
    root = Path(campaign_dir).resolve()
    path = selection_path(root, selection)
    relative = path.relative_to(root)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(root, flags)
        try:
            for component in relative.parts[:-1]:
                child = os.open(component, flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = child
            descriptor = os.open(
                relative.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
                dir_fd=directory_fd,
            )
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise PromotionError("saved selection is not a regular file", code="CLAIMS_PATH_INVALID")
            with os.fdopen(descriptor, "rb") as stream:
                saved = SourceSelection.model_validate_json(stream.read())
        finally:
            os.close(directory_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PromotionError("saved selection path is unsafe", code="CLAIMS_PATH_INVALID") from exc
    if saved.selection_digest != selection.selection_digest or saved.confirmed_by != reviewer:
        return None
    return saved


def _write_owner_only(root: Path, path: Path, data: bytes, *, conflict_code: str) -> None:
    """Write immutable private evidence through component-wise no-follow handles."""
    root = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PromotionError("private claim path escapes campaign", code="CLAIMS_PATH_INVALID") from exc
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(root, flags)
    try:
        for component in relative.parts[:-1]:
            try:
                child_fd = os.open(component, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=directory_fd)
                except FileExistsError:
                    pass
                child_fd = os.open(component, flags, dir_fd=directory_fd)
            except OSError as exc:
                raise PromotionError("private claim path contains an unsafe component", code="CLAIMS_PATH_INVALID") from exc
            os.close(directory_fd)
            directory_fd = child_fd
        os.fchmod(directory_fd, 0o700)
        try:
            existing = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode):
                raise PromotionError("private claim record cannot be a symlink", code="CLAIMS_PATH_INVALID")
            fd = os.open(relative.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "rb") as stream:
                if stream.read() != data:
                    raise PromotionError("private claim identity conflicts with saved bytes", code=conflict_code)
            return
        temporary = f".{relative.name}.{secrets.token_hex(8)}"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=directory_fd)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # link(2) is an atomic no-replace publication primitive.  A
                # competing writer can never silently replace committed bytes.
                os.link(
                    temporary, relative.name, src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd, follow_symlinks=False,
                )
            except FileExistsError:
                committed_fd = os.open(
                    relative.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                with os.fdopen(committed_fd, "rb") as stream:
                    if stream.read() != data:
                        raise PromotionError(
                            "private claim identity conflicts with saved bytes", code=conflict_code
                        )
            os.fsync(directory_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory_fd)
