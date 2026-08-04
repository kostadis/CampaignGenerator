"""Tests for chapter identity (issue #213, Phase 0).

Covers the three cooperating pieces:

- ``split_chapters.py`` — identity marker consumed into YAML frontmatter;
  the loud heading==position check that refuses to split a drifted bible.
- ``renumber_chapters.py`` — the one-time in-place fix: bible headings
  renumbered to encounter order, chapter files stamped with frontmatter,
  sessions only from *approved* summary-map rows, hand-edit drift reported
  but never overwritten. Idempotent.
- ``assemble.py`` — the minting point: ``--chapter`` emits frontmatter and
  a ``# Chapter N`` H1 with the session date derived from the
  ``summaries/YYYYMMDD/`` path convention.
- The two chapter read points (``extract_facts``/``narrate_chapter`` both
  route through ``campaignlib.split_frontmatter``) never see the metadata
  as prose — asserted via the helper's behaviour on a stamped file.
"""

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from campaignlib import split_frontmatter  # noqa: E402
from pipelines.ensemble import split_chapters as sc  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────

def _drifted_bible() -> str:
    """Three chapters whose headings run one behind their position —
    the real Phandalin drift shape."""
    return (
        "# Chapter 1 The Founding\n\nAlpha content.\n\n"
        "# Chapter 1 Vukradin: Rank Cheval\n\nBeta content.\n\n"
        "# Chapter 2 Universal Basic Treasure\n\nGamma content.\n"
    )


def _clean_bible() -> str:
    return (
        "# Chapter 1 The Founding\n\nAlpha content.\n\n"
        "# Chapter 2 Vukradin: Rank Cheval\n<!-- chapter: 2 | session: 20260101 -->\n\n"
        "Beta content.\n\n"
        "# Chapter 3 Universal Basic Treasure\n\nGamma content.\n"
    )


def _run_split(tmp_path: Path, bible: str, *extra: str) -> subprocess.CompletedProcess:
    src = tmp_path / "bible.md"
    src.write_text(bible, encoding="utf-8")
    out = tmp_path / "chapters"
    return subprocess.run(
        [sys.executable, str(REPO / "pipelines/ensemble/split_chapters.py"),
         str(src), "--output-dir", str(out), *extra],
        capture_output=True, text=True, cwd=REPO)


# ── split_chapters: identity check ───────────────────────────────────────

def test_split_refuses_drifted_bible_and_writes_nothing(tmp_path):
    proc = _run_split(tmp_path, _drifted_bible())
    assert proc.returncode == 1
    assert "renumber_chapters.py" in proc.stderr
    assert not list((tmp_path / "chapters").glob("*.md")) if (tmp_path / "chapters").exists() else True


def test_split_clean_bible_lands_frontmatter_and_consumes_marker(tmp_path):
    proc = _run_split(tmp_path, _clean_bible())
    assert proc.returncode == 0, proc.stderr
    ch2 = (tmp_path / "chapters" / "chapter_02_vukradin_rank_cheval.md").read_text()
    meta, body = split_frontmatter(ch2)
    assert meta == {"chapter": 2, "session": "20260101",
                    "title": "Vukradin: Rank Cheval"}
    assert body.startswith("# Chapter 2 Vukradin: Rank Cheval")
    assert "<!--" not in ch2  # marker consumed, not copied
    # Chapter without a marker still gets chapter/title frontmatter.
    ch3 = (tmp_path / "chapters" / "chapter_03_universal_basic_treasure.md").read_text()
    meta3, _ = split_frontmatter(ch3)
    assert meta3 == {"chapter": 3, "title": "Universal Basic Treasure"}
    assert "session" not in meta3


def test_split_marker_position_mismatch_fails(tmp_path):
    bible = ("# Chapter 1 One\n<!-- chapter: 9 | session: 20260101 -->\n\nBody.\n")
    proc = _run_split(tmp_path, bible)
    assert proc.returncode == 1
    assert "marker says chapter 9" in proc.stderr


def test_split_no_check_allows_decimal_chapters_without_frontmatter(tmp_path):
    bible = ("# Chapter 18 One\n\nBody.\n\n# Chapter 18.05 Interlude\n\nBody.\n")
    proc = _run_split(tmp_path, bible, "--no-check")
    assert proc.returncode == 0, proc.stderr
    files = sorted(p.name for p in (tmp_path / "chapters").glob("*.md"))
    assert files == ["chapter_01_one.md", "chapter_02_interlude.md"]
    meta, _ = split_frontmatter((tmp_path / "chapters" / files[0]).read_text())
    assert meta == {}  # no frontmatter in legacy mode


