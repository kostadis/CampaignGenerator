"""The assembly gate, and the variant collision — contracts G and V (#455).

A gap marker in an assembled chapter is loud and recoverable — embarrassing
rather than dangerous. But an assembled chapter feeds the release append and the
chapter split, so a marker that reaches it travels, and it travels into the
bible.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from session_doc.assemble import SceneCollision, collect_scene_files  # noqa: E402
from session_doc.blocks import GAP_MARKER  # noqa: E402

SCENE = """---
scene: {n:02d}
slug: {slug}
narrator: {narrator}
scene_name: {name}
session: '20260825'
---

{body}
"""


def write_scene(d: Path, n: int, slug: str, body: str, suffix: str = ".md") -> Path:
    p = d / f"session_doc_scene_{n:02d}_{slug}{suffix}"
    p.write_text(SCENE.format(n=n, slug=slug, narrator="Brewbarry",
                              name=slug.replace("_", " ").title(), body=body),
                 encoding="utf-8")
    return p


def run_assemble(d: Path, out: Path, *extra: str):
    return subprocess.run(
        [sys.executable, "-m", "session_doc.assemble", str(d), "--output", str(out), *extra],
        capture_output=True, text=True, cwd=ROOT,
    )


# ── Contract G — the gate ───────────────────────────────────────────────────

def test_the_gate_refuses_a_scene_that_still_holds_a_marker(tmp_path):
    """G1."""
    write_scene(tmp_path, 1, "clean", "She turned toward the door.")
    write_scene(tmp_path, 2, "open", f"{GAP_MARKER} the party arrives]")
    r = run_assemble(tmp_path, tmp_path / "out.md", "--require-composed")
    assert r.returncode == 1
    assert "session_doc_scene_02_open.md" in r.stderr
    assert not (tmp_path / "out.md").exists()


def test_the_refusal_names_every_scene_not_just_the_first(tmp_path):
    """G2. Naming one means the GM fixes it, re-runs, and is told about the
    next — which is the shape of a tool that wastes an afternoon."""
    write_scene(tmp_path, 1, "one", f"{GAP_MARKER} a]")
    write_scene(tmp_path, 2, "two", "clean prose")
    write_scene(tmp_path, 3, "three", f"{GAP_MARKER} b]")
    r = run_assemble(tmp_path, tmp_path / "out.md", "--require-composed")
    assert r.returncode == 1
    assert "session_doc_scene_01_one.md" in r.stderr
    assert "session_doc_scene_03_three.md" in r.stderr


def test_the_gate_passes_when_every_scene_is_answered(tmp_path):
    write_scene(tmp_path, 1, "one", "prose")
    write_scene(tmp_path, 2, "two", "more prose")
    out = tmp_path / "out.md"
    r = run_assemble(tmp_path, out, "--require-composed")
    assert r.returncode == 0, r.stderr
    assert out.exists()


def test_without_the_gate_a_marker_assembles_exactly_as_before(tmp_path):
    """G4. The gate is opt-in; existing runs are untouched."""
    write_scene(tmp_path, 1, "open", f"{GAP_MARKER} the party arrives]")
    out = tmp_path / "out.md"
    r = run_assemble(tmp_path, out)
    assert r.returncode == 0, r.stderr
    assert GAP_MARKER in out.read_text(encoding="utf-8")


def test_the_gate_reads_the_document_not_a_record(tmp_path):
    """G3. A composed file with a marker in it is unfit whatever a record says
    — including when there is no record at all, which is the case here."""
    write_scene(tmp_path, 1, "hand", f"{GAP_MARKER} written by hand]",
                suffix=".composed.md")
    r = run_assemble(tmp_path, tmp_path / "out.md", "--require-composed")
    assert r.returncode == 1
    assert "hand" in r.stderr


# ── Contract V — one scene, two final variants ──────────────────────────────

def test_a_scrubbed_and_a_composed_variant_together_refuse(tmp_path):
    """V1. Neither pass supersedes the other by name: scrubbing polishes prose,
    composing fills the GM's gaps, and they are independent."""
    write_scene(tmp_path, 1, "x", "raw")
    write_scene(tmp_path, 1, "x", "scrubbed", suffix=".scrubbed.md")
    write_scene(tmp_path, 1, "x", "composed", suffix=".composed.md")
    with pytest.raises(SceneCollision) as exc:
        collect_scene_files(tmp_path, "session_doc_scene_*.md", prefer_scrubbed=True)
    assert "scrubbed.md" in str(exc.value) and "composed.md" in str(exc.value)


def test_use_resolves_the_variant_collision(tmp_path):
    """V2 — the same flag that resolves #429's collision, not a second one."""
    write_scene(tmp_path, 1, "x", "raw")
    write_scene(tmp_path, 1, "x", "scrubbed", suffix=".scrubbed.md")
    composed = write_scene(tmp_path, 1, "x", "composed", suffix=".composed.md")
    got = collect_scene_files(tmp_path, "session_doc_scene_*.md",
                              prefer_scrubbed=True, chosen={composed.name})
    assert got == [composed]


def test_the_message_distinguishes_this_from_two_scenes_claiming_one_number(tmp_path):
    """V3. Same exception and same flag by design; a shared sentence would leave
    the GM looking for a duplicate scene number that does not exist."""
    write_scene(tmp_path, 1, "x", "scrubbed", suffix=".scrubbed.md")
    write_scene(tmp_path, 1, "x", "composed", suffix=".composed.md")
    with pytest.raises(SceneCollision) as exc:
        collect_scene_files(tmp_path, "session_doc_scene_*.md", prefer_scrubbed=True)
    message = str(exc.value)
    assert "two final variants" in message
    assert "same scene" not in message      # #429's wording


def test_a_composed_variant_alone_is_used(tmp_path):
    """No collision, no flag needed: composing is the later pass and the only
    final document present."""
    write_scene(tmp_path, 1, "x", "raw")
    composed = write_scene(tmp_path, 1, "x", "composed", suffix=".composed.md")
    assert collect_scene_files(tmp_path, "session_doc_scene_*.md",
                               prefer_scrubbed=True) == [composed]


def test_the_existing_scrubbed_preference_is_unchanged(tmp_path):
    """The behaviour that shipped before this feature, still true."""
    raw = write_scene(tmp_path, 1, "x", "raw")
    scrubbed = write_scene(tmp_path, 1, "x", "scrubbed", suffix=".scrubbed.md")
    assert collect_scene_files(tmp_path, "session_doc_scene_*.md",
                               prefer_scrubbed=True) == [scrubbed]
    assert collect_scene_files(tmp_path, "session_doc_scene_*.md",
                               prefer_scrubbed=False) == [raw]
