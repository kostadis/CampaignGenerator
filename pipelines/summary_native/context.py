"""The structured party and planning configs the chunked build reads (spec 034).

No model call, no ``campaignlib.api`` import, no retrieval. The prompts are built in ``synth``, one per
section, from the checked notes; this module only resolves what the GM configured (``party.yaml``,
``planning.yaml``) and says where the prompt files live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from campaignlib.party_config import PartyConfig, load_party_config, resolve_party_config
from campaignlib.planning_config import PlanningConfig, PlanningNoteSelector, ResolvedEntry, load_planning_config, resolve_entries

PROMPT_DIR = Path(__file__).parent / "prompts"
#: The one line a Threat Tracker holds when no arc score is configured (``state_sections.threat_tracker_md``).
NO_ARC_SENTINEL = "_No arc scores configured._"


class DocConfigError(Exception):
    """A party/planning config that cannot be used (CLI exit 2)."""


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8").rstrip()


def _shown(path: Path, root: Path | None) -> str:
    p = Path(path)
    if root is not None:
        try:
            return p.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return p.as_posix()


@dataclass(frozen=True)
class ResolvedCharacter:
    """One configured player character with the files the party build reads (spec 034 T017).

    ``sheet_text`` and ``backstory_text`` are the GM's own words, verbatim; ``arc_score`` is the mechanic
    file's path (its text is read only where candidate arc-score events are built). Not to be confused
    with ``campaignlib.party_config.ResolvedCharacter``, which this is built from.
    """

    name: str
    sheet: Path
    sheet_text: str
    backstory: Path | None
    backstory_text: str | None
    arc_score: Path | None
    trackless: bool

    @property
    def files(self) -> tuple[tuple[str, Path], ...]:
        """``(role, path)`` of every file this character reads, in a fixed order."""
        found = (("sheet", self.sheet), ("backstory", self.backstory), ("arc_score", self.arc_score))
        return tuple((f"{role}:{self.name}", p) for role, p in found if p is not None)


def load_party(path: Path, root: Path, *, source_text=None) -> list[ResolvedCharacter]:
    """The configured characters in ``party.yaml`` order, with sheet and backstory text read.

    Raises ``DocConfigError``: the file is missing, unreadable, declares no characters, or a character's
    sheet, backstory or arc-score file is missing.
    """
    path = Path(path).expanduser()
    if source_text is None and not path.is_file():
        raise DocConfigError(f"--party-config {_shown(path, root)}: not found")
    try:
        if source_text is None:
            config = load_party_config(path)
        else:
            raw = yaml.safe_load(source_text(path))
            config = PartyConfig.model_validate(raw or {})
        resolved = resolve_party_config(config, Path(root), require_files=False)
    except ValueError as e:
        raise DocConfigError(f"--party-config {_shown(path, root)}: unreadable ({e})") from e
    if not resolved.characters:
        raise DocConfigError(f"--party-config {_shown(path, root)}: no characters declared")
    out: list[ResolvedCharacter] = []
    for pc in resolved.characters:
        for label, p in (("sheet", pc.sheet), ("backstory", pc.backstory), ("arc score mechanic", pc.arc_score)):
            if p is not None and (source_text is None and not p.is_file()):
                raise DocConfigError(f"party config: {pc.name} {label} file missing: {_shown(p, root)}")
        out.append(ResolvedCharacter(
            name=pc.name, sheet=pc.sheet, sheet_text=source_text(pc.sheet).rstrip() if source_text else _read(pc.sheet),
            backstory=pc.backstory, backstory_text=source_text(pc.backstory).rstrip() if pc.backstory and source_text else _read(pc.backstory) if pc.backstory else None,
            arc_score=pc.arc_score, trackless=pc.trackless,
        ))
    return out


@dataclass(frozen=True)
class ResolvedPlanning:
    """The tracked NPCs and factions of ``planning.yaml``, in file order, with their arc-score files resolved (spec 034 T034).

    ``path`` is ``None`` when no config file exists (none configured). An entry's ``arc_score`` is the
    mechanic file, or ``None`` when it is ``trackless`` (``arc_score: null`` by design) or declares none.
    """

    path: Path | None
    npcs: list[ResolvedEntry] = field(default_factory=list)
    factions: list[ResolvedEntry] = field(default_factory=list)
    notes: list[PlanningNoteSelector] | None = None

    @property
    def entries(self) -> list[ResolvedEntry]:
        """NPCs then factions, each in config order: the Threat Tracker's row order."""
        return [*self.npcs, *self.factions]

    @property
    def scored(self) -> list[ResolvedEntry]:
        return [e for e in self.entries if e.arc_score is not None]

    @property
    def files(self) -> tuple[Path, ...]:
        """The config file, then each mechanic file, in row order: what the run record hashes."""
        return (*([self.path] if self.path is not None else []), *(e.arc_score for e in self.scored))


def load_planning(path: Path | None, root: Path, *, explicit: bool, source_text=None) -> ResolvedPlanning:
    """The structured planning config. An absent default file means none configured; an explicit missing
    file refuses. Raises ``DocConfigError``."""
    if path is None or (source_text is None and not Path(path).is_file()):
        if explicit:
            raise DocConfigError(f"--planning-config {path}: no such file")
        return ResolvedPlanning(None)
    try:
        if source_text is None:
            cfg = load_planning_config(Path(path))
        else:
            raw = yaml.safe_load(source_text(Path(path)))
            cfg = PlanningConfig.model_validate(raw or {})
        npcs = resolve_entries(cfg.npcs, Path(root), require_files=False)
        factions = resolve_entries(cfg.factions, Path(root), require_files=False)
    except ValueError as e:
        raise DocConfigError(f"--planning-config {_shown(path, root)}: {e}") from e
    for e in [*npcs, *factions]:
        if e.arc_score is not None and source_text is None and not e.arc_score.is_file():
            raise DocConfigError(f"planning config: {e.name} arc score file missing: {_shown(e.arc_score, root)}")
    return ResolvedPlanning(Path(path), npcs, factions, cfg.notes)