def test_split_is_byte_stable_on_rerun(tmp_path):
    assert _run_split(tmp_path, _clean_bible()).returncode == 0
    proc = _run_split(tmp_path, _clean_bible())
    assert proc.returncode == 0
    assert "0 file(s); 3 unchanged" in proc.stdout


def test_split_em_dash_separator_stripped_from_title(tmp_path):
    bible = "# Chapter 1 — Unraveling the Storm God's Secrets\n\nBody.\n"
    proc = _run_split(tmp_path, bible)
    assert proc.returncode == 0, proc.stderr
    files = list((tmp_path / "chapters").glob("*.md"))
    assert files[0].name == "chapter_01_unraveling_the_storm_god_s_secrets.md"
    from campaignlib import split_frontmatter as sf
    meta, _ = sf(files[0].read_text())
    assert meta["title"] == "Unraveling the Storm God's Secrets"


# ── renumber_chapters ────────────────────────────────────────────────────

def _setup_drifted_campaign(tmp_path: Path) -> tuple[Path, Path]:
    bible = tmp_path / "chapters.md"
    bible.write_text(_drifted_bible(), encoding="utf-8")
    chdir = tmp_path / "chapters"
    chdir.mkdir()
    (chdir / "chapter_01_the_founding.md").write_text(
        "# Chapter 1 The Founding\n\nAlpha content.\n", encoding="utf-8")
    (chdir / "chapter_02_vukradin_rank_cheval.md").write_text(
        "# Chapter 1 Vukradin: Rank Cheval\n\nBeta content.\n", encoding="utf-8")
    (chdir / "chapter_03_universal_basic_treasure.md").write_text(
        "# Chapter 2 Universal Basic Treasure\n\nGamma content. Hand edit.\n",
        encoding="utf-8")
    return bible, chdir


def _run_renumber(bible: Path, chdir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "pipelines/ensemble/renumber_chapters.py"),
         "--bible", str(bible), "--chapters-dir", str(chdir), *extra],
        capture_output=True, text=True, cwd=REPO)


def test_renumber_dry_run_touches_nothing(tmp_path):
    bible, chdir = _setup_drifted_campaign(tmp_path)
    before = {p: p.read_text() for p in [bible, *chdir.glob("*.md")]}
    proc = _run_renumber(bible, chdir)
    assert proc.returncode == 0, proc.stderr
    assert "dry-run" in proc.stdout
    assert {p: p.read_text() for p in before} == before


def test_renumber_apply_fixes_headings_and_stamps_frontmatter(tmp_path):
    bible, chdir = _setup_drifted_campaign(tmp_path)
    proc = _run_renumber(bible, chdir, "--apply")
    assert proc.returncode == 0, proc.stderr

    text = bible.read_text()
    assert "# Chapter 2 Vukradin: Rank Cheval" in text
    assert "# Chapter 3 Universal Basic Treasure" in text
    assert "# Chapter 1 Vukradin" not in text

    ch2 = (chdir / "chapter_02_vukradin_rank_cheval.md").read_text()
    meta, body = split_frontmatter(ch2)
    assert meta == {"chapter": 2, "title": "Vukradin: Rank Cheval"}
    assert body.startswith("# Chapter 2 Vukradin: Rank Cheval")

    # Hand-edited file: heading fixed, content NOT reverted to the bible's.
    ch3 = (chdir / "chapter_03_universal_basic_treasure.md").read_text()
    assert "# Chapter 3 Universal Basic Treasure" in ch3
    assert "Hand edit." in ch3
    assert "chapter_03" in proc.stdout and "differs from bible chunk" in proc.stdout


def test_renumber_is_idempotent(tmp_path):
    bible, chdir = _setup_drifted_campaign(tmp_path)
    assert _run_renumber(bible, chdir, "--apply").returncode == 0
    after_first = {p: p.read_text() for p in [bible, *sorted(chdir.glob("*.md"))]}
    proc = _run_renumber(bible, chdir, "--apply")
    assert proc.returncode == 0
    assert {p: p.read_text() for p in [bible, *sorted(chdir.glob("*.md"))]} == after_first
    assert "0 file(s) written" in proc.stdout


