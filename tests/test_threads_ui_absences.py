"""014 — the Threads page's absences, guarded (T031a, T031b).

Two requirements here are about what the interface must NOT grow. Both are
easy to reintroduce by a well-meaning convenience patch, and neither shows up
as a failing feature test — only as a quietly wrong page. So they are
asserted statically, in the spirit of `tests/test_no_prefix_identity.py`.

  * FR-031 — bands, ordering, search and filters are PRESENTATION ONLY.
    Nothing in the interface may rule on, merge, group or discard a candidate,
    including by similarity between titles. Deciding two titles are the same
    thread is an identity assertion and it belongs to the GM; the engine
    matches on exact normalised titles for exactly this reason.

  * FR-028a — every band count and the excluded count is computed from the
    loaded set. A hardcoded number is the precise defect this feature
    replaced: 916 is right for OOTA, and wrong for toee (394) and Hillsfar
    (104).
"""

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"
THREADS = FRONTEND / "views" / "grounding" / "Threads.vue"


def _source() -> str:
    assert THREADS.exists(), f"{THREADS} is missing"
    return THREADS.read_text(encoding="utf-8")


def _code_only() -> str:
    """The file with comments stripped.

    The similarity guard must read CODE, not prose: the page's own module
    comment explains that it does no clustering and no "did you mean", and a
    guard that fails on the sentence describing the absence is a guard that
    punishes documenting it.
    """
    src = _source()
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)      # HTML comments
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)       # /* block */
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)        # // line
    return src


# ── FR-031: no similarity-based grouping (T031a) ─────────────────────────

SIMILARITY_MARKERS = [
    "levenshtein", "jaro", "damerau", "fuzzysort", "fuse.js", "new Fuse",
    "difflib", "similarity", "editDistance", "edit_distance",
    "did you mean", "didYouMean", "cluster", "kmeans", "dedupe",
    "looksLike", "probablySame", "mergeSimilar",
]


@pytest.mark.parametrize("marker", SIMILARITY_MARKERS)
def test_threads_page_has_no_similarity_helper(marker):
    src = _code_only().lower()
    assert marker.lower() not in src, (
        f"Threads.vue contains {marker!r}. Grouping candidates by title "
        f"similarity is an identity decision, and FR-031 reserves it for the "
        f"GM — the engine matches on exact normalised titles for the same "
        f"reason. Show the variants; never merge them."
    )


def test_threads_page_does_not_auto_rule(_=None):
    """FR-022: nothing here ratifies, merges or infers on its own."""
    src = _source()
    for bad in ("autoRatify", "autoAccept", "acceptAll", "ratifyAll",
                "rejectAll", "selectAll", "bulkRule"):
        assert bad not in src, f"Threads.vue defines {bad!r} — no bulk/auto ruling (FR-007, SC-004)"


# ── FR-028a: counts are computed, never written in (T031b) ───────────────

def test_band_and_excluded_counts_are_computed_not_literal():
    """The counts must come from the loaded payload.

    Checked by shape rather than by value: every count rendered on the page
    interpolates an expression (`{{ recurring.length }}`,
    `{{ excludedCount }}`), and no interpolation is a bare number.
    """
    src = _source()
    # Bands are data now (one card template, three bands), so the per-band
    # count is rendered as `band.items.length`. What matters is unchanged:
    # every count is an expression over the loaded set.
    for expr in ("band.items.length", "excludedCount"):
        assert expr in src, f"{expr} is not rendered — counts must be derived"
    for derived in ("const recurring", "const repeated", "const otherMatches",
                    "const excludedCount"):
        assert derived in src, f"{derived} missing — bands must be computed"

    # No mustache interpolation may be a bare integer literal.
    literals = [m for m in re.findall(r"\{\{\s*([0-9][0-9,]*)\s*\}\}", src)]
    assert not literals, (
        f"Threads.vue interpolates literal number(s) {literals}. Band and "
        f"excluded counts differ by an order of magnitude across corpora "
        f"(916 / 394 / 104); a literal is wrong everywhere but one campaign."
    )

    # And the measured figures themselves must not appear as constants.
    for corpus_specific in ("916", "394", "104", "986", "415"):
        assert not re.search(rf"=\s*{corpus_specific}\b", src), (
            f"Threads.vue assigns the corpus-specific constant "
            f"{corpus_specific} — that number belongs to one campaign only")


