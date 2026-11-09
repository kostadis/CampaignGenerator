"""The grounding baseline a delta edits against (spec 039, FR-002, FR-003, T025-T027).

The baseline is bound from the *active* generation: the identity comes from the managed layout's
``current`` link and the reconciled activation history (``promotion/history.py``), never from the
newest directory name.  Each of the four grounding documents is bound by two digests: the immutable
bytes the generation published (``origin_sha256``) and the bytes now in the live tree
(``live_sha256``).  Any difference is *drift* (a hand edit after publication), listed as stable hunks
and never silently folded into the baseline: the baseline stays ``unadopted`` until each hunk is
explicitly accepted or rejected (``adopt``), which writes a NEW record and rewrites nothing earlier.

Coverage is per member (timeline, reference tree, reading-contract records).  It is read from the
generation manifest only; live prose that cites a later chapter never raises an inherited member's
coverage (data-model.md GroundingBaseline).  No model call is made here.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from campaignlib.grounding_bundle import inspect_layout
from pipelines.summary_native.promotion.errors import (
    PromotionError, PromotionMigrationRequired, PromotionRecoveryRequired,
)
from pipelines.summary_native.promotion.history import current_activation, grounding_dir
from pipelines.summary_native.promotion.models import GenerationManifest
from pipelines.summary_native.review.models import canonical_digest

from .errors import EXIT_RECOVERY, EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .plan import DELTA_ROOT_REL

DOCUMENT_NAMES = ("world_state", "campaign_state", "party", "planning")
TIMELINE_NAME = "canon_events_timeline.md"
DISPOSITIONS = ("accept", "reject")
_HUNK_ID = re.compile(r"^(world_state|campaign_state|party|planning)#(\d+)$")


class DocBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    origin_sha256: str
    live_sha256: str
    origin_ref: str
    approval_ref: str


class MemberBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    sha256: str | None
    coverage_through: int | None
    gaps: list[str] = Field(default_factory=list)
    audience: str = "gm"


class DriftHunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hunk_id: str
    document: str
    origin_start: int  # 0-based line slice [start, end) of the origin
    origin_end: int
    live_start: int
    live_end: int
    kind: Literal["replace", "delete", "insert"]
    hunk_sha256: str
    diff: str


class HunkDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hunk: str
    hunk_sha256: str
    disposition: Literal["accept", "reject"]


class Adoption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    revision: int = Field(ge=1)
    generation_id: str
    manifest_sha256: str
    activation_id: str
    live_sha256: dict[str, str]
    adopted_at: str
    drift: list[HunkDisposition]


class GroundingBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation_id: str
    manifest_sha256: str
    activation_id: str
    documents: list[DocBinding]
    members: list[MemberBinding]
    drift: list[DriftHunk]
    adoption: Adoption | None = None
    status: Literal["valid", "unadopted", "adopted"]
    coverage: dict[str, int | None]

    @property
    def usable(self) -> bool:
        """Unreviewed drift blocks use (FR-003)."""
        return self.status != "unadopted"

    @property
    def ref(self) -> str:
        return f"{self.generation_id}@{self.manifest_sha256}"

    def to_record(self) -> dict:
        record = self.model_dump(mode="json")
        record["usable"] = self.usable
        record["unresolved_hunks"] = [h.hunk_id for h in self.drift if not self._resolved(h)]
        return record

    def _resolved(self, hunk: DriftHunk) -> bool:
        if self.adoption is None:
            return False
        return any(d.hunk == hunk.hunk_id and d.hunk_sha256 == hunk.hunk_sha256 for d in self.adoption.drift)


# --------------------------------------------------------------------------- binding

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lines(data: bytes) -> list[bytes]:
    return data.splitlines(keepends=True)


def compute_hunks(name: str, origin: bytes, live: bytes) -> list[DriftHunk]:
    """Differences between published and live bytes, one hunk per changed opcode, ids ``<doc>#<n>``."""
    if origin == live:
        return []
    a, b = _lines(origin), _lines(live)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    hunks: list[DriftHunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        diff = "".join(
            ("-" + x.decode("utf-8", "replace").rstrip("\r\n") + "\n") for x in a[i1:i2]
        ) + "".join(
            ("+" + x.decode("utf-8", "replace").rstrip("\r\n") + "\n") for x in b[j1:j2]
        )
        header = f"@@ {name} origin {i1 + 1},{i2 - i1} live {j1 + 1},{j2 - j1} @@\n"
        n = len(hunks) + 1
        hunks.append(DriftHunk(
            hunk_id=f"{name}#{n}", document=name, origin_start=i1, origin_end=i2,
            live_start=j1, live_end=j2, kind=tag, hunk_sha256=_sha((header + diff).encode("utf-8")),
            diff=header + diff))
    return hunks


def _refuse_promotion(exc: Exception) -> DeltaRefusal:
    if isinstance(exc, PromotionRecoveryRequired):
        return DeltaRefusal(f"grounding promotion needs recovery: {exc}", EXIT_RECOVERY)
    if isinstance(exc, PromotionMigrationRequired):
        return DeltaRefusal(f"no managed grounding generation to bind a baseline to: {exc}", EXIT_REFUSAL)
    return DeltaRefusal(f"cannot bind the grounding baseline: {exc}", EXIT_REFUSAL)


def _read_manifest(campaign_dir: Path, generation_id: str) -> GenerationManifest:
    path = grounding_dir(campaign_dir) / "generations" / generation_id / "manifest.json"
    return GenerationManifest.model_validate_json(path.read_bytes())


def _delta_parent(campaign_dir: Path, manifest: GenerationManifest) -> GenerationManifest | None:
    """The generation a delta-published generation was made from, or None for any other generation.

    Read from the delta lineage records the generation retained (never from the newest directory).  Each
    hop is verified: the retained bytes against the manifest's digest, and the parent manifest against the
    digest the lineage recorded; a mismatch refuses (exit 3).
    """
    generation_dir = (campaign_dir / manifest.published_path).parent  # retained records sit beside published/
    parents: dict[str, str] = {}
    for record in manifest.retained_records:
        path = generation_dir / record.retained_path
        try:
            data = path.read_bytes()
            payload = json.loads(data)
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict) or payload.get("kind") != "delta":
            continue
        if _sha(data) != record.sha256:
            raise DeltaRefusal(f"retained delta lineage changed after publication: {record.retained_path}", EXIT_STALE)
        base = payload.get("baseline") or {}
        parents[str(base.get("generation_id"))] = str(base.get("manifest_sha256"))
    if not parents:
        return None
    if len(parents) != 1:
        raise DeltaRefusal("the retained delta lineage records name different baselines", EXIT_STALE)
    (generation_id, manifest_sha), = parents.items()
    parent = _read_manifest(campaign_dir, generation_id)
    if parent.manifest_sha256 != manifest_sha:
        raise DeltaRefusal(f"baseline generation {generation_id} changed since the delta was published", EXIT_STALE)
    return parent


