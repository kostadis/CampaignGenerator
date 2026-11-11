"""Preserved legacy document structure for checked deltas; full synthesis stays strict."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pipelines.summary_native.outline import check_outline, load_outline
from pipelines.summary_native.promotion.models import GenerationManifest
from pipelines.summary_native.review.models import canonical_digest
from .grounding_check import check_headings, check_tables
from .grounding_edits import edits_dir
from .lineage import DeltaLineageRecord, delta_record_problems

_HEADER = re.compile(r"\A<!-- summary_native draft [^\n]*-->\n")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(root: Path, relative: str) -> bytes:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe delta contract path")
    cursor = root
    for part in path.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("symlink in delta contract path")
    return cursor.read_bytes()


def preserved_outline_problems(document: str, baseline: bytes, candidate: bytes) -> list[str]:
    headings = load_outline(document)
    normalized = _HEADER.sub("", candidate.decode(), count=1)
    problems = [p for p in check_outline(normalized, headings)
                if p.startswith(("missing heading:", "empty body:"))]
    findings = check_headings(document, baseline, candidate) + check_tables(document, baseline, candidate)
    problems += [f.detail for f in findings if f.severity == "blocking"]
    def order(value: str) -> list[str]:
        return [line.rstrip() for line in value.splitlines() if line.rstrip() in headings]
    if order(baseline.decode()) != order(normalized):
        problems.append("required headings changed from the inherited baseline order")
    return problems


def _legacy_candidate(root: Path, bundle, document: str, text: str) -> tuple[bytes, bytes, str] | None:
    """Return the pinned baseline, checked candidate and plan, or no legacy exception.

    The exception requires pinned baseline bytes AND the exact checked native candidate.
    It never accepts an arbitrary preamble just because a record says `kind: delta`.
    Required sections, their inherited order, heading preservation, tables, pointer
    checks, exact sign-offs, custody and the publication check remain enforced.
    """
    for identity in bundle.retained_records:
        try:
            record_bytes = _read(root, identity.path)
            if _sha(record_bytes) != identity.sha256:
                continue
            record = json.loads(record_bytes)
            if record.get("kind") != "delta":
                continue
            lineage = DeltaLineageRecord.model_validate(record)
            if not all(re.fullmatch(r"[A-Za-z0-9_-]+", value)
                       for value in (lineage.plan_ref, lineage.baseline.generation_id)):
                continue
            if delta_record_problems(lineage, root):
                continue
            member = next(m for m in lineage.members if m.name == document)
            candidate_path = edits_dir(root, lineage.plan_ref) / "candidates" / f"{document}.md"
            candidate = _read(root, candidate_path.relative_to(root).as_posix())
            normalized = _HEADER.sub("", candidate.decode(), count=1)
            if _sha(candidate) != member.sha256 or _HEADER.sub("", text, count=1) != normalized:
                continue
            if member.mode == "produced":
                check = json.loads(_read(root, member.check_ref))
                if check.get("passed") is not True or check.get("candidate_sha256", {}).get(document) != member.sha256:
                    continue
            generation = root / "docs/grounding/generations" / lineage.baseline.generation_id
            manifest_bytes = _read(root, (generation / "manifest.json").relative_to(root).as_posix())
            parsed_manifest = GenerationManifest.model_validate_json(manifest_bytes)
            if (parsed_manifest.manifest_sha256 != lineage.baseline.manifest_sha256
                    or canonical_digest(parsed_manifest, exclude_fields=frozenset({"manifest_sha256"}))
                    != parsed_manifest.manifest_sha256):
                continue
            manifest = json.loads(manifest_bytes)
            if manifest.get("kind") not in {"legacy_adoption", "delta"}:
                continue
            baseline = _read(root, (generation / "published" / f"{document}.md").relative_to(root).as_posix())
            bound = next(m for m in manifest["members"] if m["path"] == f"{document}.md")
            if _sha(baseline) != bound["sha256"]:
                continue
            return baseline, candidate, lineage.plan_ref
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            continue
    return None


def legacy_delta_outline(root: Path, bundle, document: str, text: str) -> list[str] | None:
    verified = _legacy_candidate(root, bundle, document, text)
    if verified is None:
        return None
    baseline, candidate, _plan = verified
    if not check_outline(baseline.decode(), load_outline(document)):
        return None  # No legacy shape to inherit: keep the strict contract.
    return preserved_outline_problems(document, baseline, candidate)


def legacy_delta_paths(root: Path, bundle, document: str, path: Path) -> list[str] | None:
    """Use pinned bundle paths when the adopted document never had an inline contract.

    This validation view is never written to the approved document. An existing
    inline contract, including a damaged one, must pass the ordinary checker.
    """
    from pipelines.summary_native import pointers, state_sections
    from .plan import load_plan, plans_dir

    text = path.read_text(encoding="utf-8")
    verified = _legacy_candidate(root, bundle, document, text)
    if verified is None:
        return None
    baseline, candidate, plan_ref = verified
    if "summary_native pointers:" in baseline.decode() or "summary_native pointers:" in candidate.decode():
        return None
    plan = load_plan(plans_dir(root), plan_ref)
    parents = {Path(s.path).parent for s in plan.sources}
    if len(parents) != 1:
        return ["legacy reading contract requires one explicit summaries directory"]
    summaries = next(iter(parents)).relative_to(root).as_posix()
    paths = {"reference": "reference", "timeline": "canon_events_timeline.md", "summaries": summaries}
    refs = ", ".join(f"`reference/{kind}.md`" for kind in state_sections.CONTRACT_REFERENCES[document])
    view = f'> <!-- summary_native pointers: {json.dumps(paths)} -->\n> - Every checked note, by subject: {refs}\n'
    if document == "world_state":
        view += '>   Every event, in order: `canon_events_timeline.md`\n'
    return pointers.check_text_paths(view + text, path, root)
