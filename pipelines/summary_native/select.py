"""Choose which dossiers enter a synthesis context (FR-017, research R8).

Pure and deterministic: reads dossier frontmatter, never a model, never writes.
The corpus is left untouched; selection only decides what is *shown*.
Deliberately independent of ``pipelines.ensemble`` (FR-011).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

REASONS = ("named", "recent", "recurring")
_CHAPTERS_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


class SelectionError(Exception):
    """A selection request that cannot be honoured (CLI exit 2)."""


@dataclass(frozen=True)
class Dossier:
    stem: str
    subject: str
    category: str
    n_observations: int
    first_chapter: int
    last_chapter: int
    path: Path


@dataclass(frozen=True)
class SelectedDossier:
    dossier: Dossier
    reason: str


@dataclass(frozen=True)
class Selection:
    range_end: int
    recent_chapters: int
    recurring_min: int
    items: tuple[SelectedDossier, ...]

    def to_json(self) -> str:
        data = {
            "range_end": self.range_end,
            "recent_chapters": self.recent_chapters,
            "recurring_min": self.recurring_min,
            "selected": [
                {
                    "dossier": i.dossier.stem,
                    "subject": i.dossier.subject,
                    "reason": i.reason,
                    "last_chapter": i.dossier.last_chapter,
                    "n_observations": i.dossier.n_observations,
                }
                for i in self.items
            ],
        }
        return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    data = yaml.safe_load(text[4:end]) or {}
    return data if isinstance(data, dict) else {}


def read_corpus_dossiers(range_dir: Path) -> list[Dossier]:
    """Parse every ``dossiers/*.md`` frontmatter, sorted by filename."""
    out: list[Dossier] = []
    for p in sorted((Path(range_dir) / "dossiers").glob("*.md")):
        fm = _frontmatter(p.read_text(encoding="utf-8"))
        m = _CHAPTERS_RE.match(str(fm.get("chapters", "")))
        if not fm.get("subject") or not m:
            raise SelectionError(f"{p}: dossier frontmatter lacks subject/chapters")
        out.append(
            Dossier(
                stem=p.stem,
                subject=str(fm["subject"]),
                category=str(fm.get("type", "")),
                n_observations=int(fm.get("n_facts", 0)),
                first_chapter=int(m.group(1)),
                last_chapter=int(m.group(2)),
                path=p,
            )
        )
    return out


def select_dossiers(
    dossiers: list[Dossier],
    range_until: int,
    recent_chapters: int,
    recurring_min: int,
    named: tuple[str, ...] | list[str] = (),
) -> Selection:
    """Named, then recent, then recurring. ``recent_chapters`` 0 means every dossier is recent."""
    by_subject: dict[str, list[Dossier]] = {}
    for d in dossiers:
        by_subject.setdefault(d.subject.casefold(), []).append(d)
    chosen: dict[str, SelectedDossier] = {}
    unmatched: list[str] = []
    for name in named:
        hits = by_subject.get(name.strip().casefold())
        if not hits:
            unmatched.append(name)
            continue
        for d in sorted(hits, key=lambda d: d.stem):
            chosen.setdefault(d.stem, SelectedDossier(d, "named"))
    if unmatched:
        raise SelectionError("no dossier has subject: " + ", ".join(unmatched))
    items = list(chosen.values())

    floor = range_until - recent_chapters + 1
    rest = [d for d in dossiers if d.stem not in chosen]
    recent = [d for d in rest if recent_chapters == 0 or d.last_chapter >= floor]
    recent.sort(key=lambda d: (-d.last_chapter, -d.n_observations, d.stem))
    items += [SelectedDossier(d, "recent") for d in recent]
    taken = {d.stem for d in recent}
    recurring = [d for d in rest if d.stem not in taken and d.n_observations >= recurring_min]
    recurring.sort(key=lambda d: (-d.n_observations, d.stem))
    items += [SelectedDossier(d, "recurring") for d in recurring]
    return Selection(range_until, recent_chapters, recurring_min, tuple(items))