def _chain_coverage(campaign_dir: Path, manifest: GenerationManifest, seen: tuple[str, ...] = ()) -> int | None:
    """Coverage through a generation, from manifests and lineage only (never from live prose)."""
    if manifest.generation_id in seen:
        raise DeltaRefusal("the delta baseline chain loops", EXIT_STALE)
    if manifest.selected_range is None:
        return None
    parent = _delta_parent(campaign_dir, manifest)
    if parent is None:
        return manifest.selected_range.until
    before = _chain_coverage(campaign_dir, parent, (*seen, manifest.generation_id))
    if before is None or before < manifest.selected_range.since - 1:
        return None  # a hole before this delta: its range is not chained to earlier coverage
    return manifest.selected_range.until


def _members(manifest: GenerationManifest, published: Path, campaign_dir: Path | None = None) -> list[MemberBinding]:
    through = manifest.selected_range.until if manifest.selected_range else None
    why = [] if through is not None else [
        f"coverage not recorded: generation kind {manifest.kind.value} carries no selected range"]
    if through is not None and campaign_dir is not None:
        parent = _delta_parent(campaign_dir, manifest)
        if parent is not None:
            before = _chain_coverage(campaign_dir, parent)
            if before is None or before < manifest.selected_range.since - 1:
                why = [f"coverage before chapter {manifest.selected_range.since} is not recorded by the "
                       f"baseline generation {parent.generation_id}; this delta's range is the only coverage claimed"]
    by_path = {m.path: m for m in manifest.members}
    timeline = by_path.get(TIMELINE_NAME)
    refs = sorted((m.path, m.sha256) for m in manifest.members if m.path.startswith("reference/"))
    records = sorted((r.retained_path, r.sha256) for r in manifest.retained_records)
    return [
        MemberBinding(name="timeline", sha256=timeline.sha256 if timeline else None,
                      coverage_through=through if timeline else None,
                      gaps=list(why) if timeline else ["no timeline member in the generation"]),
        MemberBinding(name="reference_tree", sha256=canonical_digest(refs) if refs else None,
                      coverage_through=through if refs else None,
                      gaps=list(why) if refs else ["no reference tree in the generation"]),
        MemberBinding(name="reading_contract_records",
                      sha256=canonical_digest(records) if records else None,
                      coverage_through=through if records else None,
                      gaps=list(why) if records else ["no retained reading-contract records"]),
    ]


