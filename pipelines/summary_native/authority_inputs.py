"""Audience-safe authority input snapshots and explicit planning selectors."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pipelines.summary_native.authority import AuthorityError, AuthorityLedger, AuthorityRecord, Classification, DOCUMENT_ANCHOR, NoteRecord, POLICY_VERSION, Projection, SCHEMA_VERSION, canonicalize, detect_conflicts, ledger_digest, load_ledger, record_metadata_digest, validate_audience_target, validate_record_identity
from pipelines.summary_native.authority_apply import authority_lock, require_no_pending_transaction



@dataclass(frozen=True)
class SelectionMember:
    selector_id: str
    authored_path: str
    resolved_path: str
    external: bool
    record_ids: tuple[str, ...]
    digest: str
    reason: str


def require_conflict_free(ledger: AuthorityLedger, *, projection: Projection,
                          record_ids: set[str] | frozenset[str]) -> None:
    """Refuse a projection only when both compared records feed this run.

    A conflict outside the selected planning scope or chapter-effective input
    set is recorded for review but cannot block an unrelated synthesis call.
    """
    scope = frozenset(record_ids)
    blocking = [
        conflict for conflict in detect_conflicts(ledger)
        if conflict.status == "open"
        and conflict.basis in {"structured_value", "source_anchor"}
        and projection in conflict.projections
        and conflict.record_ids.issubset(scope)
    ]
    if blocking:
        raise AuthorityError(
            "AUTH_CONFLICT: unresolved structured authority conflict blocks this projection: "
            + ", ".join(conflict.id for conflict in blocking),
            "AUTH_CONFLICT",
        )


@dataclass(frozen=True)
class SelectionSnapshot:
    selectors_digest: str
    members: tuple[SelectionMember, ...]
    membership_digest: str

    @property
    def digest(self) -> str:
        """The review token: selector expression *and* materialized membership."""
        return _digest({"selectors": self.selectors_digest, "membership": self.membership_digest})


@dataclass(frozen=True)
class FilteredEvidence:
    """Digest-bound authority sections visible to one target before prompt assembly."""
    audience: str
    sections: tuple[tuple[str, str, bytes], ...]
    payload_digest: str

    @property
    def text(self) -> bytes:
        """The complete, already-authorized source payload.

        Callers deliberately get no way to recover a neighbouring source span:
        the only bytes exposed here are the exact anchored sections selected
        by the authority snapshot.
        """
        return b"\n\n".join(section for _, _, section in self.sections)


@dataclass(frozen=True)
class SupportSource:
    """One complete, digest-bound deterministic input admitted to a view."""

    path: str
    data: bytes
    source_sha256: str
    record_ids: tuple[str, ...]


@dataclass(frozen=True)
class SupportSnapshot:
    """The only deterministic campaign files a non-GM synth may consume.

    A support file must be represented by a record whose anchored span is the
    complete file.  Config and registry parsers need a complete document; a
    partial grant is useful as prose evidence but cannot safely be widened into
    a parser input.
    """

    audience: str
    sources: tuple[SupportSource, ...]
    manifest: dict

    def bytes_for(self, path: Path) -> bytes:
        wanted = str(Path(path).resolve())
        for source in self.sources:
            if source.path == wanted:
                return source.data
        raise AuthorityError("authorized support is incomplete for this audience")

    def text_for(self, path: Path) -> str:
        try:
            return self.bytes_for(path).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuthorityError("authorized support is unreadable for this audience") from exc

    def has(self, path: Path | None) -> bool:
        return path is not None and any(source.path == str(Path(path).resolve()) for source in self.sources)

    def paths_under(self, directory: Path, pattern: str = "*") -> tuple[Path, ...]:
        base = Path(directory).resolve()
        return tuple(Path(source.path) for source in self.sources
                     if Path(source.path).parent == base and Path(source.path).match(pattern))


def support_snapshot(campaign_dir: Path, *, audience: str, required: list[Path],
                     selection: SelectionSnapshot | None = None, since: int | None = None,
                     until: int | None = None) -> SupportSnapshot:
    """Capture all required deterministic inputs while one shared lock is held.

    This deliberately does not expose an on-disk path for the original source.
    Consumers receive bytes from this object, so a file changed after the
    snapshot cannot alter a prompt or a deterministic renderer mid-run.
    """
    root = Path(campaign_dir).resolve()
    try:
        wanted = {str(Path(path).resolve()) for path in required if path is not None}
    except OSError as exc:
        raise AuthorityError("authorized support is incomplete for this audience") from exc
    with authority_lock(root, exclusive=False):
        require_no_pending_transaction(root)
        ledger = load_ledger(root)
        validate_audience_target(root, audience)
        sources: dict[str, list[tuple[AuthorityRecord, bytes]]] = {}
        for record in resolve_anchored_records(ledger, audience=audience, since=since, until=until):
            validate_record_identity(root, record)
            source_path = Path(record.source.path)
            source_path = source_path if source_path.is_absolute() else root / source_path
            try:
                data = source_path.read_bytes()
                section = resolve_anchor_span(data, record.source.anchor)
            except (OSError, AuthorityError) as exc:
                raise AuthorityError("authorized support is incomplete for this audience") from exc
            expected = getattr(record, "content_digest", None)
            if expected and hashlib.sha256(section).hexdigest() != expected:
                raise AuthorityError("authorized support is incomplete for this audience")
            # Deterministic loaders cannot be given an anchor plus neighbouring
            # bytes.  Accept the source only when the grant covers exactly it.
            if section == data:
                sources.setdefault(str(source_path.resolve()), []).append((record, data))
        if not wanted.issubset(sources):
            raise AuthorityError("authorized support is incomplete for this audience")
        captured = tuple(
            SupportSource(path, values[0][1], hashlib.sha256(values[0][1]).hexdigest(),
                          tuple(sorted(record.id for record, _ in values)))
            for path, values in sorted(sources.items())
        )
        # Existing manifest fields remain the authority freshness contract;
        # support membership adds the bytes used by deterministic adapters.
        manifest = build_manifest(root, ledger, audience=audience, selection=selection, since=since, until=until)
        manifest["support_sources"] = [
            {"path": source.path, "sha256": source.source_sha256, "records": list(source.record_ids)}
            for source in captured if source.path in wanted
        ]
        manifest["support_sha256"] = _digest(manifest["support_sources"])
    return SupportSnapshot(audience, captured, manifest)


def filtered_evidence(campaign_dir: Path, ledger: AuthorityLedger, *, audience: str,
                      since: int | None = None, until: int | None = None) -> FilteredEvidence:
    """Read only complete anchored sections explicitly granted to ``audience``."""
    root = Path(campaign_dir).resolve()
    validate_audience_target(root, audience)
    sections = []
    for record in resolve_anchored_records(ledger, audience=audience, since=since, until=until):
        validate_record_identity(root, record)
        source = Path(record.source.path)
        source = source if source.is_absolute() else root / source
        try:
            section = resolve_anchor_span(source.read_bytes(), record.source.anchor)
        except OSError as exc:
            raise AuthorityError(f"authority source is missing or unreadable: {record.source.path}") from exc
        expected = getattr(record, "content_digest", None)
        if expected and hashlib.sha256(section).hexdigest() != expected:
            raise AuthorityError(f"authority source section digest changed for {record.id}", "AUTH_STALE")
        sections.append((record.id, f"{record.source.path}#{record.source.anchor}", section))
    sections.sort(key=lambda item: item[:2])
    payload = [{"id": ident, "source": source, "sha256": hashlib.sha256(data).hexdigest()} for ident, source, data in sections]
    return FilteredEvidence(audience, tuple(sections), _digest(payload))


def audience_snapshot(campaign_dir: Path, *, audience: str, selection: SelectionSnapshot | None = None,
                      since: int | None = None, until: int | None = None) -> tuple[AuthorityLedger, FilteredEvidence, dict]:
    """Read ledger, authorized source bytes, and manifest under one reader lock."""
    with authority_lock(campaign_dir, exclusive=False):
        require_no_pending_transaction(campaign_dir)
        ledger = load_ledger(campaign_dir)
        evidence = filtered_evidence(campaign_dir, ledger, audience=audience, since=since, until=until)
        manifest = build_manifest(campaign_dir, ledger, audience=audience, selection=selection, since=since, until=until)
    return ledger, evidence, manifest


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(canonicalize(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def resolve_selection(campaign_dir: Path, selectors) -> SelectionSnapshot:
    """Materialize configured exact/glob selectors; empty configuration is legacy summary-only."""
    root = Path(campaign_dir).resolve()
    if not selectors:
        raise AuthorityError("configured authority note selection is empty")
    members: dict[Path, SelectionMember] = {}
    for selector in selectors:
        authored = selector.path
        candidate = Path(authored)
        base = candidate if candidate.is_absolute() else root / candidate
        if any(ch in authored for ch in "*?["):
            import glob
            matches = [Path(path) for path in sorted(glob.glob(str(base), recursive=True))]
        else:
            matches = [base]
        if not matches:
            raise AuthorityError(f"selector {selector.id} matched no notes: {authored}")
        for match in matches:
            try:
                resolved = match.resolve(strict=True)
            except OSError as exc:
                raise AuthorityError(f"selector {selector.id} is unreadable: {authored}") from exc
            if not resolved.is_file() or not os_access_readable(resolved):
                raise AuthorityError(f"selector {selector.id} is unreadable: {authored}")
            ids = tuple(sorted(selector.record_ids or ()))
            member = SelectionMember(selector.id, authored, str(resolved), not _under(resolved, root), ids, hashlib.sha256(resolved.read_bytes()).hexdigest(), f"selector:{selector.id}")
            old = members.get(resolved)
            if old:
                members[resolved] = SelectionMember(
                    selector_id=",".join(sorted({*old.selector_id.split(","), selector.id})),
                    authored_path=",".join(sorted({*old.authored_path.split(","), authored})),
                    resolved_path=str(resolved), external=old.external,
                    record_ids=tuple(sorted(set(old.record_ids) | set(ids))), digest=old.digest,
                    reason=",".join(sorted({*old.reason.split(","), member.reason})),
                )
            else:
                members[resolved] = member
    ordered = tuple(sorted(members.values(), key=lambda m: m.resolved_path))
    return SelectionSnapshot(_digest(list(selectors)), ordered, _digest([m.__dict__ for m in ordered]))


def os_access_readable(path: Path) -> bool:
    try:
        path.read_bytes()
        return True
    except OSError:
        return False


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _artifact_sha256(path: Path, *, label: str) -> str:
    """Digest an immutable authority artifact named by a live record."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise AuthorityError(f"authority {label} is missing or unreadable: {path.name}") from exc


