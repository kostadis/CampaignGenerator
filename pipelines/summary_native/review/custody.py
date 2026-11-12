"""Per-item source custody for review (spec 042): the one seam.

Deterministic and model-free (Constitution V, FR-015). Everything here answers one
question: *which of the files a review was built from does THIS item rest on, and have
any of them changed?* The review store (decision save, bundle import, status) and the
publish gate all ask it here, so they cannot disagree.

The precision rule governs every ambiguity: an item's dependency set is never smaller
than what the item rests on. Wherever something cannot be read, parsed or resolved, the
set widens (all evidence, all summaries) -- it never narrows. Nothing here is stored:
a dependency set is computed from the custody record, the items' bindings and the bytes
of the NPC's evidence file, and that file is parsed only while its bytes still equal
what custody recorded (research R2).

Public surface: ``role_of``, ``FileState``, ``disk_probe``, ``evidence_summary_paths``,
``dependency_sets``, ``stale_report``, ``refusal_detail``, ``refusal_message``,
``refusal_text_lines``, ``stale_by_npc``, ``remedy``, ``npc_label``.

(``DiskProbe.with_overrides`` / ``OverrideProbe`` are a test and replay helper -- they simulate a
changed file without writing one -- and are not part of what the store or publish call.)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Sequence

import yaml

from pipelines.summary_native.review.models import ReviewItem, SourceCustodyGeneration, SourceFile

DETAIL_VERSION = 1
NPC_DOMAIN = "npc_finding"
NPC_KIND = "npc_verification"


# ── roles and file states ──────────────────────────────────────────────────

class SourceRole(str, Enum):
    draft = "draft"
    evidence = "evidence"
    summary = "summary"
    other = "other"


def role_of(source_id: str) -> SourceRole:
    """Classify a custody source by its id prefix (R4). Unknown prefixes are ``other``.

    The builders name every source ``<role>-<digest>`` with role ``draft``, ``evidence`` or
    ``summary-<n>``. An ``other`` source is put in EVERY item's set, so a future builder's
    new kind of file keeps today's strictness instead of being silently ignored.
    """
    if source_id.startswith("draft-"):
        return SourceRole.draft
    if source_id.startswith("evidence-"):
        return SourceRole.evidence
    if source_id.startswith("summary-"):
        return SourceRole.summary
    return SourceRole.other


class FileState(str, Enum):
    current = "current"
    changed = "changed"
    missing = "missing"
    unreadable = "unreadable"


class DiskProbe:
    """Current-bytes view of the campaign, hashing each path at most once per probe.

    Callable as ``probe(source) -> FileState``; ``probe.read(source)`` returns the bytes the
    state was decided on (``None`` unless the file was readable). A symlink anywhere in the
    path raises ``REVIEW_PATH`` (a security refusal, not a staleness state) -- unless the probe is
    ``lenient`` (the read-only status view), where it is reported as ``unreadable`` instead so one
    odd path cannot hide every other file's state. The root is resolved here: a relative campaign
    dir would otherwise be joined onto itself.
    """

    def __init__(self, root: Path, *, lenient: bool = False):
        self.root = Path(root).resolve()
        self.lenient = lenient
        self._seen: dict[str, tuple[str | None, bytes | None]] = {}  # path -> (digest | None, bytes | None)
        self._failed: dict[str, FileState] = {}

    def _load(self, path: str) -> tuple[str | None, bytes | None]:
        if path in self._seen:
            return self._seen[path]
        from pipelines.summary_native.review.store import ReviewStoreError, _reject_symlinks  # lazy: store imports this module

        entry: tuple[str | None, bytes | None]
        try:
            try:
                absolute = _reject_symlinks(self.root, self.root / path)
            except ReviewStoreError:
                if not self.lenient:
                    raise
                self._failed[path] = FileState.unreadable
                self._seen[path] = entry = (None, None)
                return entry
            if not absolute.is_file():
                self._failed[path] = FileState.missing
                entry = (None, None)
            else:
                data = absolute.read_bytes()
                entry = (hashlib.sha256(data).hexdigest(), data)
        except OSError:
            self._failed[path] = FileState.unreadable
            entry = (None, None)
        self._seen[path] = entry
        return entry

    def __call__(self, source: SourceFile) -> FileState:
        digest, _data = self._load(source.path)
        if digest is None:
            return self._failed[source.path]
        return FileState.current if digest == source.sha256 else FileState.changed

    def read(self, source: SourceFile) -> bytes | None:
        return self._load(source.path)[1]

    def with_overrides(self, overrides: dict[str, FileState]) -> "OverrideProbe":
        """Test/replay helper: a probe that reports ``overrides[path]`` instead of the disk (no writes)."""
        return OverrideProbe(self, overrides)


class OverrideProbe:
    def __init__(self, base: Callable[[SourceFile], FileState], overrides: dict[str, FileState]):
        self.base = base
        self.overrides = dict(overrides)

    def __call__(self, source: SourceFile) -> FileState:
        return self.overrides.get(source.path) or self.base(source)

    def read(self, source: SourceFile) -> bytes | None:
        reader = getattr(self.base, "read", None)
        return reader(source) if reader else None

    def with_overrides(self, overrides: dict[str, FileState]) -> "OverrideProbe":
        return OverrideProbe(self, overrides)


StateProvider = Callable[[SourceFile], FileState]


def disk_probe(root: Path, *, lenient: bool = False) -> DiskProbe:
    return DiskProbe(root, lenient=lenient)


# ── value objects ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChangedFile:
    path: str
    source_id: str
    role: SourceRole
    state: FileState


@dataclass(frozen=True)
class DependencySet:
    item_id: str
    npc: str | None
    npc_key: str
    source_ids: frozenset[str]
    evidence_basis: str   # bound | sibling | layout | fallback_all_evidence | not_applicable
    summary_basis: str    # evidence_sources | fallback_all_summaries | corpus | unbound_sources


@dataclass(frozen=True)
class StaleReport:
    stale: dict[str, tuple[ChangedFile, ...]]
    changed_files: tuple[ChangedFile, ...]
    dependency_sets: dict[str, DependencySet]
    no_dependency: frozenset[str] = frozenset()
    #: only when every item was examined (``item_ids=None``): changed custody files no item depends on
    unreferenced_changed: tuple[ChangedFile, ...] = ()


# ── NPC label ──────────────────────────────────────────────────────────────

def draft_stem_name(source_path: str | None) -> str | None:
    """The draft file's stem without its ``npc_`` prefix (and ``.verify`` suffix)."""
    stem = Path(str(source_path or "")).name
    stem = stem[:-len(".md")] if stem.endswith(".md") else stem
    if stem.endswith(".verify"):
        stem = stem[:-len(".verify")]
    stem = stem[len("npc_"):] if stem.startswith("npc_") else stem
    return stem or None


