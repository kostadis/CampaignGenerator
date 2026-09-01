"""Deterministic d4-v1 evidence measurement; measurements never decide a Gate."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from campaignlib.narration_context import resolve_narration_guidance
from session_doc.voice_lint import (
    CHECKER_SCHEMA_VERSION,
    D4_CHECK_REGISTRY,
    MEASUREMENT_PROFILE,
    load_config,
)

from .models import (
    CampaignScope,
    MeasurementSnapshot,
    StateError,
    ValidationError,
    canonical_json,
    sha256_bytes,
)
from .storage import load_iteration, read_json, save_iteration, write_json


WORD_RE = re.compile(r"[\w'’-]+", re.UNICODE)
HEADING_RE = re.compile(r"^##\s+(.+?)(?:\s+[—–-]\s+.*)?\s*$")


def _eligible_lines(text: str) -> Iterable[tuple[int, str, str | None]]:
    section: str | None = None
    fenced = False
    frontmatter = text.startswith("---\n")
    for line_number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if frontmatter:
            if line_number > 1 and line.strip() == "---":
                frontmatter = False
            continue
        if fenced:
            continue
        heading = HEADING_RE.match(line)
        if heading:
            section = heading.group(1).strip()
            continue
        if line.lstrip().startswith("#") or not WORD_RE.search(line):
            continue
        yield line_number, line, section


def _occurrences(text: str, expression: re.Pattern[str], path: str, narrator: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line, section in _eligible_lines(text):
        for match in expression.finditer(line):
            rows.append({
                "path": path,
                "line": line_number,
                "section": section,
                "narrator": section or narrator,
                "matched": match.group(0),
            })
    return rows


def _budget(value: int, unit: str) -> dict[str, Any]:
    return {"operator": "<=", "value": value, "unit": unit}


def _check(
    key: str,
    scope: str,
    subject: str | None,
    occurrences: list[dict[str, Any]],
    budget: dict[str, Any] | None,
    *,
    reason: str | None = None,
    observed: int | None = None,
) -> dict[str, Any]:
    if reason is not None:
        verdict = "skipped"
        observed = None
    else:
        observed = len(occurrences) if observed is None else observed
        verdict = "ok" if budget is None or observed <= budget["value"] else "breach"
    return {
        "key": key,
        "scope": scope,
        "subject": subject,
        "observed": observed,
        "budget": budget,
        "verdict": verdict,
        "reason": reason,
        "occurrences": sorted(
            occurrences,
            key=lambda row: (row["path"], row["line"] or 0, row["narrator"] or "", row["matched"]),
        ),
    }


def _maximal_reuse(documents: list[tuple[str, str | None, str]]) -> list[dict[str, Any]]:
    phrase_sites: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    phrase_narrators: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for path, narrator, text in documents:
        for line_number, line, section in _eligible_lines(text):
            effective_narrator = section or narrator or "unknown"
            words = WORD_RE.findall(line)
            normalized = [word.casefold() for word in words]
            for size in range(3, min(12, len(words)) + 1):
                for start in range(0, len(words) - size + 1):
                    key = tuple(normalized[start:start + size])
                    phrase_narrators[key].add(effective_narrator)
                    phrase_sites[key].append({
                        "path": path,
                        "line": line_number,
                        "section": None,
                        "narrator": effective_narrator,
                        "matched": " ".join(words[start:start + size]),
                    })
    eligible = [key for key, narrators in phrase_narrators.items() if len(narrators) >= 2]
    maximal = []
    for key in eligible:
        if any(len(other) > len(key) and any(other[i:i + len(key)] == key for i in range(len(other) - len(key) + 1))
               for other in eligible):
            continue
        sites_by_identity: dict[tuple[str, int, str], dict[str, Any]] = {}
        for site in phrase_sites[key]:
            identity = (site["path"], site["line"], site["narrator"])
            sites_by_identity.setdefault(identity, site)
        sites = sorted(sites_by_identity.values(), key=lambda row: (row["path"], row["line"], row["narrator"]))
        maximal.append({
            "phrase": sites[0]["matched"],
            "word_count": len(key),
            "narrators": sorted(phrase_narrators[key]),
            "occurrences": sites,
        })
    return sorted(maximal, key=lambda row: (-row["word_count"], row["phrase"].casefold()))


def _load_corpus(scope: CampaignScope, manifest: dict[str, Any]) -> list[tuple[str, str | None, str, str]]:
    artifacts = {row["path"]: row for row in manifest.get("artifacts", [])}
    result = []
    for relative in manifest.get("measurement_corpus", []):
        artifact = artifacts.get(relative)
        if artifact is None:
            raise ValidationError(f"measurement corpus path is absent from manifest: {relative}")
        path = scope.session_root / relative
        raw = path.read_bytes()
        digest = sha256_bytes(raw)
        if digest != artifact.get("sha256"):
            raise StateError(f"source corpus drifted after collection: {relative}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"measurement corpus is not UTF-8: {relative}") from exc
        result.append((relative, artifact.get("narrator"), text, digest))
    if not result:
        raise ValidationError("trace manifest has no narration measurement corpus")
    return result


def _checks(corpus: list[tuple[str, str | None, str, str]], config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_narrator: dict[str, list[dict[str, Any]]] = defaultdict(list)
    filing_sections: set[tuple[str, str | None]] = set()
    legacy_key = {
        "shape_of": "the_shape_of",
        "portable_portrait": "with_the_x_of_a_man_who",
        "taxonomy": "the_way_x_do_when",
    }
    for definition in D4_CHECK_REGISTRY:
        if definition.key in {"filing_sections", "bookkeeping_per_narrator"}:
            if not by_narrator:
                for path, narrator, text, _ in corpus:
                    occurrences = _occurrences(text, definition.expression, path, narrator)
                    by_narrator[narrator or "unknown"].extend(occurrences)
                    filing_sections.update((row["path"], row["section"]) for row in occurrences)
            if definition.key == "filing_sections":
                if config.bookkeeping is None:
                    rows.append(_check(definition.key, "corpus", None, [], None, reason=config.skip_reason))
                else:
                    rows.append(_check(
                        definition.key, "corpus", None,
                        sorted((site for sites in by_narrator.values() for site in sites), key=lambda row: (row["path"], row["line"])),
                        _budget(config.bookkeeping.doc_sections_cap, "sections"),
                        observed=len(filing_sections),
                    ))
            else:
                if config.bookkeeping is None:
                    rows.append(_check(definition.key, "narrator", None, [], None, reason=config.skip_reason))
                else:
                    narrators = sorted(set(by_narrator) | set(config.bookkeeping.licensed) | set(config.bookkeeping.unlicensed))
                    for narrator in narrators:
                        rows.append(_check(
                            definition.key, "narrator", narrator, by_narrator.get(narrator, []),
                            _budget(config.bookkeeping.per_section_cap, "occurrences"),
                        ))
            continue
        for path, narrator, text, _ in corpus:
            occurrences = _occurrences(text, definition.expression, path, narrator)
            cap = 0 if definition.key == "em_dash" else config.cap_for(legacy_key[definition.key])
            rows.append(_check(definition.key, "document", path, occurrences, _budget(cap, definition.budget_unit)))
    return sorted(rows, key=lambda row: (row["key"], row["scope"], row["subject"] or ""))


def measure(scope: CampaignScope, phase: str, proposal_id: str | None = None) -> dict[str, Any]:
    if phase not in {"before", "after"}:
        raise ValidationError("measurement phase must be before or after")
    if (phase == "after") != bool(proposal_id):
        raise ValidationError("after measurement requires proposal-id; before forbids it")
    iteration = load_iteration(scope)
    manifest = read_json(scope.iteration_root / "trace-manifest.json")
    corpus = _load_corpus(scope, manifest)
    corpus_id = str(manifest.get("corpus_id", ""))
    if corpus_id != iteration.corpus_id:
        raise StateError("iteration and manifest corpus identities differ")
    guidance = resolve_narration_guidance(scope.campaign_root, require_rulebook=True)
    assert guidance.rulebook is not None
    config = load_config(scope.campaign_root / guidance.rulebook.path)
    if not config.readable:
        raise ValidationError("configured narration rulebook cannot be read")

    output = scope.iteration_root / "measurement-before.json"
    if phase == "after":
        proposal_root = scope.iteration_root / "proposals" / str(proposal_id)
        proposal = read_json(proposal_root / "proposal.json")
        if proposal.get("state") != "comparison_applied":
            raise StateError("after measurement requires an applied comparison")
        target = scope.campaign_root / str(proposal["target_path"])
        if sha256_bytes(target.read_bytes()) != proposal.get("after_sha256"):
            raise StateError("live target does not match comparison snapshot")
        baseline = read_json(scope.iteration_root / "measurement-before.json")
        if baseline.get("corpus_id") != corpus_id:
            raise StateError("after measurement must reuse the baseline corpus")
        output = proposal_root / "measurement-after.json"

    snapshot = MeasurementSnapshot(
        iteration_id=scope.iteration_id,
        phase=phase,
        proposal_id=proposal_id,
        corpus_id=corpus_id,
        guidance={
            "path": guidance.rulebook.path,
            "sha256": guidance.guidance_sha256,
            "checker_schema_version": CHECKER_SCHEMA_VERSION,
            "profile": MEASUREMENT_PROFILE,
        },
        documents=[
            {"path": path, "sha256": digest, "narrators": [narrator] if narrator else []}
            for path, narrator, _, digest in corpus
        ],
        checks=_checks(corpus, config),
        cross_narrator_reuse=_maximal_reuse([(path, narrator, text) for path, narrator, text, _ in corpus]),
    )
    encoded = canonical_json(snapshot.to_dict()).encode("utf-8")
    gate1_path = scope.iteration_root / "gate1.json"
    if phase == "before" and output.exists() and gate1_path.exists():
        gate1 = read_json(gate1_path)
        if gate1.get("rulings") and output.read_bytes() != encoded:
            raise StateError("baseline drift after a Gate 1 ruling requires a new iteration")
    write_json(output, snapshot.to_dict())
    if phase == "before":
        iteration.state = "measured_before"
        save_iteration(scope, iteration)
    else:
        proposal["state"] = "awaiting_gate2"
        write_json(scope.iteration_root / "proposals" / str(proposal_id) / "proposal.json", proposal)
        iteration.state = "awaiting_gate2"
        iteration.active_proposal_id = proposal_id
        save_iteration(scope, iteration)
    return {
        "phase": phase,
        "proposal_id": proposal_id,
        "artifact": output.relative_to(scope.session_root).as_posix(),
        "artifact_sha256": sha256_bytes(output.read_bytes()),
        "corpus_id": corpus_id,
        "breaches": sum(1 for row in snapshot.checks if row["verdict"] == "breach"),
    }
