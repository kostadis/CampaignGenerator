"""Pins the deliberate divergence between the two surviving frontmatter
parsers (issue #261).

A third parser, `session_doc.assemble.parse_frontmatter` (a hand-rolled
`k: v` line splitter masquerading under the same `(dict, body)` contract as
`campaignlib.textproc.split_frontmatter`), was deleted — it was redundant
with the real YAML parser and disagreed with it on value types. The two that
remain do genuinely different jobs and must keep disagreeing:

- `campaignlib.textproc.split_frontmatter_raw` returns the frontmatter block
  RAW — the literal bytes, delimiters included — with no parsing at all,
  because a caller that reassembles `frontmatter + prose` (e.g. the `/scrub`
  Claude Code skill's apply step) needs the original block back unchanged.
  Relocated here from the now-retired `session_doc.scrub_mechanics` (issue
  #010) — it was always a shared utility, not part of what was removed.
- `campaignlib.textproc.split_frontmatter` PARSES the block into a dict and
  returns only the body, discarding the delimiters and raw bytes.

Both are run over the SAME input here so a future "these look like the same
job, let's collapse them" edit has to break these assertions first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from campaignlib.textproc import split_frontmatter, split_frontmatter_raw  # noqa: E402


TEXT = "---\nscene: 4\nscene_name: Test Scene\n---\nBody prose here.\n"


def test_raw_parser_returns_block_with_delimiters():
    frontmatter, body = split_frontmatter_raw(TEXT)
    assert frontmatter == "---\nscene: 4\nscene_name: Test Scene\n---\n"
    assert frontmatter.startswith("---\n")
    assert frontmatter.endswith("---\n")
    assert body == "Body prose here.\n"


def test_parsed_variant_returns_dict_not_raw_block():
    meta, body = split_frontmatter(TEXT)
    assert meta == {"scene": 4, "scene_name": "Test Scene"}
    assert body == "Body prose here.\n"


def test_raw_and_parsed_agree_on_body_but_diverge_on_frontmatter_shape():
    """Same input, same body split point; deliberately different frontmatter
    shape: a raw string block with delimiters vs. a parsed dict with none."""
    raw_fm, raw_body = split_frontmatter_raw(TEXT)
    parsed_fm, parsed_body = split_frontmatter(TEXT)

    assert raw_body == parsed_body
    assert type(raw_fm) is str
    assert type(parsed_fm) is dict
    assert "---" not in repr(parsed_fm)
