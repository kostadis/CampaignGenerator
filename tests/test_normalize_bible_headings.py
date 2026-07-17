"""Tests for normalize_bible_headings.py.

The tool demotes bare `##`-level headings that resolve to a known character
name down to `###`, so a chapter that mixes `## <date>` and bare `## <Name>`
headings at the same level becomes internally consistent with the legacy
`## <date>` / `### <Name>` two-tier convention. Every other heading shape
(dates, recap section titles, the current `## Name — Scene` format) must be
left untouched.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.grounding.normalize_bible_headings import apply_demotions, find_demotions  # noqa: E402

KNOWN = {"zalthir", "daz", "grygum", "thorin"}


def _bare_h2_lines(text: str) -> list[str]:
    """Lines that are exactly `##`-level (not `###`) — for asserting demotion."""
    return re.findall(r'^##(?!#)\s+.+$', text, re.MULTILINE)


def test_mixed_chapter_demotes_only_the_name_line():
    text = (
        "# Chapter 16 Wanna Bet on Who Dies First?\n\n"
        "## 9th day of the 1st Tenday of Myrtul 1493\n\n"
        "Some prose happens.\n\n"
        "## Zalthir\n\n"
        "I said something.\n"
    )
    demotions = find_demotions(text, KNOWN)
    assert len(demotions) == 1
    result = apply_demotions(text, demotions)
    assert "## 9th day of the 1st Tenday of Myrtul 1493" in _bare_h2_lines(result)[0]
    assert "### Zalthir" in result
    assert "Zalthir" not in "".join(_bare_h2_lines(result))


def test_non_matching_heading_left_alone():
    text = (
        "# Chapter 02 Exploring the prison\n\n"
        "## 3rd day of the 2nd tenday of Taraskh, 1492\n\n"
        "![image]()\n\n"
        "## Dreams\n\n"
        "Prose describing a dream sequence in third person.\n"
    )
    demotions = find_demotions(text, KNOWN)
    assert demotions == []
    assert apply_demotions(text, demotions) == text


def test_bare_name_only_chapter_all_demoted():
    text = (
        "# Chapter 20 The Derro like Demogorgon\n\n"
        "## Grygum.\n\nHealing prose.\n\n"
        "## Daz\n\nMore prose.\n\n"
        "## Thorin\n\nEven more.\n"
    )
    demotions = find_demotions(text, KNOWN)
    assert len(demotions) == 3
    result = apply_demotions(text, demotions)
    assert result.count("### Grygum.") == 1
    assert result.count("### Daz") == 1
    assert result.count("### Thorin") == 1
    assert _bare_h2_lines(result) == []


def test_clean_two_tier_recap_and_emdash_chapters_are_no_ops():
    clean_two_tier = (
        "# Chapter 05 Pursuit\n\n"
        "## 2nd day of the 3rd Tenday of Taraskh\n\n### Daz\n\nProse.\n"
    )
    recap = (
        "# Chapter 43 The Fall of the Pudding King\n\n"
        "## Summary\n\nProse.\n\n## Scenes\n\n### Breaking into the Throne Room\n\nProse.\n"
    )
    emdash = (
        "# Chapter 47 A Spore-Filled Finale\n\n"
        "## Zalthir — The Confrontation with Ilvara\n\nI could see it in their posture.\n"
    )
    for text in (clean_two_tier, recap, emdash):
        demotions = find_demotions(text, KNOWN)
        assert demotions == [], text
        assert apply_demotions(text, demotions) == text


def test_dry_run_writes_nothing(tmp_path, capsys):
    import yaml
    from pipelines.grounding import normalize_bible_headings as nbh

    campaign_dir = tmp_path / "campaign"
    (campaign_dir / "docs").mkdir(parents=True)
    (campaign_dir / "config").mkdir(parents=True)

    bible_path = campaign_dir / "docs" / "Bible.md"
    bible_path.write_text(
        "# Chapter 20 The Derro like Demogorgon\n\n## Grygum\n\nProse.\n",
        encoding="utf-8",
    )
    (campaign_dir / "docs" / "entity_registry.yaml").write_text(
        "version: 1\ncampaign: test\nentities:\n"
        "  - name: Grygum\n    type: npc\n",
        encoding="utf-8",
    )
    (campaign_dir / "config" / "party.yaml").write_text(
        "characters: []\n", encoding="utf-8",
    )

    original = bible_path.read_text(encoding="utf-8")
    argv = ["normalize_bible_headings.py", str(bible_path), "--dry-run"]
    old_argv = sys.argv
    sys.argv = argv
    try:
        rc = nbh.main()
    finally:
        sys.argv = old_argv

    assert rc == 0
    assert bible_path.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "## Grygum" in out
    assert "dry-run" in out.lower()
