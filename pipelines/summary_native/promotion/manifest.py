"""Pure enumeration of one complete candidate grounding bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from pipelines.summary_native import schema
from pipelines.summary_native.promotion.errors import PromotionPathError
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.models import (
    BundleSelection,
    ContentIdentity,
    DocumentMember,
    GroundingDocument,
    PathIdentity,
    RangeSelection,
)
from pipelines.summary_native.review.models import canonical_digest


_RECORD = re.compile(r"record:\s*([^ |]+)")


def _identity(root: Path, path: Path) -> ContentIdentity:
    canonical_root = root.resolve()
    lexical = path.absolute()
    try:
        lexical_relative = lexical.relative_to(root.absolute())
    except ValueError as exc:
        raise PromotionPathError(f"bundle input escapes campaign: {path}") from exc
    cursor = root.absolute()
    for part in lexical_relative.parts:
        if part == "..":
            cursor = cursor.parent
            continue
        cursor = cursor / part
        if cursor.is_symlink():
            raise PromotionPathError(f"bundle input contains symlink: {cursor}")
    resolved = lexical.resolve()
    if not resolved.is_file():
        raise PromotionPathError(f"bundle input must be a regular file: {path}")
    try:
        relative = resolved.relative_to(canonical_root).as_posix()
    except ValueError as exc:
        raise PromotionPathError(f"bundle input escapes campaign: {path}") from exc
    data = resolved.read_bytes()
    return ContentIdentity(path=relative, sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def _tree(root: Path, directory: Path) -> tuple[ContentIdentity, ...]:
    if directory.is_symlink() or not directory.is_dir():
        raise PromotionPathError(f"required bundle directory is missing or unsafe: {directory}")
    values: list[ContentIdentity] = []
    casefolded: set[str] = set()
    for entry in sorted(directory.rglob("*")):
        if entry.is_symlink():
            raise PromotionPathError(f"bundle tree contains symlink: {entry}")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise PromotionPathError(f"bundle tree contains special file: {entry}")
        identity = _identity(root, entry)
        folded = identity.path.casefold()
        if folded in casefolded:
            raise PromotionPathError(f"bundle paths collide by case: {identity.path}")
        casefolded.add(folded)
        values.append(identity)
    if not values:
        raise PromotionPathError(f"required bundle directory is empty: {directory}")
    return tuple(values)


def _path_identity(root: Path, relative: str) -> PathIdentity:
    path = root / relative
    if path.is_symlink():
        return PathIdentity(path=relative, kind="symlink", target=os.readlink(path))
    if not path.exists():
        return PathIdentity(path=relative, kind="absent")
    if path.is_file():
        return PathIdentity(path=relative, kind="file", sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if path.is_dir():
        members = []
        for member in sorted(path.rglob("*")):
            if member.is_symlink() or (not member.is_file() and not member.is_dir()):
                raise PromotionPathError(f"managed alias tree contains unsafe member: {member}")
            if member.is_file():
                members.append((member.relative_to(path).as_posix(), hashlib.sha256(member.read_bytes()).hexdigest()))
        return PathIdentity(path=relative, kind="directory", sha256=canonical_digest(members))
    raise PromotionPathError(f"managed alias is an unsupported filesystem object: {path}")


def _record_and_dependencies(root: Path, draft: Path, state_dir: Path) -> tuple[ContentIdentity, tuple[ContentIdentity, ...]]:
    text = draft.read_text(encoding="utf-8")
    match = _RECORD.search(text)
    if not match:
        raise PromotionPathError(f"draft has no run record pointer: {draft}")
    lexical = state_dir / match.group(1)
    try:
        lexical.relative_to(root)
    except ValueError as exc:
        raise PromotionPathError(f"run record escapes campaign: {lexical}") from exc
    record = _identity(root, lexical)
    try:
        payload = json.loads(lexical.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PromotionPathError(f"invalid run record: {lexical}") from exc
    dependencies: dict[str, ContentIdentity] = {}
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        raise PromotionPathError(f"run record has no typed inputs map: {lexical}")
    range_dir = state_dir.parent

    def bind(path: Path, expected: object, label: str) -> None:
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise PromotionPathError(f"run record has no valid {label} digest: {lexical}")
        identity = _identity(root, path)
        if identity.sha256 != expected:
            raise PromotionPathError(f"run record {label} dependency is stale: {identity.path}")
        dependencies[identity.path] = identity

    corpus_manifest_path = range_dir / "manifest.json"
    bind(corpus_manifest_path, inputs.get("corpus_manifest_sha256"), "corpus manifest")
    try:
        corpus_manifest = json.loads(corpus_manifest_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise PromotionPathError("corpus manifest is unreadable") from exc
    corpus_sources = corpus_manifest.get("files")
    if not isinstance(corpus_sources, list) or not corpus_sources:
        raise PromotionPathError("corpus manifest has no source-summary custody")
    for source in corpus_sources:
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            raise PromotionPathError("corpus manifest source entry is malformed")
        source_path = Path(source["path"])
        if source_path.is_absolute():
            raise PromotionPathError("external corpus sources require an explicit bounded source map")
        bind(root / source_path, source.get("sha256"), "corpus source")
    bind(state_dir / "notes/manifest.json", inputs.get("notes_manifest_sha256"), "notes manifest")
    bind(root / "docs/entity_registry.yaml", inputs.get("registry_sha256"), "registry")
    bind(root / "config/players.yaml", inputs.get("players_sha256"), "players")

    if "thread_registry_sha256" in inputs:
        bind(root / "docs/thread_registry.yaml", inputs.get("thread_registry_sha256"), "thread registry")

    def bind_entries(value: object, label: str) -> None:
        if not isinstance(value, list):
            raise PromotionPathError(f"run record {label} must be a list")
        for entry in value:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise PromotionPathError(f"run record {label} entry is malformed")
            bind(root / entry["path"], entry.get("sha256"), label)

    bind_entries(inputs.get("track_files", []), "track file")
    for group_name in ("party_config", "planning_config"):
        group = inputs.get(group_name)
        if group is None:
            continue
        if not isinstance(group, dict):
            raise PromotionPathError(f"run record {group_name} is malformed")
        group_path = group.get("path")
        if group_path is not None:
            if not isinstance(group_path, str):
                raise PromotionPathError(f"run record {group_name} path is malformed")
            bind(root / group_path, group.get("sha256"), group_name)
        bind_entries(group.get("files", []), f"{group_name} file")

    authority = inputs.get("authority_manifest")
    if authority is not None:
        if not isinstance(authority, dict):
            raise PromotionPathError("run record authority manifest is malformed")
        # The run record retains the original full-ledger custody digest. Review
        # decisions legitimately append to that ledger, so requiring the live
        # ledger to retain this digest would make sign-off itself stale every
        # draft. Current relevant authority is rebound by the review/check gate.
        ledger_digest = authority.get("ledger_sha256")
        if not isinstance(ledger_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", ledger_digest):
            raise PromotionPathError("run record has no valid authority ledger custody digest")
        source_entries: list[object] = []
        records = authority.get("records", [])
        support_sources = authority.get("support_sources", [])
        if not isinstance(records, list) or not isinstance(support_sources, list):
            raise PromotionPathError("run record authority sources are malformed")
        source_entries.extend(records)
        source_entries.extend(support_sources)
        for entry in source_entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("source", entry.get("path")), str):
                raise PromotionPathError("run record authority source entry is malformed")
            source = entry.get("source", entry.get("path"))
            digest = entry.get("source_sha256", entry.get("sha256"))
            bind(root / source, digest, "authority source")
    return record, tuple(sorted(dependencies.values(), key=lambda item: item.path))


def build_bundle_selection(
    campaign_dir: Path,
    *,
    out_root: str,
    since: int,
    until: int,
    campaign_id: str,
    review_id: str,
    rule_versions: tuple[str, ...],
    config_path: Path | None = None,
) -> BundleSelection:
    root = Path(campaign_dir).absolute()
    if any(part == ".." for part in Path(out_root).parts):
        raise PromotionPathError("output root traversal is not allowed")
    selected_range = RangeSelection(since=since, until=until, out_root=Path(out_root).as_posix())
    range_dir = root / out_root / f"ch{since:03d}-{until:03d}"
    drafts = schema.draft_dir(range_dir, "world_state")
    documents: list[DocumentMember] = []
    retained: list[ContentIdentity] = []
    dependencies: dict[str, ContentIdentity] = {}
    for document in GroundingDocument:
        draft = drafts / f"{document.value}.draft.md"
        base = _identity(root, draft)
        header = draft.read_text(encoding="utf-8")[:2048]
        expected_range = f"range: ch{since:03d}-{until:03d}"
        if expected_range not in header:
            raise PromotionError(
                f"draft {document.value} does not declare {expected_range}",
                code="PROMOTION_MIXED_RANGE",
            )
        documents.append(DocumentMember(document_id=document, **base.model_dump()))
        record, bound = _record_and_dependencies(root, draft, drafts.parent)
        retained.append(record)
        for item in bound:
            dependencies[item.path] = item
    timeline = _identity(root, drafts / schema.TIMELINE_FILE)
    references = _tree(root, drafts / "reference")
    config = _identity(root, config_path or (root / "config/config.yaml"))
    aliases = tuple(
        _path_identity(root, relative)
        for relative in (
            "docs/world_state.md", "docs/campaign_state.md", "docs/party.md",
            "docs/planning.md", "docs/canon_events_timeline.md", "docs/reference",
        )
    )
    return BundleSelection(
        campaign_id=campaign_id,
        selected_range=selected_range,
        documents=tuple(documents),
        timeline=timeline,
        references=references,
        retained_records=tuple(sorted(retained, key=lambda item: item.path)),
        dependencies=tuple(sorted(dependencies.values(), key=lambda item: item.path)),
        config_identity=config,
        alias_identities=aliases,
        review_id=review_id,
        rule_versions=tuple(sorted(rule_versions)),
    )