def test_no_show_all_control(_=None):
    """FR-028 — the excluded tail is reached by search or chapter filter, not
    by a button that dumps ~1000 rows into the page.

    NOTE: this covers the *absence of the control*, which is what can be
    checked without a component-test harness. T045a (proving the rendered
    page exposes no such affordance) remains an open GM question and is NOT
    closed by this test.
    """
    # _code_only(): the page's own comment explains that the third band is
    # NOT a "Show all" control, and a guard that fails on the sentence
    # documenting the absence punishes documenting it.
    src = _code_only()
    for bad in ("Show all", "showAll", "show_all", "Show everything", "Load all"):
        assert bad not in src, f"Threads.vue offers {bad!r} (FR-028)"


# ── the band predicate itself (research D20) ─────────────────────────────

def test_repeated_band_uses_less_than_two_not_equals_one():
    """A chapterless candidate has ZERO chapters. `== 1` would drop it into
    the excluded tail — the one place the GM cannot see the "no chapter
    recorded" warning D20 put on the card."""
    src = _source()
    assert "spans < 2" in src, "the repeated band must use `< 2`, not `== 1`"
    assert "spans === 1" not in src and "spans == 1" not in src


# ── FR-029/FR-030: the tail must be REACHABLE, not merely counted ─────────

def test_every_band_including_the_tail_is_rendered():
    """The defect that shipped in #346, guarded.

    `bandOf()` sorts candidates into three buckets, but the template rendered
    only two loops — so a `once`-band candidate was counted by
    `excludedCount` and displayed by nothing. Typing its exact title into the
    search box updated the count and produced no card. On an OOTA-sized
    harvest that was ~916 of 986 candidates unreachable, under a line telling
    the GM to "search or filter by chapter to reach them".

    The structural fix is that bands are DATA: one card template iterates
    `bands`, so a bucket cannot be computed and then silently not rendered.
    """
    src = _source()
    # every bucket bandOf() can return has a band entry
    for key in ("'recurring'", "'repeated'", "'once'"):
        assert key in src, f"bandOf bucket {key} is missing"
    assert "v-for=\"band in bands\"" in src, (
        "bands must be rendered from one data-driven loop; per-band copies of "
        "the card template are how the third band came to be omitted")
    assert "v-for=\"p in band.items\"" in src, "cards must come from band.items"

    # ...and there is exactly ONE candidate-card loop, not one per band
    assert src.count('v-for="p in band.items"') == 1
    for stale in ('v-for="p in recurring"', 'v-for="p in repeated"'):
        assert stale not in src, (
            f"{stale} is a per-band card copy — the duplication this replaced")


def test_the_tail_appears_only_in_response_to_a_query():
    """Reachable by search is not the same as a "Show all" button (FR-028).

    The `once` band must be gated on `searching`, so the page never dumps the
    whole tail on its own, and `excludedCount` must go to zero when it does
    render — a page that shows the tail must not simultaneously claim to be
    hiding it.
    """
    src = _code_only()
    assert "searching.value ? orderBand" in src, (
        "the tail band must be gated on an active query")
    assert "searching.value ? 0 :" in src, (
        "excludedCount must be 0 while the tail is on screen")


# ── the signpost must cover #337's own case (review finding) ─────────────

PROJECTIONS_VUE = FRONTEND / "views" / "grounding" / "ProjectionSections.vue"


def test_blocked_sections_are_not_scoped_to_the_selection():
    """`grounding_sections` assembles over SPECS[doc] — the doc's FULL section
    list — regardless of `--sections`. So a build of only `spine` still dies on
    a missing required `threads` file.

    Filtering the explanation box to the SELECTED sections therefore produced
    an empty box in exactly the #337 case it exists to explain: the GM sees a
    bare `error: missing section file …/threads.md` and no route out.
    """
    src = PROJECTIONS_VUE.read_text(encoding="utf-8")
    # the FILTERING assignment, not the `= []` reset in the success branch
    i = src.index("blockedByMissingInput.value = sections.value")
    assignment = src[i:i + 300]
    assert "selected.value.has" not in assignment, (
        "blockedByMissingInput must not be scoped to the selection — assemble() "
        "runs over the whole doc spec")
    assert "'no-input'" in assignment