def npc_label(item: ReviewItem) -> str | None:
    """``registry_name`` when the subject has one, else the draft stem without ``npc_`` (R12)."""
    return getattr(item.subject_ref, "registry_name", None) or draft_stem_name(item.locator.source_path)


# ── evidence -> summaries (R5) ─────────────────────────────────────────────

_SOURCE_LINE = re.compile(r"^\s*[-*+]\s+Source: (\S.*?) \(line \d+\)$")
# Any list-item line carrying a ``Source:`` marker is a Source line, however it is indented or
# bulleted: an unrecognised shape must fall back, never be silently skipped.
_SOURCE_MARKER = re.compile(r"^\s*[-*+]\s+Source:")
_CHAPTER_HEAD = re.compile(r"^## Chapter (\d+)\b")


def evidence_summary_paths(evidence_bytes: bytes, custody_paths: Iterable[str]) -> frozenset[str] | None:
    """The summary paths an evidence file names, or ``None`` (meaning: depend on every summary).

    ``None`` unless ALL hold: (1) at least one ``- Source:`` line; (2) every such line matches
    ``- Source: <path> (line N)`` and its path is a custody path; (3) every ``## Chapter NNN``
    section holds at least one; (4) a frontmatter ``chapters:`` list, if present, equals the set
    of ``## Chapter`` numbers. Any irregularity is a fallback: one unparsable line cannot drop a
    dependency.
    """
    known = set(custody_paths)
    try:
        text = evidence_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = text.splitlines()
    declared: set[int] | None = None
    body_from = 0
    if lines and lines[0].rstrip() == "---":
        close = next((n for n in range(1, len(lines)) if lines[n].rstrip() == "---"), None)
        if close is None:
            return None
        try:
            front = yaml.safe_load("\n".join(lines[1:close]))
        except yaml.YAMLError:
            return None
        if not isinstance(front, dict):
            return None
        if "chapters" in front:
            chapters = front["chapters"]
            if (not isinstance(chapters, list)
                    or any(isinstance(c, bool) or not isinstance(c, int) for c in chapters)):
                return None
            declared = set(chapters)
        body_from = close + 1
    paths: set[str] = set()
    sections: dict[int, int] = {}  # chapter number -> Source lines inside it
    current: int | None = None
    any_source = False
    for line in lines[body_from:]:
        head = _CHAPTER_HEAD.match(line)
        if head:
            current = int(head.group(1))
            sections.setdefault(current, 0)
            continue
        if line.startswith("## "):
            current = None
            continue
        if _SOURCE_MARKER.match(line):
            any_source = True
            match = _SOURCE_LINE.match(line)
            if match is None or match.group(1) not in known:
                return None
            paths.add(match.group(1))
            if current is not None:
                sections[current] += 1
    if not any_source or any(count == 0 for count in sections.values()):
        return None
    if declared is not None and declared != set(sections):
        return None
    return frozenset(paths)


