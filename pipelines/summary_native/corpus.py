"""Deterministic evidence corpus: chronology, memorable moments, dossiers, manifest.

Everything here is a pure restatement of what the summaries declare — no model,
no similarity. Identical input gives byte-identical output (research R5): files
and dossiers are sorted, JSON uses sorted keys, YAML keeps declared key order,
nothing carries a timestamp or an absolute path, and every write is atomic.

Grouping is a parameter: ``grouper(category, heading) -> (canonical,
grouped_by)``. The default groups identical heading text (after strip) within a
category only; a later story swaps in exact same-type registry aliases.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from campaignlib.util import atomic_write_text
from pipelines.summary_native import parse, schema
from pipelines.summary_native.validate import ValidationReport

Grouper = Callable[[str, str], "tuple[str, list[str]]"]

REPORT_FILES = ("validation_report.md", "validation_report.json")
GENERATED_FILES = ("chronology.md", "memorable_moments.md", "other_sections.md", "manifest.json")
GENERATED_DIRS = ("dossiers",)
ENSEMBLE_DIRS = ("state_dossiers", "merged_dossiers")
CATEGORY_TITLES = {cat: sec for sec, cat in schema.ENTITY_CATEGORIES.items()}
CATEGORIES = tuple(schema.ENTITY_CATEGORIES.values())


class CorpusError(Exception):
    """A refusal to read or write a corpus location (CLI exit 2)."""


def identity_grouper(category: str, heading: str) -> tuple[str, list[str]]:
    return heading.strip(), []


# ── Guards ──────────────────────────────────────────────────────────────────


def _read_manifest(range_dir: Path) -> dict | None:
    mp = range_dir / "manifest.json"
    if not mp.is_file():
        return None
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CorpusError(f"{range_dir}: manifest.json is unreadable ({e})") from e
    return data if isinstance(data, dict) else {}


def check_not_foreign(range_dir: Path) -> dict | None:
    """Refuse a directory holding another corpus. Returns the manifest if ours."""
    if not range_dir.exists():
        return None
    if not range_dir.is_dir():
        raise CorpusError(f"{range_dir}: not a directory")
    for name in ("merged.json", *ENSEMBLE_DIRS):
        if (range_dir / name).exists():
            raise CorpusError(
                f"{range_dir}: holds ensemble artifacts ({name}); "
                "summary-native and ensemble corpora must never be mixed"
            )
    for pat in ("facts_*.json", "extract_*.md"):
        if any(range_dir.glob(pat)):
            raise CorpusError(
                f"{range_dir}: holds ensemble artifacts ({pat}); "
                "summary-native and ensemble corpora must never be mixed"
            )
    manifest = _read_manifest(range_dir)
    if manifest is not None:
        if manifest.get("kind") != "summary_native":
            raise CorpusError(
                f"{range_dir}: manifest.json has kind {manifest.get('kind')!r}, "
                "not 'summary_native'"
            )
        return manifest
    extra = sorted(p.name for p in range_dir.iterdir() if p.name not in REPORT_FILES)
    if extra:
        raise CorpusError(
            f"{range_dir}: is not empty and has no summary-native manifest "
            f"(found: {', '.join(extra)})"
        )
    return None


def guard_out_dir(range_dir: Path, force: bool) -> None:
    """Refuse an unsafe range directory; with ``force`` clear our own old output."""
    range_dir = Path(range_dir)
    manifest = check_not_foreign(range_dir)
    if manifest is None:
        return
    if not force:
        raise CorpusError(
            f"{range_dir}: a summary-native corpus already exists; pass --force to rewrite it"
        )
    for name in GENERATED_FILES:
        (range_dir / name).unlink(missing_ok=True)
    for name in GENERATED_DIRS:
        shutil.rmtree(range_dir / name, ignore_errors=True)


# ── Observations & dossiers ─────────────────────────────────────────────────


@dataclass(frozen=True)
class Observation:
    category: str
    heading: str
    canonical: str
    grouped_by: tuple[str, ...]
    chapter: int
    source_file: str
    source_scene_id: str | None
    line: int
    body: str


def build_observations(
    files: list[parse.ParsedFile], grouper: Grouper = identity_grouper
) -> list[Observation]:
    out: list[Observation] = []
    for pf in sorted(files, key=lambda f: (f.prefix_chapter, f.path)):
        for e in pf.entities:
            canonical, by = grouper(e.category, e.heading)
            out.append(
                Observation(
                    category=e.category,
                    heading=e.heading,
                    canonical=canonical,
                    grouped_by=tuple(by),
                    chapter=pf.prefix_chapter,
                    source_file=pf.path,
                    source_scene_id=e.source_scene_id,
                    line=e.line,
                    body=e.body,
                )
            )
    return out


def _attach(body: str) -> str:
    """Body exactly as written, with one blank line before it and a final newline."""
    lead = "" if body.startswith("\n") else "\n"
    tail = "" if body.endswith("\n") else "\n"
    return lead + body + tail


def _slug(text: str) -> str:
    return re.sub(r"\W+", "_", text.casefold()).strip("_")


def _group_dossiers(obs: list[Observation]) -> list[tuple[str, str, list[Observation]]]:
    groups: dict[tuple[str, str], list[Observation]] = {}
    for o in obs:
        groups.setdefault((o.category, o.canonical), []).append(o)
    ordered = sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1].casefold(), kv[0][1]))
    return [
        (cat, subj, sorted(lst, key=lambda o: (o.chapter, o.line, o.source_file)))
        for (cat, subj), lst in ordered
    ]


def dossier_filenames(groups: list[tuple[str, str, list[Observation]]]) -> list[str]:
    """``<category>_<slug>.md``; a colliding stem gets ``_`` + sha256(category NUL subject)[:8]."""
    stems = [f"{cat}_{_slug(subj) or 'unnamed'}" for cat, subj, _ in groups]
    counts: dict[str, int] = {}
    for s in stems:
        counts[s] = counts.get(s, 0) + 1
    names = []
    for (cat, subj, _), stem in zip(groups, stems):
        if counts[stem] > 1:
            stem += "_" + hashlib.sha256(f"{cat}\0{subj}".encode()).hexdigest()[:8]
        names.append(stem + ".md")
    return names


def render_dossier(category: str, subject: str, obs: list[Observation]) -> str:
    chapters = [o.chapter for o in obs]
    fm: dict = {
        "subject": subject,
        "type": category,
        "n_facts": len(obs),
        "chapters": f"{min(chapters)}-{max(chapters)}",
        "source_kind": "summary_native",
        "headings": sorted({o.heading for o in obs}),
    }
    grouped = sorted({g for o in obs for g in o.grouped_by})
    if grouped:
        fm["grouped_by"] = grouped
    head = yaml.safe_dump(
        fm, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10**6
    )
    parts = [f"---\n{head}---\n\n# {CATEGORY_TITLES[category]} — {subject}\n"]
    for o in obs:
        parts.append(
            f"\n## Chapter {o.chapter:03d} — {o.heading}\n\n"
            f"- Source: {o.source_file} (line {o.line})\n"
            f"- Scene: {o.source_scene_id or 'none'}\n"
            + _attach(o.body)
        )
    return "".join(parts)


def write_dossiers(out_dir: Path, obs: list[Observation]) -> int:
    groups = _group_dossiers(obs)
    ddir = Path(out_dir) / "dossiers"
    ddir.mkdir(parents=True, exist_ok=True)
    for (cat, subj, lst), name in zip(groups, dossier_filenames(groups)):
        atomic_write_text(ddir / name, render_dossier(cat, subj, lst))
    return len(groups)


# ── Chronology, memorable moments, other sections ───────────────────────────


def _ordered(files: list[parse.ParsedFile]) -> list[parse.ParsedFile]:
    return sorted(files, key=lambda f: (f.prefix_chapter, f.path))


def render_chronology(files: list[parse.ParsedFile]) -> str:
    out = ["# Chronology\n"]
    for pf in _ordered(files):
        ch = pf.prefix_chapter
        out.append(f"\n## Chapter {ch:03d} — {pf.date or 'date not stated'}\n")
        for sc in pf.scenes:
            syn = (sc.synopsis or "(none)").replace("\n", "\n  ")
            out.append(
                f"\n### {sc.source_scene_id} — {sc.title}\n\n"
                f"- Synopsis: {syn}\n"
                f"- Provenance: {pf.path}; chapter {ch}; scene {sc.source_scene_id} (line {sc.line})\n"
            )
        end = pf.section(schema.SESSION_END_STATE)
        if end is not None:
            out.append(
                f"\n### Session-End State\n\n- Provenance: {pf.path}; chapter {ch} (line {end.line})\n"
                + _attach(end.body)
            )
    return "".join(out)


def render_memorable_moments(files: list[parse.ParsedFile]) -> str:
    out = ["# Memorable Moments\n"]
    for pf in _ordered(files):
        sec = pf.section(schema.MEMORABLE_MOMENTS)
        if sec is None:
            continue
        out.append(
            f"\n## Chapter {pf.prefix_chapter:03d}\n\n"
            f"- Provenance: {pf.path}; chapter {pf.prefix_chapter} (line {sec.line})\n"
            + _attach(sec.body)
        )
    return "".join(out)


def unknown_sections(files: list[parse.ParsedFile]) -> list[dict]:
    return [
        {"chapter": pf.prefix_chapter, "path": pf.path, "name": sec.name}
        for pf in _ordered(files)
        for sec in pf.sections
        if sec.name not in schema.RECOGNISED_SECTIONS
    ]


def render_other_sections(files: list[parse.ParsedFile]) -> str | None:
    out = ["# Other Sections\n"]
    found = False
    for pf in _ordered(files):
        for sec in pf.sections:
            if sec.name in schema.RECOGNISED_SECTIONS:
                continue
            found = True
            out.append(
                f"\n## Chapter {pf.prefix_chapter:03d} — {sec.name}\n\n"
                f"- Provenance: {pf.path}; chapter {pf.prefix_chapter} (line {sec.line})\n"
                + _attach(sec.body)
            )
    return "".join(out) if found else None


# ── Manifest ────────────────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_manifest(
    files: list[parse.ParsedFile],
    campaign_root: Path,
    report: ValidationReport,
    obs: list[Observation],
    n_dossiers: int,
    registry_sha256: str | None,
    canon_sha256: str | None,
) -> dict:
    ordered = _ordered(files)
    absent = {
        sec: [pf.prefix_chapter for pf in ordered if pf.section(sec) is None]
        for sec in schema.RECOGNISED_SECTIONS
        if sec != schema.SCENES
    }
    return {
        "kind": "summary_native",
        "schema": 1,
        "range": {
            "since": report.range.since,
            "until": report.range.until,
            "gaps": report.range.gaps,
        },
        "files": [
            {
                "path": pf.path,
                "chapter": pf.prefix_chapter,
                "sha256": sha256_file(Path(campaign_root) / pf.path),
            }
            for pf in ordered
        ],
        "counts": {
            "files": len(ordered),
            "scenes": sum(len(pf.scenes) for pf in ordered),
            "observations": {c: sum(1 for o in obs if o.category == c) for c in CATEGORIES},
            "dossiers": n_dossiers,
        },
        "absent_optional_sections": absent,
        "unknown_sections": unknown_sections(ordered),
        "canon": {"registry_sha256": registry_sha256, "canon_sha256": canon_sha256},
    }


def build_corpus(
    summaries_dir: Path,
    campaign_root: Path,
    report: ValidationReport,
    range_dir: Path,
    force: bool = False,
    grouper: Grouper = identity_grouper,
    registry_sha256: str | None = None,
    canon_sha256: str | None = None,
) -> dict:
    """Write the corpus for ``report``'s range into ``range_dir``; return the manifest.

    The caller has already run ``validate.scan`` and found no blocking problem.
    Only in-range files are parsed here, so nothing outside the range can reach
    any artifact.
    """
    if report.blocking_count:
        raise CorpusError("refusing to build: validation has blocking problems")
    range_dir = Path(range_dir)
    guard_out_dir(range_dir, force)
    files = []
    for p in sorted(Path(summaries_dir).glob("*.md")):
        pf = parse.parse_file(p, campaign_root)
        if pf.prefix_chapter is not None and report.range.contains(pf.prefix_chapter):
            files.append(pf)
    files = _ordered(files)
    obs = build_observations(files, grouper)

    range_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(range_dir / "chronology.md", render_chronology(files))
    atomic_write_text(range_dir / "memorable_moments.md", render_memorable_moments(files))
    other = render_other_sections(files)
    if other is not None:
        atomic_write_text(range_dir / "other_sections.md", other)
    n_dossiers = write_dossiers(range_dir, obs)
    manifest = build_manifest(
        files, campaign_root, report, obs, n_dossiers, registry_sha256, canon_sha256
    )
    atomic_write_text(range_dir / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
