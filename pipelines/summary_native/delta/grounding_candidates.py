"""Candidate documents and the delta lineage record for a decided grounding plan (spec 039, T037).

The host step between ``grounding check`` and ``grounding preview``.  Given the baseline documents,
the reconstructed candidates (approved proposals only) and the deterministic check report, it writes

* ``candidates/<doc>.md``  one file per grounding document, byte-exact, and
* ``lineage.json``         a :class:`DeltaLineageRecord`: a bundle member whose bytes equal the
                           baseline generation's published bytes is *inherited* (custody = the
                           generation's published path and digest); any other member is *produced*,
                           ``check_ref`` is the check report and ``check_status`` is ``passed`` only
                           when the deterministic check passed.  A model consistency finding is
                           advisory and can neither set nor withhold ``passed`` (FR-015).

No model call is made here, and no synthetic full-corpus ``synth`` record is written (FR-021).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from .baseline import DOCUMENT_NAMES, GroundingBaseline, _read_manifest
from .errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .grounding_edits import edits_dir
from .lineage import (
    BaselineRef, CustodyRef, DeltaLineageRecord, LineageMember, RebaseBlock, load_lineage, save_lineage,
)

CANDIDATES_DIR = "candidates"
LINEAGE_FILE = "lineage.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_candidates(campaign_dir: Path | str, plan_id: str, candidate: Mapping[str, bytes]) -> dict[str, Path]:
    directory = edits_dir(campaign_dir, plan_id) / CANDIDATES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    written = {}
    for name in sorted(candidate):
        target = directory / f"{name}.md"
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(candidate[name])
        tmp.replace(target)
        written[name] = target
    return written


def build_lineage(campaign_dir: Path | str, plan_id: str, baseline: GroundingBaseline,
                  candidate: Mapping[str, bytes], *, check_ref: str, check_passed: bool,
                  rebase: RebaseBlock | None = None) -> DeltaLineageRecord:
    root = Path(campaign_dir).absolute()
    manifest = _read_manifest(root, baseline.generation_id)
    members: list[LineageMember] = []
    for name in DOCUMENT_NAMES:
        data = candidate[name]
        rel = f"{manifest.published_path}/{name}.md"
        published = _sha((root / rel).read_bytes())
        if _sha(data) == published:
            members.append(LineageMember(name=name, mode="inherited", sha256=published,
                                         custody_ref=CustodyRef(path=rel, sha256=published)))
        else:
            members.append(LineageMember(name=name, mode="produced", sha256=_sha(data), check_ref=check_ref,
                                         check_status="passed" if check_passed else "failed"))
    documents = {f"{name}.md" for name in DOCUMENT_NAMES}
    for item in sorted(manifest.members, key=lambda m: m.path):
        if item.path in documents:
            continue
        members.append(LineageMember(
            name=item.path, mode="inherited", sha256=item.sha256,
            custody_ref=CustodyRef(path=f"{manifest.published_path}/{item.path}", sha256=item.sha256)))
    for record in sorted(manifest.retained_records, key=lambda r: r.retained_path):
        path = f"{Path(manifest.published_path).parent.as_posix()}/{record.retained_path}"  # beside published/
        if (root / path).is_file():
            members.append(LineageMember(name=f"retained/{record.retained_path}", mode="inherited",
                                         sha256=record.sha256, custody_ref=CustodyRef(path=path, sha256=record.sha256)))
    return DeltaLineageRecord(
        plan_ref=plan_id, baseline=BaselineRef(generation_id=baseline.generation_id,
                                               manifest_sha256=baseline.manifest_sha256),
        members=members, rebase=rebase)


def materialize(campaign_dir: Path | str, plan_id: str, baseline: GroundingBaseline,
                candidate: Mapping[str, bytes], *, check_path: str, check_passed: bool,
                rebase: RebaseBlock | None = None) -> DeltaLineageRecord:
    """Write the candidates and lineage; return the lineage.  ``check_path`` is campaign-relative.

    ``rebase`` (spec 040) is the source-custody block of a rebase plan's lineage; ``None`` leaves the record
    byte-identical to the one a delta plan has always produced."""
    write_candidates(campaign_dir, plan_id, candidate)
    lineage = build_lineage(campaign_dir, plan_id, baseline, candidate, check_ref=check_path,
                            check_passed=check_passed, rebase=rebase)
    save_lineage(lineage, edits_dir(campaign_dir, plan_id) / LINEAGE_FILE)
    return lineage


def check_binding_problems(campaign_dir: Path | str, candidates: Mapping[str, bytes],
                           lineage: DeltaLineageRecord) -> list[str]:
    """Each produced member's check report must name the exact candidate bytes now on disk."""
    import json

    root = Path(campaign_dir).absolute()
    problems: list[str] = []
    for member in lineage.members:
        if member.mode != "produced" or member.check_status != "passed":
            continue
        report_path = root / (member.check_ref or "")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"{member.name}: check report {member.check_ref} is missing or unreadable")
            continue
        recorded = (report.get("candidate_sha256") or {}).get(member.name)
        data = candidates.get(f"{member.name}.md")
        actual = _sha(data) if data is not None else None
        if recorded != actual or member.sha256 != actual:
            problems.append(f"{member.name}: the check report does not describe the candidate bytes "
                            "(candidate changed after the check); run `delta grounding check` again")
    return problems