# ── dependency sets ────────────────────────────────────────────────────────

class _Index:
    """Lookups over one review's custody and items, built once per computation."""

    def __init__(self, custody: SourceCustodyGeneration, items: Sequence[ReviewItem]):
        self.custody = custody
        self.items = list(items)
        self.by_id = {s.source_id: s for s in custody.sources}
        self.by_path = {s.path: s for s in custody.sources}
        self.by_role: dict[SourceRole, set[str]] = {role: set() for role in SourceRole}
        for source in custody.sources:
            self.by_role[role_of(source.source_id)].add(source.source_id)
        self.by_draft: dict[str, list[ReviewItem]] = {}
        for item in self.items:
            for path in self.draft_paths(item):
                self.by_draft.setdefault(path, []).append(item)
        bound = {b.source_id for item in self.items for b in item.input_bindings}
        self.unbound = frozenset(sid for sid in self.by_id if sid not in bound)

    def bound_ids(self, item: ReviewItem) -> set[str]:
        """The custody sources an item binds. A binding is never silently dropped.

        Resolved by ``source_id``; failing that by ``path`` (custody and bindings can disagree on
        an id, never on where the file lives); failing both it WIDENS to every source of the
        binding's role (every source, for an unknown role) -- an unresolvable binding must not
        shrink the set the item rests on.
        """
        out: set[str] = set()
        for binding in item.input_bindings:
            if binding.source_id in self.by_id:
                out.add(binding.source_id)
            elif binding.path in self.by_path:
                out.add(self.by_path[binding.path].source_id)
            else:
                role = role_of(binding.source_id)
                widened = set() if role is SourceRole.other else set(self.by_role[role])
                out |= widened or set(self.by_id)
        return out

    def draft_paths(self, item: ReviewItem) -> list[str]:
        paths = [b.path for b in item.input_bindings
                 if role_of(b.source_id) is SourceRole.draft]
        return list(dict.fromkeys(paths))

    def npc_key(self, item: ReviewItem) -> str:
        drafts = self.draft_paths(item)
        return drafts[0] if drafts else item.locator.source_path

    def evidence_of(self, item: ReviewItem) -> tuple[frozenset[str], str]:
        evid = {s for s in self.bound_ids(item) if role_of(s) is SourceRole.evidence}
        sibling: set[str] = set()
        layout: set[str] = set()
        for path in self.draft_paths(item):
            for other in self.by_draft.get(path, ()):
                if other.item_id != item.item_id:
                    sibling |= {s for s in self.bound_ids(other) if role_of(s) is SourceRole.evidence}
            posix = PurePosixPath(path)
            if posix.parent.name == "draft":
                target = str(posix.parent.parent / "evidence" / posix.name)
                found = self.by_path.get(target)
                if found is not None:
                    layout.add(found.source_id)
        union = evid | sibling | layout
        if not union:
            return frozenset(self.by_role[SourceRole.evidence]), "fallback_all_evidence"
        basis = "bound" if evid else "sibling" if sibling else "layout"
        return frozenset(union), basis


