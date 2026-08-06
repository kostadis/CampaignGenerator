"""T021 — tier precedence, ambiguity reporting, and ``unclassified`` as an answer.

Three properties, in descending order of how much damage getting them wrong does:

1. **``unclassified`` is returned, not dropped** (FR-013). A file matching no
   glob is still on disk and still true. Silently omitting it is the narrowing
   this feature exists to prevent — and it would be invisible, because the
   caller cannot miss what they were never shown.
2. **Ambiguity is reported, not resolved in silence** (research D8). One
   deterministic winner, every loser named.
3. **Precedence is fixed** — the same path classifies the same way on every run,
   regardless of dict ordering or which glob was authored first.

The glob translator gets its own section because it is hand-rolled. ``fnmatch``
was rejected for a concrete reason (its ``*`` crosses ``/``, which would file
every NPC dossier under ``docs/*.md``) and the tests below are what stop someone
"simplifying" it back.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from provenance.tiers import (
    AUTHORABLE_TIERS,
    Classification,
    TrustTier,
    classify,
    compile_glob,
    matches_any,
)


def globs(**kwargs):
    """A ``TierGlobs`` stand-in; ``classify`` deliberately does not import the model."""
    return SimpleNamespace(
        authoritative=kwargs.get("authoritative", []),
        search_accelerator=kwargs.get("search_accelerator", []),
        working_reference=kwargs.get("working_reference", []),
        staging=kwargs.get("staging", []),
    )


# ── the enum ─────────────────────────────────────────────────────────────────


def test_ordinals_rank_by_trust():
    assert [t.ordinal for t in TrustTier] == [0, 1, 2, 3, 4]
    assert TrustTier.AUTHORITATIVE.ordinal < TrustTier.STAGING.ordinal
    assert TrustTier.UNCLASSIFIED.ordinal == max(t.ordinal for t in TrustTier)


def test_a_tier_serialises_as_its_own_name():
    """The CLI's ``--json`` and the MCP tool emit the strings the manifest is authored in."""
    import json

    assert json.dumps(TrustTier.WORKING_REFERENCE) == '"working_reference"'


def test_unclassified_is_not_authorable():
    """Nobody writes "this is unclassified" — it is what an absent declaration looks like."""
    assert TrustTier.UNCLASSIFIED not in AUTHORABLE_TIERS
    assert len(AUTHORABLE_TIERS) == 4


def test_authorable_tiers_are_in_ordinal_order():
    """``classify`` relies on this to report losers without re-sorting."""
    assert [t.ordinal for t in AUTHORABLE_TIERS] == sorted(t.ordinal for t in AUTHORABLE_TIERS)


# ── precedence ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tier", AUTHORABLE_TIERS)
def test_each_tier_can_win_alone(tier):
    result = classify("docs/x.md", globs(**{tier.value: ["docs/x.md"]}))
    assert result.tier is tier
    assert result.ambiguous == ()


def test_the_most_trusted_matching_tier_wins():
    result = classify(
        "docs/x.md",
        globs(authoritative=["docs/*.md"], working_reference=["docs/*.md"],
              staging=["docs/*.md"]),
    )
    assert result.tier is TrustTier.AUTHORITATIVE


def test_precedence_does_not_depend_on_authoring_order():
    """Same answer whichever glob the GM happened to write first."""
    a = classify("docs/x.md", globs(staging=["docs/*.md"], authoritative=["docs/x.md"]))
    b = classify("docs/x.md", globs(authoritative=["docs/x.md"], staging=["docs/*.md"]))
    assert a == b == Classification(TrustTier.AUTHORITATIVE, (TrustTier.STAGING,))


def test_classification_is_deterministic_across_runs():
    tiers = globs(authoritative=["docs/**/*.md"], working_reference=["docs/*.md"])
    assert len({classify("docs/x.md", tiers) for _ in range(50)}) == 1


# ── ambiguity is reported (D8) ───────────────────────────────────────────────


def test_every_losing_tier_is_recorded():
    result = classify(
        "docs/x.md",
        globs(authoritative=["docs/*.md"], search_accelerator=["docs/*.md"],
              working_reference=["docs/*.md"], staging=["**/*.md"]),
    )
    assert result.tier is TrustTier.AUTHORITATIVE
    assert result.ambiguous == (
        TrustTier.SEARCH_ACCELERATOR,
        TrustTier.WORKING_REFERENCE,
        TrustTier.STAGING,
    )
    assert result.is_ambiguous


def test_a_single_match_is_not_ambiguous():
    result = classify("docs/x.md", globs(working_reference=["docs/*.md"]))
    assert result.ambiguous == ()
    assert not result.is_ambiguous


def test_the_winner_is_never_listed_among_the_losers():
    result = classify("docs/x.md", globs(authoritative=["docs/*.md", "**/*.md"]))
    assert TrustTier.AUTHORITATIVE not in result.ambiguous
    assert result.ambiguous == ()


def test_the_fixture_overlap_is_reported_not_resolved(alpha):
    """``docs/**/*.md`` deliberately overlaps two more specific globs in the fixture."""
    chapter = classify("docs/chapters/chapter_01_arrival.md", alpha.tiers)
    assert chapter.tier is TrustTier.AUTHORITATIVE
    assert chapter.ambiguous == (TrustTier.WORKING_REFERENCE,)

    extraction = classify("docs/distill_extractions/ch01_facts.md", alpha.tiers)
    assert extraction.tier is TrustTier.SEARCH_ACCELERATOR
    assert extraction.ambiguous == (TrustTier.WORKING_REFERENCE,)