def resolve_anchor_span(data: bytes, anchor: str) -> bytes:
    """Resolve an independently reviewable anchored section without widening scope."""
    # YAML and JSON support files cannot accept a marker without changing
    # their parsed value. This marker is support-only; ruling records reject
    # it, so it can never authorize a whole-document source correction.
    if anchor == DOCUMENT_ANCHOR:
        return data
    # Markdown uses an HTML marker; YAML/config support uses an ordinary YAML
    # comment so a complete config can remain valid for its native parser.
    marker = re.compile(
        rb"(?:<!--\s*anchor:\s*" + re.escape(anchor.encode()) + rb"\s*-->|^\s*#\s*anchor:\s*"
        + re.escape(anchor.encode()) + rb"\s*$)", re.I | re.M)
    matches = list(marker.finditer(data))
    if not matches:
        raise AuthorityError(f"authority anchor {anchor!r} is missing")
    if len(matches) != 1:
        raise AuthorityError(f"authority anchor {anchor!r} is ambiguous")
    found = matches[0]
    # A scene is an H3, so H3 boundaries are just as significant as H1/H2
    # boundaries for a reviewed source slice.
    suffix = data[found.end():]
    next_heading = re.search(rb"^(#{1,3})\s+", suffix, re.M)
    # An anchor immediately before a structured summary heading owns that
    # complete heading block.  Treating the heading itself as the boundary
    # would leave no citeable evidence for audience-specific extraction.
    if next_heading and not suffix[:next_heading.start()].strip():
        level = len(next_heading.group(1))
        following = re.search(rb"^#{1," + str(level).encode() + rb"}\s+", suffix[next_heading.end():], re.M)
        end = found.end() + next_heading.end() + (following.start() if following else len(suffix[next_heading.end():]))
    else:
        end = found.end() + next_heading.start() if next_heading else len(data)
    return data[found.start():end]