# A finding whose verdict was computed against the whole in-range corpus (not just this NPC's
# evidence) rests on every summary: ``invalid`` / ``outside-evidence`` are decided by corpus
# membership of the cited scene, and ``not-found`` carries "(verbatim in the summaries ...)" -- a
# summary that gains or loses the quote changes its message. Sign-off items are NOT in this set:
# their ``mechanical_verdict`` is recorded as ``pass``, and a pass cannot be flipped by a summary
# the evidence does not name (a cited target resolves into an evidence-named summary).
CORPUS_DEPENDENT_CODES = frozenset({"invalid", "outside-evidence", "not-found"})
_CORPUS_PHRASES = ("in-range corpus", "in the summaries", "the corpus")
SIGNOFF_ACTION = "signoff_npc_draft"


def corpus_dependent(item: ReviewItem) -> bool:
    """Whether a finding item's verdict depends on the whole summaries corpus (see above)."""
    if item.proposed_action.action == SIGNOFF_ACTION:
        return False
    for diagnostic in item.diagnostics:
        if str(diagnostic.legacy_code) in CORPUS_DEPENDENT_CODES:
            return True
        # The verifier's own words only (message and its ``detail``), never the draft's quoted
        # ``text``: a dossier line saying "not established in the summaries" is prose, not a verdict.
        detail = diagnostic.details.get("detail") if isinstance(diagnostic.details, dict) else None
        text = f"{diagnostic.message} {detail or ''}".casefold()
        if any(phrase in text for phrase in _CORPUS_PHRASES):
            return True
    return False


def _kind_value(kind) -> str:
    return str(getattr(kind, "value", kind))


def dependency_sets(kind, custody: SourceCustodyGeneration, items: Sequence[ReviewItem],
                    item_ids: Iterable[str] | None, state: StateProvider) -> dict[str, DependencySet]:
    """The dependency set of each named item (all items when ``item_ids`` is ``None``).

    NPC verification items: ``bound | evidence(R6) | summaries(R5) | other``. An evidence file is
    parsed only when ``state(evidence) is current`` (so the parsed list is the recorded one), with
    bytes read through the probe's cache; otherwise, or when it parses to ``None``, every
    summary-role source joins. Any other item: ``bound | sources no item binds | other`` (R7).
    Unknown ids are skipped.
    """
    index = _Index(custody, items)
    wanted = None if item_ids is None else set(item_ids)
    reader = getattr(state, "read", None)
    all_paths = set(index.by_path)
    parsed: dict[str, frozenset[str] | None] = {}

    def summaries_named(source_id: str) -> frozenset[str] | None:
        if source_id in parsed:
            return parsed[source_id]
        source = index.by_id[source_id]
        result: frozenset[str] | None = None
        if state(source) is FileState.current and reader is not None:
            data = reader(source)
            if data is not None:
                paths = evidence_summary_paths(data, all_paths)
                if paths is not None:
                    result = frozenset(index.by_path[p].source_id for p in paths)
        parsed[source_id] = result
        return result

    npc_rule = _kind_value(kind) == NPC_KIND
    other = index.by_role[SourceRole.other]
    out: dict[str, DependencySet] = {}
    for item in index.items:
        if wanted is not None and item.item_id not in wanted:
            continue
        bound = index.bound_ids(item)
        if npc_rule and _kind_value(item.domain) == NPC_DOMAIN:
            evidence, e_basis = index.evidence_of(item)
            summaries: set[str] = set()
            s_basis = "evidence_sources"
            if e_basis == "fallback_all_evidence":
                s_basis = "fallback_all_summaries"
            else:
                for sid in evidence:
                    named = summaries_named(sid)
                    if named is None:
                        s_basis = "fallback_all_summaries"
                        break
                    summaries |= named
            if s_basis != "fallback_all_summaries" and corpus_dependent(item):
                s_basis = "corpus"
            if s_basis in ("fallback_all_summaries", "corpus"):
                summaries = set(index.by_role[SourceRole.summary])
            ids = bound | evidence | summaries | other
        else:
            e_basis, s_basis = "not_applicable", "unbound_sources"
            ids = bound | set(index.unbound) | other
        out[item.item_id] = DependencySet(
            item_id=item.item_id, npc=npc_label(item), npc_key=index.npc_key(item),
            source_ids=frozenset(ids), evidence_basis=e_basis, summary_basis=s_basis,
        )
    return out


