"""A campaign with a REAL managed grounding generation, for spec 039 grounding tests.

Built by the promotion suite's own factory (``tests/fixtures/summary_native/promotion/create_campaign.py``)
and ``initialize_managed``, so the generation manifest, activation history and ``current`` link are what
the real readers (``promotion/history.py``, ``campaignlib.grounding_bundle``) accept.  Adds a new
source chapter that the delta selects.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

_FACTORY_PATH = Path(__file__).parents[1] / "fixtures/summary_native/promotion/create_campaign.py"
_spec = importlib.util.spec_from_file_location("delta_promotion_fixture_factory", _FACTORY_PATH)
assert _spec and _spec.loader
FACTORY = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FACTORY)

DOCUMENTS = FACTORY.DOCUMENTS
GENERATION_ID = "legacy-fixture"

NEW_CHAPTER = """# Chapter 4

Date: 2026-04-02

## Scenes

### 004.01 The Eastern Marker

Warden Hale confirmed the Lantern Road is open past the eastern marker, and Mara sealed the survey ledger.

#### The road is surveyed to the marker.

- Hale confirms the road is open to the eastern marker.

## Memorable Moments

> "The marker holds."
> - Warden Hale
> *Mara nodded.*
"""


def make_grounding_campaign(tmp_path: Path, *, edit_live: bool = False) -> Path:
    """Campaign root with an active managed generation (live docs are symlinks into it)."""
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    FACTORY.initialize_managed(root, GENERATION_ID)
    if edit_live:
        edit_live_document(root, "world_state")
    return root


def live_path(root: Path, name: str) -> Path:
    return root / "docs/grounding/generations" / GENERATION_ID / "live" / f"{name}.md"


def published_path(root: Path, name: str) -> Path:
    return root / "docs/grounding/generations" / GENERATION_ID / "published" / f"{name}.md"


def edit_live_document(root: Path, name: str = "world_state") -> None:
    """A hand edit after publication: one line changed and one appended."""
    path = live_path(root, name)
    text = path.read_text(encoding="utf-8")
    first_body = next(ln for ln in text.splitlines() if ln.startswith("Existing reviewed live edit"))
    path.write_text(text.replace(first_body, first_body + " HAND-EDITED.", 1) + "A hand-added closing line.\n",
                    encoding="utf-8")


def add_new_chapter(root: Path, chapter: int = 4) -> Path:
    path = root / f"docs/summaries/{chapter:03d}-the-eastern-marker.md"
    path.write_text(NEW_CHAPTER, encoding="utf-8")
    return path


def digest_tree(path: Path) -> dict[str, str]:
    """relative path -> sha256 for every file under ``path`` (follows no symlinked directories)."""
    out = {}
    for p in sorted(path.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[p.relative_to(path).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def history_digests(root: Path) -> dict[str, str]:
    """Digest of every earlier generation/activation/receipt file (must never change)."""
    g = root / "docs/grounding"
    out = {}
    for sub in ("generations", "activations", "migrations"):
        d = g / sub
        if d.is_dir():
            out.update({f"{sub}/{k}": v for k, v in digest_tree(d).items()})
    return out