def resolve_anchored_records(ledger: AuthorityLedger, *, audience: str, since: int | None = None,
                             until: int | None = None) -> list[AuthorityRecord]:
    if audience not in {"gm", "players", "characters"} and not audience.startswith("character:"):
        raise AuthorityError(f"invalid audience target {audience!r}")
    return [r for r in ledger.records if r.audience.allows(audience)
            and getattr(r, "status", None) in {"active", "applied"}
            and _effective_for_range(r.effective, since, until)]


def _effective_for_range(effective, since: int | None, until: int | None) -> bool:
    """Bounded historical records must overlap the requested chapter range.

    Future/open planning records remain current intentional context; chapter
    ranges only restrict records that declare chapter bounds.
    """
    if since is None or until is None or effective.horizon is not None:
        return True
    start = effective.from_chapter if effective.from_chapter is not None else 0
    end = effective.through_chapter if effective.through_chapter is not None else float("inf")
    return start <= until and since <= end


_PRECEDENCE = {
    Classification.RULED: 6,
    Classification.CANON: 5,
    Classification.TABLE: 4,
    Classification.OVERLAY: 3,
    Classification.PREP: 2,
    Classification.OPEN: 1,
}


def _intervals_overlap(left, right) -> bool:
    """Future/open intervals overlap conservatively; bounded chapter spans compare exactly."""
    if left.horizon is not None or right.horizon is not None:
        return True
    left_start, left_end = left.from_chapter or 0, left.through_chapter if left.through_chapter is not None else float("inf")
    right_start, right_end = right.from_chapter or 0, right.through_chapter if right.through_chapter is not None else float("inf")
    return left_start <= right_end and right_start <= left_end