# ── staleness ──────────────────────────────────────────────────────────────

def stale_report(kind, custody: SourceCustodyGeneration, items: Sequence[ReviewItem],
                 item_ids: Iterable[str] | None, state: StateProvider) -> StaleReport:
    """An item is stale iff some source in its dependency set is not ``current`` (FR-002).

    The baseline is the custody generation's recorded sha, never a binding's (R3). An item with
    an empty dependency set is stale (``no_dependency``): nothing can show it current.
    """
    deps = dependency_sets(kind, custody, items, item_ids, state)
    by_id = {s.source_id: s for s in custody.sources}
    verdicts: dict[str, ChangedFile | None] = {}

    def changed(source_id: str) -> ChangedFile | None:
        if source_id not in verdicts:
            source = by_id[source_id]
            current = state(source)
            verdicts[source_id] = None if current is FileState.current else ChangedFile(
                source.path, source_id, role_of(source_id), current)
        return verdicts[source_id]

    stale: dict[str, tuple[ChangedFile, ...]] = {}
    empty: set[str] = set()
    for item_id, dep in deps.items():
        files = tuple(sorted((c for c in (changed(s) for s in dep.source_ids) if c is not None),
                             key=lambda c: c.path))
        if files:
            stale[item_id] = files
        elif not dep.source_ids:
            stale[item_id] = ()
            empty.add(item_id)
    union = {c.source_id: c for files in stale.values() for c in files}
    unreferenced: tuple[ChangedFile, ...] = ()
    if item_ids is None:
        referenced = {sid for dep in deps.values() for sid in dep.source_ids}
        unreferenced = tuple(sorted(
            (c for sid in by_id if sid not in referenced and (c := changed(sid)) is not None),
            key=lambda c: c.path))
    return StaleReport(
        stale=stale, changed_files=tuple(sorted(union.values(), key=lambda c: c.path)),
        dependency_sets=deps, no_dependency=frozenset(empty), unreferenced_changed=unreferenced,
    )


# ── the refusal and the status view ────────────────────────────────────────

def remedy(review_id: str, generation: int, has_draft: bool) -> dict:
    """The named command that brings items current (FR-008: never run for the GM)."""
    out = {"command": f"summary_native review refresh {review_id} --expected-generation {generation}"}
    if has_draft:
        out["note"] = "A changed draft also needs a new verification review before its sign-off can be approved."
    return out


def refusal_message(report: StaleReport, operation: str = "decide") -> str:
    tail = "nothing was imported" if operation == "import" else "nothing was saved"
    return (f"REVIEW_STALE_CUSTODY: {len(report.changed_files)} source file(s) changed; "
            f"{len(report.stale)} submitted item(s) depend on them; {tail}")


def _npc_sort(npc: str | None, key: str) -> tuple:
    return (npc is None, npc or "", key)


