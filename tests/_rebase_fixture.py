"""Synthetic git-initialised campaign for spec 040 (source-custody rebase). Not collected: no ``test_`` prefix.

Layers (each is a function so later phases extend the state instead of rebuilding it):

1. :func:`build_active_through_ch5` - a managed generation through chapter 5, published through the REAL
   delta/promotion path (the same ``publish_delta`` the spec 039 e2e test uses), with the original summaries
   committed to the campaign's own git history.
2. :func:`stage_pending_ch6` - a pending chapter-6 grounding delta plan: edits proposed and approved, the
   deterministic check passed and the candidates staged as a promotion range (``grounding preview``).
3. :func:`apply_corrections` - commits corrections to chapters 2-5 (semantic) or a chapter-1 whitespace-only
   variant, so the pins held by the active generation go stale.

:func:`build` runs all three.  NOT built here (Phase 4 work, no records are faked to cover it): NPC receipts
published for >= 2 members of the pending plan.  The grounding-only plan is what T002 needs; the NPC layer
belongs in ``stage_pending_npc`` once US2 (rebind) needs NPC bindings to preserve.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from tests.support.delta_grounding_fixture import FACTORY, GENERATION_ID, add_new_chapter, make_grounding_campaign
from tests.test_delta_grounding_e2e import NEW_LINE, INHERITED_LINE, SUPPORT, prepare, publish_delta, run

CHAPTER_5 = """# Chapter 5

Date: 2026-04-09

## Scenes

### 005.01 The Far Marker

Warden Hale walked the Lantern Road past the eastern marker and found the far marker standing. The company holds four prisoners.

#### The far marker stands.

- Hale confirms the far marker stands.
- The company holds four prisoners.

## Locations

### Far Marker

A weathered stone beyond the eastern marker.

## Memorable Moments

> "It still stands."
> - Warden Hale
> *Mara smiled.*
"""
CHAPTER_6 = """# Chapter 6

Date: 2026-04-16

## Scenes

### 006.01 The Cellar

Warden Hale confirmed the four prisoners were marched to the far marker before dusk.

#### The prisoners are moved.

- Hale confirms four prisoners were marched to the far marker.

## Memorable Moments