def resolve_planning_precedence(records: list[AuthorityRecord]) -> tuple[list[AuthorityRecord], list[str]]:
    """Select one scoped planning fact per claim and retain unresolved OPEN prompts."""
    groups: dict[tuple[str, str, str], list[AuthorityRecord]] = {}
    warnings: list[str] = []
    for record in records:
        if Projection.PLANNING not in record.projections:
            continue
        key = (record.subject.kind, record.subject.id, record.claim_key or record.id)
        groups.setdefault(key, []).append(record)
    resolved: list[AuthorityRecord] = []
    for key, candidates in sorted(groups.items()):
        active = [r for r in candidates if getattr(r, "status", None) in {"active", "applied"}]
        if not active:
            continue
        active.sort(key=lambda r: (-_PRECEDENCE[r.classification], -r.revision, r.id))
        overlays = [r for r in active if r.classification is Classification.OVERLAY]
        for index, left in enumerate(overlays):
            for right in overlays[index + 1:]:
                if left.normalized_value != right.normalized_value and _intervals_overlap(left.effective, right.effective):
                    raise AuthorityError(f"AUTH_CONFLICT: equal OVERLAY claims conflict for {key[0]}:{key[1]}", "AUTH_CONFLICT")
        # OPEN is an unresolved question, never a lower-precedence fact that a
        # later fact silently settles.  Keep it in the reviewed prompt.
        open_questions = [r for r in active if r.classification is Classification.OPEN]
        settled: list[AuthorityRecord] = []
        for candidate in (r for r in active if r.classification is not Classification.OPEN):
            if any(_intervals_overlap(candidate.effective, chosen.effective) for chosen in settled):
                continue
            settled.append(candidate)
        resolved.extend(settled)
        for record in open_questions:
            warnings.append(f"open planning question retained: {record.id}")
            resolved.append(record)
        for record in [*settled, *open_questions]:
            if record.effective.horizon == "future":
                warnings.append(f"future planning authority: {record.id}")
    return resolved, warnings