def refusal_detail(report: StaleReport, *, review_id: str, generation: int, operation: str,
                   items: Sequence[ReviewItem]) -> dict:
    """The ``data`` of a ``REVIEW_STALE_CUSTODY`` refusal (contracts/custody-refusal.md)."""
    by_item = {i.item_id: i for i in items}
    file_items: dict[str, list[str]] = {}
    for item_id, files in report.stale.items():
        for changed in files:
            file_items.setdefault(changed.source_id, []).append(item_id)

    def label(item_id: str) -> str | None:
        dep = report.dependency_sets.get(item_id)
        return dep.npc if dep is not None else (npc_label(by_item[item_id]) if item_id in by_item else None)

    changed_files = [{
        "path": c.path, "source_id": c.source_id, "role": c.role.value, "state": c.state.value,
        "items": [{"item_id": i, "npc": label(i),
                   "action": by_item[i].proposed_action.action if i in by_item else None}
                  for i in sorted(file_items.get(c.source_id, ()))],
    } for c in report.changed_files]
    stale_items = []
    for item_id in sorted(report.stale):
        entry = {"item_id": item_id, "npc": label(item_id), "paths": sorted(c.path for c in report.stale[item_id])}
        if item_id in report.no_dependency:
            entry["reason"] = "no_dependency"
        stale_items.append(entry)
    groups: dict[str, dict] = {}
    for item_id, files in report.stale.items():
        dep = report.dependency_sets[item_id]
        group = groups.setdefault(dep.npc_key, {"npc": dep.npc, "item_ids": [], "paths": set()})
        group["item_ids"].append(item_id)
        group["paths"].update(c.path for c in files)
    by_npc = [{"npc": g["npc"], "item_ids": sorted(g["item_ids"]), "paths": sorted(g["paths"])}
              for key, g in sorted(groups.items(), key=lambda kv: _npc_sort(kv[1]["npc"], kv[0]))]
    return {
        "version": DETAIL_VERSION, "operation": operation, "review_id": review_id,
        "review_generation": generation, "changed_files": changed_files, "stale_items": stale_items,
        "by_npc": by_npc,
        "remedy": remedy(review_id, generation, any(c.role is SourceRole.draft for c in report.changed_files)),
    }


def refusal_text_lines(detail: dict) -> list[str]:
    """CLI text-mode lines that follow the one-line message: files, then the remedy."""
    lines = []
    for changed in detail.get("changed_files", []):
        by_npc: dict[str | None, list[str]] = {}
        for entry in changed.get("items", []):
            by_npc.setdefault(entry.get("npc"), []).append(entry["item_id"])
        who = "; ".join(f"{npc or '(unnamed)'} — {', '.join(ids)}" for npc, ids in by_npc.items())
        lines.append(f"  {changed['state']:<7}  {changed['path']}: {who}")
    fix = detail.get("remedy", {})
    if fix.get("command"):
        lines.append(f"Bring them current: {fix['command']}")
    if fix.get("note"):
        lines.append(fix["note"])
    return lines


def stale_by_npc(report: StaleReport, items: Sequence[ReviewItem]) -> dict:
    """The two ``review status`` keys (contracts/review-status.md), from a whole-review report."""
    depending: dict[str, int] = {}
    for dep in report.dependency_sets.values():
        for sid in dep.source_ids:
            depending[sid] = depending.get(sid, 0) + 1
    files = {c.source_id: c for c in (*report.changed_files, *report.unreferenced_changed)}
    changed_files = [{"path": c.path, "role": c.role.value, "state": c.state.value,
                      "stale_item_count": depending.get(c.source_id, 0)}
                     for c in sorted(files.values(), key=lambda c: c.path)]
    groups: dict[str, dict] = {}
    for item_id, changed in report.stale.items():
        dep = report.dependency_sets[item_id]
        group = groups.setdefault(dep.npc_key, {"npc": dep.npc, "ids": [], "files": {}})
        group["ids"].append(item_id)
        for c in changed:
            group["files"][c.path] = c.state.value
    stale = [{
        "npc": g["npc"], "npc_key": key, "stale_item_count": len(g["ids"]),
        "stale_item_ids": sorted(g["ids"]),
        "changed_files": [{"path": p, "state": s} for p, s in sorted(g["files"].items())],
    } for key, g in sorted(groups.items(), key=lambda kv: _npc_sort(kv[1]["npc"], kv[0]))]
    return {"changed_files": changed_files, "stale_by_npc": stale}
