"""Published NPC dossiers: who is in scope, and by which exact names.

Only an NPC with a published dossier (``npc-publish`` output: a provenance
comment, then YAML frontmatter) is in scope (GM ruling, 2026-10-12). The
dossier supplies the NPC's name forms: ``aliases_used`` is the set of exact
strings ``npc-link`` matched for this NPC, so re-matching them reproduces its
scope rather than inventing a new one. Its counts and chapter list are what
:mod:`pipelines.npc_agent.presence` checks the candidate list against.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

#: ``[ch 061 / 061.05]``, ``[ch 071 / entry; ch 071 / 071.07]`` -> every ``NNN.SS``.
_CITED_SCENE_RE = re.compile(r"\bch \d+ / (\d{3}\.\d{2})\b")


class DossierError(Exception):
    """A dossier cannot be read as a published dossier; the message is user-facing."""


@dataclass(frozen=True)
class Dossier:
    subject: str
    stem: str  # the file's stem, e.g. ``sylvira-savikas``
    path: Path
    forms: tuple[str, ...]
    chapters: tuple[int, ...]
    first_seen: int
    last_seen: int
    n_entries: int
    n_scenes: int
    n_moments: int
    #: every scene id the dossier body cites, in first-seen order
    cited_scenes: tuple[str, ...]


def _frontmatter(text: str) -> tuple[dict, str]:
    """``(frontmatter, body)`` — the first ``---`` block, after any leading comment."""
    m = re.search(r"(?m)^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        raise DossierError("no YAML frontmatter")
    fm = yaml.safe_load(m.group(1))
    if not isinstance(fm, dict):
        raise DossierError("frontmatter is not a mapping")
    return fm, text[m.end():]


def read_dossier(path: Path) -> Dossier:
    text = Path(path).read_text(encoding="utf-8")
    try:
        fm, body = _frontmatter(text)
        forms = fm.get("aliases_used") or []
        if not forms or not all(isinstance(f, str) and f.strip() for f in forms):
            raise DossierError("no aliases_used: nothing names this NPC")
        cited = list(dict.fromkeys(_CITED_SCENE_RE.findall(body)))
        return Dossier(
            subject=str(fm["subject"]),
            stem=Path(path).stem,
            path=Path(path),
            forms=tuple(forms),
            chapters=tuple(int(c) for c in fm.get("chapters") or ()),
            first_seen=int(fm.get("first_seen", 0)),
            last_seen=int(fm.get("last_seen", 0)),
            n_entries=int(fm.get("n_entries", 0)),
            n_scenes=int(fm.get("n_scenes", 0)),
            n_moments=int(fm.get("n_moments", 0)),
            cited_scenes=tuple(cited),
        )
    except DossierError as e:
        raise DossierError(f"{path}: {e}") from None
    except (KeyError, TypeError, ValueError) as e:
        raise DossierError(f"{path}: bad frontmatter ({e})") from None


def read_dossiers(npcs_dir: Path) -> list[Dossier]:
    """Every top-level ``*.md`` in ``npcs_dir`` (subdirectories are pipeline working files)."""
    return [read_dossier(p) for p in sorted(Path(npcs_dir).glob("*.md"))]


def select(dossiers: list[Dossier], names: list[str]) -> list[Dossier]:
    """The dossiers named by subject, stem or one of their forms; refuses an unknown name."""
    out = []
    for name in names:
        hit = [d for d in dossiers if name in (d.subject, d.stem) or name in d.forms]
        if not hit:
            known = ", ".join(d.subject for d in dossiers) or "none"
            raise DossierError(f"no published dossier for {name!r}; published: {known}")
        if len(hit) > 1:
            raise DossierError(
                f"{name!r} names more than one dossier: {', '.join(d.subject for d in hit)}"
            )
        if hit[0] not in out:
            out.append(hit[0])
    return out