# ── unclassified is an answer (FR-013) ───────────────────────────────────────


def test_no_match_yields_unclassified_rather_than_none():
    result = classify("misc/loose_note.md", globs(authoritative=["summaries/**/*.md"]))
    assert result.tier is TrustTier.UNCLASSIFIED
    assert result.ambiguous == ()


def test_classify_never_raises_on_an_unmatched_path():
    """Dropping the file would be invisible: nobody misses what they were never shown."""
    assert classify("anything/at/all.xyz", globs()).tier is TrustTier.UNCLASSIFIED


def test_the_fixture_unclassified_file_classifies_not_disappears(alpha):
    assert classify("misc/loose_note.md", alpha.tiers).tier is TrustTier.UNCLASSIFIED


@pytest.mark.parametrize(
    "rel_path, expected",
    [
        ("summaries/session_01_opening.md", TrustTier.AUTHORITATIVE),
        ("docs/chapters/chapter_01_arrival.md", TrustTier.AUTHORITATIVE),
        ("docs/distill_extractions/ch01_facts.md", TrustTier.SEARCH_ACCELERATOR),
        ("docs/world_state.md", TrustTier.WORKING_REFERENCE),
        ("docs/npcs/keeper.md", TrustTier.WORKING_REFERENCE),
        ("docs/entity_registry.yaml", TrustTier.WORKING_REFERENCE),
        ("docs/hidden_reference.md", TrustTier.WORKING_REFERENCE),
        ("notes/scratch.md", TrustTier.STAGING),
        ("misc/loose_note.md", TrustTier.UNCLASSIFIED),
    ],
)
def test_every_fixture_path_classifies_as_designed(alpha, rel_path, expected):
    assert classify(rel_path, alpha.tiers).tier is expected


def test_a_gitignored_file_classifies_like_any_other(alpha):
    """``.gitignore`` is a version-control concern and has no vote on trust (D17)."""
    assert classify("docs/hidden_reference.md", alpha.tiers).tier is (
        TrustTier.WORKING_REFERENCE
    )


# ── glob semantics ───────────────────────────────────────────────────────────


def test_star_does_not_cross_a_separator():
    """The reason ``fnmatch`` is not used.

    With ``fnmatch``, ``docs/*.md`` matches ``docs/npcs/keeper.md`` and every NPC
    dossier in the corpus gets mis-tiered.
    """
    assert matches_any("docs/world_state.md", ["docs/*.md"])
    assert not matches_any("docs/npcs/keeper.md", ["docs/*.md"])


def test_double_star_crosses_separators():
    assert matches_any("docs/npcs/keeper.md", ["docs/**/*.md"])
    assert matches_any("docs/world_state.md", ["docs/**/*.md"])   # zero segments
    assert matches_any("a/b/c/d.md", ["**/*.md"])
    assert matches_any("d.md", ["**/*.md"])


def test_trailing_double_star_takes_everything_below():
    assert matches_any("notes/a.md", ["notes/**"])
    assert matches_any("notes/deep/b/c.txt", ["notes/**"])
    assert not matches_any("notes", ["notes/**"])


def test_double_star_only_spans_segments_when_it_is_a_whole_segment():
    """``foo**bar`` is a wildcard inside one segment, not a directory crossing."""
    assert matches_any("docs/fooXbar.md", ["docs/foo**bar.md"])
    assert not matches_any("docs/foo/x/bar.md", ["docs/foo**bar.md"])


def test_question_mark_is_one_non_separator_character():
    assert matches_any("docs/a.md", ["docs/?.md"])
    assert not matches_any("docs/ab.md", ["docs/?.md"])
    assert not matches_any("docs/a/b.md", ["docs?b.md"])


def test_character_classes_including_negation():
    assert matches_any("ch1.md", ["ch[0-9].md"])
    assert not matches_any("cha.md", ["ch[0-9].md"])
    assert matches_any("cha.md", ["ch[!0-9].md"])
    assert not matches_any("ch1.md", ["ch[!0-9].md"])


def test_an_unterminated_bracket_is_a_literal_not_a_crash():
    assert matches_any("a[b.md", ["a[b.md"])


def test_matching_is_anchored_at_both_ends():
    """Substring matching would file ``old_docs/x.md`` under ``docs/*.md``."""
    assert not matches_any("old_docs/x.md", ["docs/*.md"])
    assert not matches_any("docs/x.md.bak", ["docs/*.md"])


def test_regex_metacharacters_in_a_glob_are_literal():
    assert matches_any("docs/a+b.md", ["docs/a+b.md"])
    assert not matches_any("docs/aab.md", ["docs/a+b.md"])
    assert matches_any("docs/v1.2.md", ["docs/v1.2.md"])
    assert not matches_any("docs/v1x2.md", ["docs/v1.2.md"])


def test_matches_any_with_no_patterns_is_false():
    assert not matches_any("docs/x.md", [])


def test_compiled_globs_are_cached():
    assert compile_glob("docs/*.md") is compile_glob("docs/*.md")


def test_extension_globs_are_case_sensitive_like_rg():
    """rg's ``-g`` is case-sensitive; the classifier must not disagree with the scanner."""
    assert not matches_any("docs/X.MD", ["docs/*.md"])