def test_renumber_sessions_only_from_approved_map_rows(tmp_path):
    bible, chdir = _setup_drifted_campaign(tmp_path)
    smap = tmp_path / "summary_map.yaml"
    smap.write_text(yaml.safe_dump({"entries": [
        {"chapter": "chapter_01_the_founding.md", "summary_date": "20260101",
         "approved": True},
        {"chapter": "chapter_02_vukradin_rank_cheval.md", "summary_date": "20260108",
         "approved": False},
    ]}), encoding="utf-8")
    proc = _run_renumber(bible, chdir, "--summary-map", str(smap), "--apply")
    assert proc.returncode == 0, proc.stderr
    meta1, _ = split_frontmatter((chdir / "chapter_01_the_founding.md").read_text())
    meta2, _ = split_frontmatter((chdir / "chapter_02_vukradin_rank_cheval.md").read_text())
    assert meta1.get("session") == "20260101"      # approved row stamps
    assert "session" not in meta2                  # proposal never stamps


def test_renumbered_bible_passes_split_check(tmp_path):
    bible, chdir = _setup_drifted_campaign(tmp_path)
    assert _run_renumber(bible, chdir, "--apply").returncode == 0
    chunks = sc.split(bible.read_text(), "# Chapter ")
    assert sc.check_identity(chunks) == []


# ── assemble minting ─────────────────────────────────────────────────────

def _scene(dir_path: Path, n: int, body: str) -> None:
    (dir_path / f"session_doc_scene_{n:02d}_x.md").write_text(
        f"---\nscene: {n}\nscene_name: Scene {n}\nnarrator: Vukradin\n---\n{body}\n",
        encoding="utf-8")


def test_assemble_mints_frontmatter_and_h1(tmp_path):
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    _scene(narr, 1, "First.")
    out = tmp_path / "session_doc.md"
    proc = subprocess.run(
        [sys.executable, str(REPO / "session_doc/assemble.py"), str(narr),
         "--output", str(out), "--chapter", "46",
         "--title", "Chapter 46 — Universal Basic Treasure"],
        capture_output=True, text=True, cwd=REPO)
    assert proc.returncode == 0, proc.stderr
    meta, body = split_frontmatter(out.read_text())
    assert meta == {"chapter": 46, "session": "20260706",
                    "title": "Universal Basic Treasure"}
    # The number is stated once, by --chapter; the separator the author wrote
    # in --title is re-emitted as ": " rather than flattened to a space.
    assert body.lstrip().startswith("# Chapter 46: Universal Basic Treasure")


def test_assemble_h1_has_no_dangling_separator_without_a_title(tmp_path):
    """--chapter with no --title must not emit '# Chapter 46: '."""
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    _scene(narr, 1, "First.")
    out = tmp_path / "session_doc.md"
    proc = subprocess.run(
        [sys.executable, str(REPO / "session_doc/assemble.py"), str(narr),
         "--output", str(out), "--chapter", "46", "--title", "Chapter 46"],
        capture_output=True, text=True, cwd=REPO)
    assert proc.returncode == 0, proc.stderr
    meta, body = split_frontmatter(out.read_text())
    assert "title" not in meta
    assert body.lstrip().startswith("# Chapter 46\n")


def test_assemble_h1_survives_split_chapters(tmp_path):
    """The minted H1 must still parse as a chapter heading downstream."""
    heading = "# Chapter 46: Universal Basic Treasure"
    chapters = sc.split(f"{heading}\n\nBody.\n", "# Chapter ")
    assert len(chapters) == 1
    assert sc.heading_title(heading, "# Chapter ") == "Universal Basic Treasure"


def test_assemble_without_chapter_is_unchanged(tmp_path):
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    _scene(narr, 1, "First.")
    out = tmp_path / "session_doc.md"
    proc = subprocess.run(
        [sys.executable, str(REPO / "session_doc/assemble.py"), str(narr),
         "--output", str(out)],
        capture_output=True, text=True, cwd=REPO)
    assert proc.returncode == 0, proc.stderr
    text = out.read_text()
    assert text.startswith("# 20260706\n")
    assert "---\nchapter" not in text


# ── read points strip metadata ───────────────────────────────────────────

def test_stamped_chapter_reads_as_body_only():
    stamped = ("---\nchapter: 46\nsession: '20260706'\ntitle: T\n---\n"
               "# Chapter 46 T\n\nProse.\n")
    meta, body = split_frontmatter(stamped)
    assert meta["chapter"] == 46
    assert "session" not in body and body.startswith("# Chapter 46 T")
