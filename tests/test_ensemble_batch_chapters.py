"""ensemble_batch.py --chapters accepts one or more globs/paths (the engine
contract behind the UI chapter picker's select-all / select-one / subset)."""

from pipelines.ensemble import ensemble_batch


def test_chapters_accepts_multiple_globs():
    p = ensemble_batch._build_parser()
    args = p.parse_args(["--chapters", "docs/a_*.md", "docs/b_03.md", "--out", "x.json"])
    assert args.chapters == ["docs/a_*.md", "docs/b_03.md"]


def test_chapters_single_value_still_works():
    p = ensemble_batch._build_parser()
    args = p.parse_args(["--chapters", "docs/chapters/chapter_*.md", "--out", "x.json"])
    assert args.chapters == ["docs/chapters/chapter_*.md"]