def require_check_binding(campaign_dir: Path | str, candidates: Mapping[str, bytes],
                          lineage: DeltaLineageRecord) -> None:
    problems = check_binding_problems(campaign_dir, candidates, lineage)
    if problems:
        raise DeltaRefusal("; ".join(problems), EXIT_STALE)


# --------------------------------------------------------------------------- staging for promotion

_HEADER = re.compile(r"\A<!-- summary_native draft [^\n]*-->\n")
REQUEST_FILE = "publish_request.json"
#: Written by ``stage_for_promotion`` into every range directory it creates; its presence is the only
#: thing that lets a later delta restage there (an existing full build's directory has none).
STAGED_MARKER = ".delta-staged.json"


def _range_name(since: int, until: int) -> str:
    return f"ch{since:03d}-{until:03d}"


def _strip_header(data: bytes) -> bytes:
    return _HEADER.sub("", data.decode("utf-8"), count=1).encode("utf-8")


def stage_for_promotion(campaign_dir: Path | str, plan, *, review: str | None = None,
                        claims_report: str | None = None, request_id: str | None = None) -> dict:
    """Install the checked candidates where the real promotion path reads them (FR-016, FR-021).

    Layout (the one ``promotion.manifest.build_bundle_selection`` reads), for the delta's OWN selected
    chapters ``S..U`` (they must be contiguous, so the range label claims nothing the delta did not select)::

        <out_root>/chSSS-UUU/manifest.json                 the selected chapters only
        <out_root>/chSSS-UUU/state/drafts/<doc>.draft.md   candidate bytes; only the draft header comment is
                                                           rewritten (honest range, record pointer)
        <out_root>/chSSS-UUU/state/drafts/canon_events_timeline.md, reference/**
                                                           copied byte-for-byte from the baseline generation
        <out_root>/chSSS-UUU/state/runs/delta-<plan>-<doc>/record.json
                                                           the delta lineage record (kind "delta"), the
                                                           run-record pointer; NOT a synth record

    ``publish_request.json`` is written for ``default_publisher``.  Nothing here calls a model.
    """
    from pipelines.summary_native import schema
    from pipelines.summary_native.promotion.errors import PromotionError
    from pipelines.summary_native.promotion.settings import load_settings, resolve_out_root

    root = Path(campaign_dir).absolute()
    base = edits_dir(root, plan.plan_id)
    candidates = {p.name: p.read_bytes() for p in sorted((base / CANDIDATES_DIR).glob("*.md"))}
    if not candidates:
        raise DeltaRefusal("no checked candidates to stage; run `delta grounding check`", EXIT_USAGE)
    lineage_path = base / LINEAGE_FILE
    if not lineage_path.is_file():
        raise DeltaRefusal("no lineage record; run `delta grounding check`", EXIT_USAGE)
    lineage = load_lineage(lineage_path)
    require_check_binding(root, candidates, lineage)
    rebase = plan.kind == "rebase"
    if rebase:
        # a custody rebase re-pins only the chapters its decisions kept; the range label is their span and
        # `range.gaps` names every chapter in the span it did not select (research R3)
        if lineage.rebase is None:
            raise DeltaRefusal("a rebase plan's lineage has no rebase block; run `delta grounding check`", EXIT_USAGE)
        chapters = sorted(s.chapter for s in lineage.rebase.sources)
        gaps = [c for c in range(chapters[0], chapters[-1] + 1) if c not in set(chapters)]
    else:
        chapters = sorted({s.chapter for s in plan.sources})
        gaps = []
        if chapters != list(range(chapters[0], chapters[-1] + 1)):
            raise DeltaRefusal(
                f"the selected chapters {chapters} are not contiguous; a promotion range would claim chapters "
                "the delta did not select. Plan contiguous chapters (or one delta per run).", EXIT_USAGE)
    since, until = chapters[0], chapters[-1]
    try:
        config_path = root / "config" / "config.yaml"
        settings = load_settings(str(config_path))
        out_root = resolve_out_root(settings, None)
    except PromotionError as exc:
        raise DeltaRefusal(f"cannot resolve the promotion output root: {exc}", EXIT_USAGE) from exc
    range_dir = root / out_root / _range_name(since, until)
    if range_dir.exists() and not (range_dir / STAGED_MARKER).is_file():
        raise DeltaRefusal(
            f"{range_dir.relative_to(root)} already exists and was not staged by a delta; staging would overwrite "
            "its manifest and drafts. Select chapters whose range directory is new.", EXIT_REFUSAL)
    state = range_dir / "state"
    drafts = schema.draft_dir(range_dir, "world_state")
    manifest_files = []
    for source in (lineage.rebase.sources if rebase else plan.sources):
        try:
            rel = source.path if rebase else Path(source.path).absolute().relative_to(root).as_posix()
        except ValueError as exc:
            raise DeltaRefusal(f"selected source is outside the campaign: {source.path}", EXIT_USAGE) from exc
        manifest_files.append({"path": rel, "chapter": source.chapter,
                               "sha256": source.new_sha256 if rebase else source.sha256})
    record_bytes = lineage_path.read_bytes()
    record_sha = _sha(record_bytes)
    _put(range_dir / STAGED_MARKER, (json.dumps({"delta_staged": True, "plan": plan.plan_id}, sort_keys=True) + "\n").encode())
    manifest = {"kind": "summary_native", "schema": 1, "complete": True,
                "range": {"since": since, "until": until, "gaps": gaps},
                "files": sorted(manifest_files, key=lambda f: f["chapter"])}
    if rebase:
        manifest["kind"] = "custody_rebase"
    _put(range_dir / "manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    for name in DOCUMENT_NAMES:
        # one record path per document (a bundle's paths are unique), all with the same lineage bytes
        record_rel = f"runs/delta-{plan.plan_id}-{name}/record.json"
        _put(state / record_rel, record_bytes)
        body = _strip_header(candidates[f"{name}.md"])
        header = (f"<!-- summary_native draft | doc: {name} | range: {_range_name(since, until)} | "
                  f"record: {record_rel} | record sha256: {record_sha} | delta: {plan.plan_id} -->\n")
        _put(drafts / f"{name}.draft.md", header.encode() + body)
    # inherited members travel by custody: copy the baseline generation's bytes, verified against the lineage
    inherited = {m.name: m for m in lineage.members if m.mode == "inherited" and m.custody_ref}
    for name, member in inherited.items():
        if name in DOCUMENT_NAMES or name.startswith("retained/"):
            continue
        source = root / member.custody_ref.path
        data = source.read_bytes()
        if _sha(data) != member.custody_ref.sha256:
            raise DeltaRefusal(f"baseline custody bytes changed: {member.custody_ref.path}", EXIT_STALE)
        _put(drafts / name, data)
    request_path = base / REQUEST_FILE
    previous = json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else {}
    request = {"config": str(config_path), "out_root": out_root, "since": since, "until": until,
               "request_id": request_id or previous.get("request_id") or f"delta-{plan.plan_id}"}
    for key, value in (("review", review or previous.get("review")),
                       ("check_report", claims_report or previous.get("check_report"))):
        if value:
            request[key] = value
    _put(request_path, (json.dumps(request, indent=2, sort_keys=True) + "\n").encode())
    return {"range": _range_name(since, until), "drafts": str(drafts.relative_to(root)),
            "record": str((state / f"runs/delta-{plan.plan_id}-<doc>/record.json").relative_to(root)),
            "request": request}


def _put(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == data:
        return
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
