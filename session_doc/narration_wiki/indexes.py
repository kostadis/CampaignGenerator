"""Pattern-page parsing, tier ownership, indexes, and companion capability checks."""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .models import (
    CampaignScope,
    CompanionCapabilityManifest,
    Gate1Ruling,
    PatternDraft,
    ValidationError,
    normalize_slug,
    sha256_file,
)


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)
SECTION_RE = re.compile(
    r"(?:^|\n)##\s+Problem\s*\n(?P<problem>.*?)"
    r"(?:\n##\s+Root Cause\s*\n)(?P<root>.*?)"
    r"(?:\n##\s+Corrective Strategy\s*\n)(?P<strategy>.*?)"
    r"(?:\n##\s+Evidence\s*\n)(?P<evidence>.*)\Z",
    re.S | re.I,
)
INDEX_LINK_RE = re.compile(r"\[[^\]]+\]\((?:\./)?patterns/([a-z0-9-]+)\.md\)")


def _frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValidationError(f"pattern page is missing: {path.name}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(f"pattern page cannot be read: {path.name}") from exc
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValidationError(f"pattern page needs YAML frontmatter: {path.name}")
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValidationError(f"invalid pattern frontmatter in {path.name}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ValidationError(f"pattern frontmatter must be an object: {path.name}")
    return metadata, match.group(2)


def parse_pattern_page(path: Path, *, expected_slug: str | None = None, draft: bool = False) -> PatternDraft:
    metadata, body = _frontmatter(path)
    sections = SECTION_RE.search(body)
    if not sections:
        raise ValidationError(
            f"pattern {path.name} requires Problem, Root Cause, Corrective Strategy, and Evidence sections"
        )
    slug = normalize_slug(str(metadata.get("slug") or path.stem))
    if expected_slug and slug != normalize_slug(expected_slug):
        raise ValidationError(f"pattern slug does not match its filename: {path.name}")
    evidence = metadata.get("evidence") or [line.strip("- ") for line in sections["evidence"].splitlines() if line.strip()]
    if not isinstance(evidence, list) or not evidence:
        raise ValidationError(f"pattern {slug} needs at least one evidence reference")
    problem = sections["problem"].strip()
    root = sections["root"].strip()
    strategy = sections["strategy"].strip()
    if len(problem.split()) < 3 or len(root.split()) < 3 or len(strategy.split()) < 3:
        raise ValidationError(f"pattern {slug} must explain a lesson, not only name a phrase")
    conflicts = metadata.get("conflict_ids") or []
    if not isinstance(conflicts, list):
        raise ValidationError(f"pattern {slug} conflict_ids must be a list")
    return PatternDraft(
        slug=slug,
        title=str(metadata.get("title") or slug.replace("-", " ").title()),
        problem=problem,
        root_cause=root,
        corrective_strategy=strategy,
        evidence=evidence,
        conflict_ids=sorted(str(item) for item in conflicts),
        proposed_tier=str(metadata.get("proposed_tier") or metadata.get("tier") or "campaign"),
        mentions_campaign_identity=bool(metadata.get("mentions_campaign_identity", False)),
        status=str(metadata.get("status") or ("pending" if draft else "confirmed")),
    )


def render_confirmed_pattern(
    draft: PatternDraft,
    ruling: Gate1Ruling,
    *,
    status: str = "confirmed",
) -> str:
    metadata = {
        "baseline_sha256": ruling.baseline.measurement_sha256,
        "conflict_ruling_refs": list(ruling.conflict_ruling_refs),
        "evidence": draft.evidence,
        "gate1": {
            "iteration_id": ruling.iteration_id,
            "ruling": ruling.ruling,
        },
        "slug": draft.slug,
        "status": status,
        "tier": ruling.tier,
        "title": draft.title,
    }
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=True).strip()
    evidence = "\n".join(f"- {item}" for item in draft.evidence)
    return (
        f"---\n{frontmatter}\n---\n\n# {draft.title}\n\n"
        f"## Problem\n{draft.problem}\n\n"
        f"## Root Cause\n{draft.root_cause}\n\n"
        f"## Corrective Strategy\n{draft.corrective_strategy}\n\n"
        f"## Evidence\n{evidence}\n"
    )


def _summary(value: str, words: int = 24) -> str:
    flattened = " ".join(value.split())
    parts = flattened.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def _page_rows(patterns_root: Path) -> list[PatternDraft]:
    if not patterns_root.is_dir():
        return []
    rows = []
    for path in sorted(patterns_root.glob("*.md"), key=lambda item: item.name):
        rows.append(parse_pattern_page(path, expected_slug=path.stem))
    return rows


def render_campaign_index(
    scope: CampaignScope,
    *,
    pending: tuple[str, str] | None = None,
) -> str:
    rows = _page_rows(scope.campaign_wiki_root / "patterns")
    if pending:
        slug, page = pending
        temporary = scope.iteration_root / f".{slug}.index-preview.md"
        # Parse without writing a preview file by duplicating the validated
        # draft already loaded by the caller from the pending page text.
        metadata_match = FRONTMATTER_RE.match(page)
        section_match = SECTION_RE.search(metadata_match.group(2) if metadata_match else "")
        if not metadata_match or not section_match:
            raise ValidationError("pending campaign pattern is malformed")
        metadata = yaml.safe_load(metadata_match.group(1)) or {}
        rows.append(PatternDraft(
            slug=slug,
            title=str(metadata.get("title") or slug),
            problem=section_match["problem"].strip(),
            root_cause=section_match["root"].strip(),
            corrective_strategy=section_match["strategy"].strip(),
            evidence=list(metadata.get("evidence") or ["Gate 1 evidence"]),
            status="accepted",
        ))
    by_slug: dict[str, PatternDraft] = {}
    for row in rows:
        if row.slug in by_slug:
            raise ValidationError(f"duplicate campaign pattern slug: {row.slug}")
        by_slug[row.slug] = row
    lines = ["# Narration Wiki", "", "<!-- narration-wiki:index tier=campaign -->", ""]
    for slug, row in sorted(by_slug.items()):
        lines.append(
            f"- [{row.title}](patterns/{slug}.md) — "
            f"**Problem:** {_summary(row.problem)} "
            f"**Root cause:** {_summary(row.root_cause)} "
            f"**Fix:** {_summary(row.corrective_strategy)}"
        )
    return "\n".join(lines) + "\n"


def load_companion_capability(portable_root: Path) -> dict[str, Any]:
    path = portable_root / "capabilities.yaml"
    if not path.is_file():
        return {
            "present": False,
            "compatible": False,
            "reason": "capabilities.yaml is missing",
            "source_repository": None,
            "source_revision": None,
            "capabilities": [],
            "manifest_sha256": None,
        }
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValidationError("capability manifest must be an object")
        manifest = CompanionCapabilityManifest.from_mapping(loaded)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
        return {
            "present": True,
            "compatible": False,
            "reason": str(exc),
            "source_repository": None,
            "source_revision": None,
            "capabilities": [],
            "manifest_sha256": sha256_file(path),
        }
    return {
        "present": True,
        "compatible": True,
        "reason": None,
        "source_repository": manifest.source_repository,
        "source_revision": manifest.source_revision,
        "capabilities": list(manifest.capabilities),
        "manifest_sha256": sha256_file(path),
    }


def _audit_tier(root: Path, tier: str) -> tuple[dict[str, PatternDraft], list[str]]:
    pages: dict[str, PatternDraft] = {}
    problems: list[str] = []
    patterns = root / "patterns"
    if patterns.is_dir():
        for path in sorted(patterns.glob("*.md"), key=lambda item: item.name):
            try:
                draft = parse_pattern_page(path, expected_slug=path.stem)
                metadata, _ = _frontmatter(path)
                if metadata.get("tier") != tier:
                    problems.append(f"{tier}: tier mismatch in {path.name}")
                if metadata.get("status") != "confirmed":
                    problems.append(f"{tier}: unresolved promotion state in {path.name}")
                if draft.slug in pages:
                    problems.append(f"{tier}: duplicate slug {draft.slug}")
                pages[draft.slug] = draft
            except ValidationError as exc:
                problems.append(f"{tier}: {exc}")
    index = root / "index.md"
    links: list[str] = []
    if index.is_file():
        try:
            links = INDEX_LINK_RE.findall(index.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{tier}: index cannot be read: {exc}")
    elif pages:
        problems.append(f"{tier}: index.md is missing")
    for slug in links:
        if slug not in pages:
            problems.append(f"{tier}: broken index link for {slug}")
    for slug in pages:
        if slug not in links:
            problems.append(f"{tier}: page {slug} is absent from index")
    if len(links) != len(set(links)):
        problems.append(f"{tier}: duplicate index slug")
    return pages, problems


def index_check(scope: CampaignScope) -> dict[str, Any]:
    campaign, problems = _audit_tier(scope.campaign_wiki_root, "campaign")
    dependency = load_companion_capability(scope.portable_root)
    portable: dict[str, PatternDraft] = {}
    if dependency["compatible"]:
        portable, portable_problems = _audit_tier(scope.portable_root, "portable")
        problems.extend(portable_problems)
    collisions = sorted(set(campaign) & set(portable))
    problems.extend(f"cross-tier duplicate slug: {slug}" for slug in collisions)
    pending = []
    promotions = scope.iteration_root / "portable-promotions"
    if promotions.is_dir():
        for path in sorted(promotions.glob("*.md"), key=lambda item: item.name):
            if path.stem not in portable:
                pending.append(path.stem)
    if pending:
        problems.extend(f"pending portable synchronization: {slug}" for slug in pending)
    return {
        "valid": not problems,
        "problems": sorted(problems),
        "campaign_slugs": sorted(campaign),
        "portable_slugs": sorted(portable),
        "pending_portable_sync": pending,
        "dependency": dependency,
    }


def visible_confirmed_slugs(scope: CampaignScope) -> set[str]:
    result = index_check(scope)
    # Index problems do not silently grant eligibility.  Valid individual
    # confirmed pages remain visible when only the companion dependency is absent.
    return set(result["campaign_slugs"]) | set(result["portable_slugs"])