def baseline_dir(campaign_dir: Path | str) -> Path:
    return Path(campaign_dir) / DELTA_ROOT_REL / "baseline"


def _adoption_files(campaign_dir: Path, generation_id: str) -> list[tuple[int, Path]]:
    found = []
    for p in baseline_dir(campaign_dir).glob(f"adoption-{generation_id}-r*.json"):
        m = re.fullmatch(re.escape(f"adoption-{generation_id}-r") + r"(\d+)\.json", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return sorted(found)


def load_adoption(campaign_dir: Path | str, generation_id: str) -> Adoption | None:
    """The highest-revision adoption record for the generation, or None."""
    files = _adoption_files(Path(campaign_dir), generation_id)
    if not files:
        return None
    return Adoption.model_validate_json(files[-1][1].read_text(encoding="utf-8"))


def bind(campaign_dir: Path | str) -> GroundingBaseline:
    """Bind the baseline from the ACTIVE generation; never from the newest directory."""
    root = Path(campaign_dir).absolute()
    try:
        layout = inspect_layout(root)
        generation_id = layout.generation_id
        activation, _activation_sha = current_activation(root, generation_id)
        manifest = _read_manifest(root, generation_id)
        published = root / manifest.published_path
        documents: list[DocBinding] = []
        drift: list[DriftHunk] = []
        for name in DOCUMENT_NAMES:
            origin = (published / f"{name}.md").read_bytes()
            live = (layout.live_dir / f"{name}.md").read_bytes()
            documents.append(DocBinding(
                name=name, origin_sha256=_sha(origin), live_sha256=_sha(live),
                origin_ref=f"{manifest.published_path}/{name}.md",
                approval_ref=f"{activation.activation_id}@{activation.manifest_sha256}"))
            drift.extend(compute_hunks(name, origin, live))
        members = _members(manifest, published, root)
    except (PromotionError, OSError, ValueError) as exc:
        raise _refuse_promotion(exc) from exc
    adoption = load_adoption(root, generation_id)
    baseline = GroundingBaseline(
        generation_id=generation_id, manifest_sha256=manifest.manifest_sha256,
        activation_id=activation.activation_id, documents=documents, members=members, drift=drift,
        adoption=None, status="valid" if not drift else "unadopted",
        coverage={m.name: m.coverage_through for m in members})
    if adoption is not None and adoption.manifest_sha256 == manifest.manifest_sha256:
        current = {(h.hunk_id, h.hunk_sha256) for h in drift}
        recorded = {(d.hunk, d.hunk_sha256) for d in adoption.drift}
        live_now = {d.name: d.live_sha256 for d in documents}
        if current == recorded and adoption.live_sha256 == live_now:
            baseline = baseline.model_copy(update={"adoption": adoption, "status": "adopted"})
    return baseline


# --------------------------------------------------------------------------- adoption

def parse_resolve(values: list[str] | None) -> dict[str, str]:
    """``HUNK=accept|reject`` arguments into a mapping; a malformed pair is a usage error."""
    out: dict[str, str] = {}
    for item in values or ():
        hunk, sep, disposition = item.partition("=")
        if not sep or not _HUNK_ID.match(hunk) or disposition not in DISPOSITIONS:
            raise DeltaRefusal(
                f"bad --resolve {item!r}; expected <document>#<n>=accept|reject", EXIT_USAGE)
        if hunk in out:
            raise DeltaRefusal(f"hunk {hunk} resolved twice", EXIT_USAGE)
        out[hunk] = disposition
    return out


def adopt(campaign_dir: Path | str, resolve: dict[str, str] | None = None) -> Adoption:
    """Write a NEW adoption record for the active generation (explicit; never implicit).

    Every drift hunk must be given a disposition; an unresolved or unknown hunk refuses and writes
    nothing.  Earlier adoption, generation and receipt files are never rewritten.
    """
    root = Path(campaign_dir).absolute()
    resolve = dict(resolve or {})
    baseline = bind(root)
    known = {h.hunk_id: h for h in baseline.drift}
    unknown = sorted(set(resolve) - set(known))
    if unknown:
        raise DeltaRefusal(
            "no such drift hunk: " + ", ".join(unknown)
            + (f"; current hunks: {', '.join(known)}" if known else "; there is no drift"), EXIT_STALE)
    bad = sorted(h for h, d in resolve.items() if d not in DISPOSITIONS)
    if bad:
        raise DeltaRefusal(f"disposition must be accept or reject: {', '.join(bad)}", EXIT_USAGE)
    unresolved = [h for h in known if h not in resolve]
    if unresolved:
        raise DeltaRefusal(
            "unresolved drift; resolve each hunk with --resolve <hunk>=accept|reject: "
            + ", ".join(unresolved), EXIT_REFUSAL)
    existing = _adoption_files(root, baseline.generation_id)
    revision = (existing[-1][0] + 1) if existing else 1
    record = Adoption(
        revision=revision, generation_id=baseline.generation_id,
        manifest_sha256=baseline.manifest_sha256, activation_id=baseline.activation_id,
        live_sha256={d.name: d.live_sha256 for d in baseline.documents},
        adopted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        drift=[HunkDisposition(hunk=h.hunk_id, hunk_sha256=h.hunk_sha256, disposition=resolve[h.hunk_id])
               for h in baseline.drift])
    target = baseline_dir(root) / f"adoption-{baseline.generation_id}-r{revision}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise DeltaRefusal(f"adoption revision already exists: {target.name}", EXIT_STALE)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(record.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(target)
    return record


def baseline_documents(baseline: GroundingBaseline, campaign_dir: Path | str) -> dict[str, bytes]:
    """Bytes of the four documents the delta edits against.

    Origin bytes, with each *accepted* drift hunk applied (a rejected hunk reverts to origin).
    Refuses while any drift is unreviewed.
    """
    if not baseline.usable:
        raise DeltaRefusal(
            "the baseline has unreviewed drift; run `delta baseline adopt --resolve <hunk>=accept|reject` first: "
            + ", ".join(h.hunk_id for h in baseline.drift), EXIT_REFUSAL)
    root = Path(campaign_dir).absolute()
    try:
        layout = inspect_layout(root)
        manifest = _read_manifest(root, baseline.generation_id)
        published = root / manifest.published_path
        accepted = {d.hunk for d in (baseline.adoption.drift if baseline.adoption else ())
                    if d.disposition == "accept"}
        out: dict[str, bytes] = {}
        for name in DOCUMENT_NAMES:
            origin = (published / f"{name}.md").read_bytes()
            live = (layout.live_dir / f"{name}.md").read_bytes()
            if origin == live:
                out[name] = origin
                continue
            a, b = _lines(origin), _lines(live)
            by_span = {(h.origin_start, h.origin_end, h.live_start, h.live_end): h
                       for h in baseline.drift if h.document == name}
            chunks: list[bytes] = []
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
                if tag == "equal":
                    chunks.extend(a[i1:i2])
                    continue
                hunk = by_span[(i1, i2, j1, j2)]
                chunks.extend(b[j1:j2] if hunk.hunk_id in accepted else a[i1:i2])
            out[name] = b"".join(chunks)
        return out
    except (PromotionError, OSError, KeyError) as exc:
        raise _refuse_promotion(exc) from exc


# --------------------------------------------------------------------------- claims custody

_CHAPTER_FILE = re.compile(r"^(\d{3,})-.*\.md$")
_SCENE_ENTRY = re.compile(r"^\d{3}\.\d{2}$")


def _custody_rows(campaign_dir: Path, manifest: GenerationManifest,
                  seen: tuple[str, ...] = ()) -> dict[int, tuple[str, str]]:
    """chapter -> (campaign-relative path, sha256) the baseline generation holds.

    Sources, all recorded rather than inferred from recency: the generation's own range manifest
    (``selected_range``), a legacy adoption's configured range (``grounding.yaml summary_native``
    ``out_root`` + ``range_since``/``range_until``), and summaries pinned as external dependencies.
    """
    return {c: (path, sha) for c, (path, sha, _gid) in _custody_rows_pinned_by(campaign_dir, manifest, seen).items()}


def _custody_rows_pinned_by(campaign_dir: Path, manifest: GenerationManifest,
                            seen: tuple[str, ...] = ()) -> dict[int, tuple[str, str, str]]:
    """``_custody_rows`` plus the id of the generation in the delta chain whose records pinned each row
    (spec 040: the stale-pin report names it).  The row values are exactly ``_custody_rows``'."""
    import yaml

    if manifest.generation_id in seen:
        raise DeltaRefusal("the delta baseline chain loops", EXIT_STALE)
    # a delta-published generation holds only its own range's summaries; follow its lineage back to the
    # generation(s) holding the rest (each hop digest-verified), then let this generation's own rows win
    parent = _delta_parent(campaign_dir, manifest)
    gid = manifest.generation_id
    rows: dict[int, tuple[str, str, str]] = (
        _custody_rows_pinned_by(campaign_dir, parent, (*seen, manifest.generation_id)) if parent is not None else {})
    for dep in manifest.external_dependencies:
        m = _CHAPTER_FILE.match(Path(dep.path).name)
        if m:
            rows[int(m.group(1))] = (dep.path, dep.sha256, gid)
    out_root = since = until = None
    if manifest.selected_range is not None:
        out_root, since, until = (manifest.selected_range.out_root, manifest.selected_range.since,
                                  manifest.selected_range.until)
    else:
        path = campaign_dir / "config" / "grounding.yaml"
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, yaml.YAMLError):
            data = {}
        section = (data or {}).get("summary_native") if isinstance(data, dict) else None
        if isinstance(section, dict):
            out_root, since, until = section.get("out_root"), section.get("range_since"), section.get("range_until")
    if out_root and isinstance(since, int) and isinstance(until, int):
        range_manifest = campaign_dir / out_root / f"ch{since:03d}-{until:03d}" / "manifest.json"
        try:
            files = json.loads(range_manifest.read_text(encoding="utf-8")).get("files", [])
        except (OSError, ValueError):
            files = []
        for item in files:
            if isinstance(item, dict) and isinstance(item.get("chapter"), int) \
                    and isinstance(item.get("path"), str) and isinstance(item.get("sha256"), str):
                rows[item["chapter"]] = (item["path"], item["sha256"], gid)
    return rows