def selected_planning_records(campaign_dir: Path, ledger: AuthorityLedger, selection: SelectionSnapshot, *, audience: str = "gm",
                              since: int | None = None, until: int | None = None) -> list[AuthorityRecord]:
    """Return only classified planning notes named by the reviewed snapshot.

    The selector grants no implicit file-wide authority: each selected file
    must be represented by an active planning NoteRecord, and ``record_ids``
    narrows that set when present.
    """
    root = Path(campaign_dir).resolve()
    active = resolve_anchored_records(ledger, audience=audience, since=since, until=until)
    result: list[AuthorityRecord] = []
    for member in selection.members:
        matching = []
        for record in active:
            if not isinstance(record, NoteRecord) or Projection.PLANNING not in record.projections:
                continue
            source = Path(record.source.path)
            source = source if source.is_absolute() else root / source
            try:
                same_file = source.resolve(strict=True) == Path(member.resolved_path)
            except OSError:
                same_file = False
            if same_file and (not member.record_ids or record.id in member.record_ids):
                matching.append(record)
        if not matching:
            suffix = f" ({', '.join(member.record_ids)})" if member.record_ids else ""
            # Do not disclose an omitted file or record id to a non-GM caller.
            if audience != "gm":
                raise AuthorityError("selected planning authority has no complete support for this audience")
            raise AuthorityError(f"selected note has no active classified planning record: {member.authored_path}{suffix}")
        result.extend(matching)
    return sorted({record.id: record for record in result}.values(), key=lambda record: record.id)


def build_manifest(campaign_dir: Path, ledger: AuthorityLedger | None = None, *, audience: str = "gm", selection: SelectionSnapshot | None = None, horizon: str | None = None, since: int | None = None, until: int | None = None) -> dict:
    with authority_lock(campaign_dir, exclusive=False):
        require_no_pending_transaction(campaign_dir)
        # Load while holding the shared lock.  Callers may pass a ledger for
        # convenience, but it may not be used to create a mixed generation.
        current = load_ledger(campaign_dir)
        if ledger is not None and (ledger.revision != current.revision or ledger.campaign != current.campaign):
            raise AuthorityError("authority ledger changed while constructing input manifest", "AUTH_STALE")
        ledger = current
        records = resolve_anchored_records(ledger, audience=audience, since=since, until=until)
        if selection is not None:
            records = selected_planning_records(campaign_dir, ledger, selection, audience=audience, since=since, until=until)
        entries = []
        payload = []
        root = Path(campaign_dir).resolve()
        for record in records:
            validate_record_identity(campaign_dir, record)
            path = Path(record.source.path)
            path = path if path.is_absolute() else root / path
            if not path.is_file():
                raise AuthorityError(f"authority source is missing or unreadable: {record.source.path}")
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise AuthorityError(f"authority source is missing or unreadable: {record.source.path}") from exc
            section = resolve_anchor_span(data, record.source.anchor)
            source_sha = hashlib.sha256(data).hexdigest()
            section_sha = hashlib.sha256(section).hexdigest()
            expected = getattr(record, "content_digest", None)
            if expected and expected != section_sha:
                raise AuthorityError(f"authority source section digest changed for {record.id}", "AUTH_STALE")
            proposal_id = getattr(record, "proposal_id", None)
            receipt_id = getattr(record, "applied_receipt", None)
            artifacts = root / "docs" / "authority"
            entries.append({
                "id": record.id,
                "revision": record.revision,
                "kind": record.kind,
                "classification": record.classification.value,
                "metadata_sha256": record_metadata_digest(record),
                "audience": sorted(record.audience.grants),
                "subject": record.subject.model_dump(mode="json"),
                "effective": record.effective.model_dump(mode="json", exclude_none=True),
                "source": record.source.path,
                "source_sha256": source_sha,
                "section_sha256": section_sha,
                "anchor": record.source.anchor,
                "proposal_sha256": _artifact_sha256(
                    artifacts / "proposals" / proposal_id / "proposal.json", label="proposal"
                ) if proposal_id else None,
                "receipt_sha256": _artifact_sha256(
                    artifacts / "receipts" / f"{receipt_id}.json", label="receipt"
                ) if receipt_id else None,
            })
            payload.append({"record": record.id, "section_sha256": section_sha, "audience": audience})
        manifest = {"authority_schema": SCHEMA_VERSION, "authority_policy": POLICY_VERSION, "ledger_sha256": ledger_digest(campaign_dir), "ledger_revision": ledger.revision, "records": entries, "audience": audience, "horizon": horizon, "range": None if since is None or until is None else {"since": since, "until": until}, "selection": None if selection is None else {"selection_sha256": selection.digest, "selectors_sha256": selection.selectors_digest, "membership_sha256": selection.membership_digest, "members": [m.__dict__ for m in selection.members]}, "pending_transaction": None}
        manifest["filtered_payload_sha256"] = _digest(payload)
        return manifest