> "Four, and not one more."
> - Warden Hale
> *Mara counted them twice.*
"""
NEW_LINE_5 = "The far marker beyond the eastern marker still stands. [ch 005 / 005.01]"
PRISONER_LINE_5 = "The company holds four prisoners. [ch 005 / 005.01]"
OLD_LINE_1 = "The brass key still opens the sealed gate. [ch 001 / 001.01]"
CH2_LINE = "The company opens the sealed gate and clears the old watch room. [ch 002 / 002.01]"
NEW_LINE_6 = "Four prisoners were marched to the far marker. [ch 006 / 006.01]"
SUPPORT_5 = "Warden Hale walked the Lantern Road past the eastern marker"
SUPPORT_6 = "Warden Hale confirmed the four prisoners were marched to the far marker"

#: chapter -> (old text, new text): each swapped phrase sits in a cited entry (the corrections quickstart lists).
SEMANTIC = {
    2: ("The company opens the sealed gate and clears the old watch room.",
        "The company opens the sealed gate for a fee of 40 gold and clears the old watch room."),
    3: ("Hale records that the Lantern Road is safe as far as the eastern marker.",
        "Hale records the Lantern Road as open as far as the eastern marker."),
    4: ("Hale confirms the road is open to the eastern marker.",
        "Hale has not yet told the company the road is open to the eastern marker."),
    5: ("The company holds four prisoners.", "The company holds three prisoners."),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def git_show_bytes(root: Path, rev: str, rel: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), "show", f"{rev}:{rel}"], capture_output=True, check=True).stdout


@dataclass
class RebaseFixture:
    root: Path
    generation_id: str = ""
    paths: dict[int, Path] = field(default_factory=dict)
    old_sha: dict[int, str] = field(default_factory=dict)
    new_sha: dict[int, str] = field(default_factory=dict)
    pending_plan_id: str | None = None
    staged: dict | None = None
    #: git commit holding the original (pre-correction) summaries
    original_commit: str = ""

    @property
    def corrected(self) -> list[int]:
        return sorted(c for c in self.new_sha if self.new_sha[c] != self.old_sha[c])


def _summary_paths(root: Path) -> dict[int, Path]:
    out = {}
    for p in (root / "docs/summaries").glob("*.md"):
        head = p.name.split("-", 1)[0]
        if head.isdigit():
            out[int(head)] = p
    return out


def init_git(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.com")
    git(root, "config", "user.name", "fixture")
    git(root, "config", "commit.gpgsign", "false")


def commit_all(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def build_active_through_ch5(tmp_path: Path, capsys, monkeypatch) -> RebaseFixture:
    """Layer 1: ch1-3 legacy generation, then delta generations for ch4 and ch5 through the real publish path."""
    root = make_grounding_campaign(tmp_path)
    init_git(root)
    fx = RebaseFixture(root=root)
    publish_delta(capsys, root, add_new_chapter(root), monkeypatch, 4, "rb-r4",
                  "{line}\n" + NEW_LINE + "\n" + INHERITED_LINE + "\n" + CH2_LINE)
    source5 = root / "docs/summaries/005-the-far-marker.md"
    source5.write_text(CHAPTER_5, encoding="utf-8")
    publish_delta(capsys, root, source5, monkeypatch, 5, "rb-r5",
                  "{line}\n" + NEW_LINE_5 + "\n" + PRISONER_LINE_5 + "\n" + OLD_LINE_1, support=SUPPORT_5)
    from pipelines.summary_native.delta import baseline as bl
    fx.generation_id = bl.bind(root).generation_id
    assert fx.generation_id != GENERATION_ID
    return fx


def stage_pending_ch6(fx: RebaseFixture, capsys, monkeypatch) -> RebaseFixture:
    """Layer 2: a pending ch6 grounding plan, decided, checked and staged (not applied)."""
    root = fx.root
    source6 = root / "docs/summaries/006-the-cellar.md"
    source6.write_text(CHAPTER_6, encoding="utf-8")
    pid, _line = prepare(capsys, root, source6, monkeypatch,
                         "{line}\n" + NEW_LINE_6, support=SUPPORT_6)
    assert run(capsys, root, "grounding", "check", "--plan", pid)["passed"] is True
    fx.staged = run(capsys, root, "grounding", "preview", "--plan", pid)["staged"]
    fx.pending_plan_id = pid
    return fx


def snapshot_originals(fx: RebaseFixture) -> None:
    fx.paths = _summary_paths(fx.root)
    fx.old_sha = {c: sha(p.read_bytes()) for c, p in fx.paths.items()}
    fx.original_commit = commit_all(fx.root, "original summaries and published generations")


def apply_corrections(fx: RebaseFixture, *, whitespace_ch1: bool = False) -> RebaseFixture:
    """Layer 3: commit corrections.  ``whitespace_ch1`` is the separate variant: ONLY ch1, in an uncited region."""
    if whitespace_ch1:
        p = fx.paths[1]
        text = p.read_text(encoding="utf-8")
        assert "Hale keeps the gate ledger.\n" in text
        p.write_text(text.replace("Hale keeps the gate ledger.\n", "Hale keeps the gate ledger.  \n", 1), encoding="utf-8")
    else:
        for chapter, (old, new) in SEMANTIC.items():
            p = fx.paths[chapter]
            text = p.read_text(encoding="utf-8")
            assert old in text, (chapter, old)
            p.write_text(text.replace(old, new, 1), encoding="utf-8")
    fx.new_sha = {c: sha(p.read_bytes()) for c, p in fx.paths.items()}
    commit_all(fx.root, "corrections")
    return fx


def build(tmp_path: Path, capsys, monkeypatch, *, whitespace_ch1: bool = False,
          pending_ch6: bool = True) -> RebaseFixture:
    fx = build_active_through_ch5(tmp_path, capsys, monkeypatch)
    if pending_ch6:
        stage_pending_ch6(fx, capsys, monkeypatch)
    snapshot_originals(fx)
    return apply_corrections(fx, whitespace_ch1=whitespace_ch1)