def custody_resolver(baseline: GroundingBaseline, campaign_dir: Path | str):
    """An ``InheritedCustodyResolver`` built from the bound baseline (FR-016).

    ``(chapter, entry)`` resolves to the ``ContentIdentity`` of the baseline's summary for that chapter,
    or ``None`` when the baseline does not hold it (its support was removed or never inherited) or when
    a scene-id entry no longer appears in that chapter's text.  Unreviewed drift refuses first.
    """
    if not baseline.usable:
        raise DeltaRefusal("the baseline has unreviewed drift; adopt it before resolving custody", EXIT_REFUSAL)
    return custody_resolver_for_generation(campaign_dir, baseline.generation_id)


def custody_resolver_for_generation(campaign_dir: Path | str, generation_id: str):
    """The same resolver, keyed by the generation a delta lineage record names (used by the claims
    selection, which only has the lineage record)."""
    from pipelines.summary_native.promotion.models import ContentIdentity

    root = Path(campaign_dir).absolute()
    try:
        rows = _custody_rows(root, _read_manifest(root, generation_id))
    except (PromotionError, OSError, ValueError) as exc:
        raise _refuse_promotion(exc) from exc

    def resolve(chapter: int, entry: str) -> ContentIdentity | None:
        found = rows.get(chapter)
        if found is None:
            return None
        rel, digest = found
        try:
            data = (root / rel).read_bytes()
        except OSError:
            return None
        if _SCENE_ENTRY.match(entry.strip()) and entry.strip().encode("utf-8") not in data:
            return None
        return ContentIdentity(path=rel, sha256=digest, size=len(data))

    return resolve
