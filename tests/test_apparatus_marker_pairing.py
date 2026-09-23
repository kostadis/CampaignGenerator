"""Every apparatus marker the assembler strips must have a live producer.

`26ec5b0` deleted the prompt that emitted `<!-- table-speech reclassified: … -->`
and left everything downstream standing: the stripper in `assemble.py`, its
seven tests, a mandatory `## Reclassified table speech` section in the
out-of-repo `/voice-critic` skill, `/scrub`'s comment masking, and `/no-mech`'s
guidance. Nothing failed. The suite even *asserted* the marker's absence from
every prompt, so the deletion looked deliberate and complete from inside the
repo while the review queue it fed reported a permanent, false "none" (#396).

The gap was that nothing tied `APPARATUS_MARKERS` to a producer. These tests
are that binding. Three of the four markers are written by a human or by a
skill living outside this repo, which this repo cannot check — so the exemption
is declared per-marker and counted, rather than left as an absence.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doc import narrate  # noqa: E402
from session_doc.apparatus import (  # noqa: E402
    APPARATUS_MARKERS,
    strip_audit_comments,
)
from test_narrate_template_contract import _bundle_scene  # noqa: E402
from test_session_doc_prompts import _build_matrix  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _every_narration_prompt() -> list[str]:
    """All 256 single-scene flag combinations, plus the bundled prompt.

    Walking one representative mode is not enough: a producer restored only
    under `--prose-mode` would satisfy a spot check while leaving the default
    path making the same silent scope call, which is #396 in miniature.
    """
    prompts = [p for key, p in _build_matrix().items() if not key.startswith("__")]
    system, user = narrate.build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice"), _bundle_scene(2, "Departure", "Bob")],
        prose_mode=True,
    )
    prompts.append(system + "\n" + user)
    return prompts


def test_every_apparatus_marker_declares_where_it_comes_from():
    """The forcing function: a new stripper cannot land without an origin.

    The literal set is deliberate. Adding a marker to `APPARATUS_MARKERS`
    fails here until someone states who writes it, which is the question
    `26ec5b0` was never asked.
    """
    assert {m.pattern for m in APPARATUS_MARKERS} == {
        r"table-speech\s+reclassified:",
        r"hand-fixed",
        r"Editorial\s+note:",
        r"Scene\s+boundary\s+note:",
    }
    for marker in APPARATUS_MARKERS:
        assert marker.origin in {"narrate-prompt", "external"}, marker
        assert marker.produced_by.strip(), marker


def test_an_in_repo_marker_is_asked_for_by_every_narration_prompt():
    """The test `26ec5b0` would have failed."""
    in_repo = [m for m in APPARATUS_MARKERS if m.origin == "narrate-prompt"]
    assert in_repo, "the hatch is the one marker this repo produces (#396)"

    prompts = _every_narration_prompt()
    for marker in in_repo:
        producer = REPO / marker.produced_by
        assert producer.is_file(), f"{marker.pattern}: {marker.produced_by} is gone"
        assert re.search(marker.pattern, producer.read_text(encoding="utf-8")), marker
        for prompt in prompts:
            assert re.search(marker.pattern, prompt), (
                f"{marker.pattern} is stripped at assembly but reaches no model"
            )


def test_the_comment_the_prompt_shows_the_model_is_the_one_assembly_strips():
    """Producer and consumer, run against each other.

    The two halves are a prompt template and a regex in another module, and
    nothing but this makes them agree on the literal text. Reword the template
    to `<!-- table speech reclassified: … -->` — a space, not a hyphen — and
    the model writes a comment that travels straight into the assembled
    document and on into the bible.
    """
    examples = re.findall(r"<!--.*?-->", narrate.AUDIT_HATCH_INSTRUCTION, re.DOTALL)
    assert examples, "the hatch template must show the model a literal example"
    for example in examples:
        assert strip_audit_comments(example + "\n") == "", example


def test_an_external_marker_is_exempt_from_the_producer_check_and_says_why():
    """Documentation as assertion: the exemption is named and counted."""
    external = [m for m in APPARATUS_MARKERS if m.origin == "external"]
    assert len(external) == 3
    for marker in external:
        assert "skill" in marker.produced_by or "human" in marker.produced_by, marker
    # Flipping one of these to "narrate-prompt" — say, if `Editorial note:`
    # ever gains an in-repo producer — starts enforcing it above automatically.


# ── #454 — the gap marker is content, and has a live producer ───────────────

GAP_MARKER = "[GM NARRATION — TO BE WRITTEN:"


def test_the_gap_marker_is_not_registered_as_apparatus():
    """It must NOT join `APPARATUS_MARKERS`, and that is the opposite of the
    reflex this file otherwise teaches.

    The registry drives `strip_audit_comments`, which *removes* what it matches
    from the assembled document. A gap marker is the feature's output — #455
    exists to answer it and #456 to edit it — so registering it would delete the
    thing at assembly. The registry is also comment-shaped (`<!-- … -->`); the
    marker is a bracketed line.
    """
    assert not any("GM NARRATION" in m.pattern for m in APPARATUS_MARKERS)


def test_the_gap_marker_survives_assembly():
    """The other half of the same fact, asserted on behaviour rather than on
    the registry's contents — a future stripper written some other way would
    still fail here."""
    body = (
        "She turned toward the door.\n\n"
        f"{GAP_MARKER} the counting house is loud and full of clerks]\n\n"
        "<!-- table-speech reclassified: \"roll for it\" -->\n"
        "\"After you,\" she said.\n"
    )
    stripped = strip_audit_comments(body)
    assert GAP_MARKER in stripped                       # content survives
    assert "table-speech reclassified" not in stripped  # apparatus does not


def test_the_gap_marker_has_a_live_producer():
    """The binding `26ec5b0` never had: it deleted the prompt that emitted
    `table-speech reclassified:` and left the stripper, its tests and three
    out-of-repo skills standing, with nothing failing.

    Deleting `gm_attribution_gap.md`, or unhooking it from the builders, must
    fail here rather than silently producing markerless renders (SC-008).
    """
    from session_doc.narrate import build_bundled_narrate_prompts, build_narrate_system
    from test_narrate_template_contract import _bundle_scene

    per_scene = build_narrate_system(examples_text=None, narrator="Alice",
                                     gap_marking=True)
    system, user = build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice")], gap_marking=True)
    assert GAP_MARKER in per_scene
    assert GAP_MARKER in system + "\n" + user


def test_no_prompt_asks_for_the_gap_marker_with_the_mode_off():
    """The producer is bound to the mode, not merely present in the repo.

    `_every_narration_prompt()` walks the whole matrix; with #454 that is 512
    single-scene combinations, half of them gap-on. Filtered to the gap-off
    half, none may request a marker.
    """
    from test_session_doc_prompts import _build_matrix

    for key, prompt in _build_matrix().items():
        if key.startswith("__") or not key.endswith("_gm0"):
            continue
        assert GAP_MARKER not in prompt, key


def test_a_name_invented_inside_a_gap_marker_is_still_reported():
    """Deliberately NOT masked, and that is the opposite call from #396.

    Audit comments are masked before the unknown-name scan because they quote
    raw table speech *verbatim* — an unmasked scan reports the very words the
    pass just removed from the fiction. A gap marker is the reverse: it is new
    prose the model wrote *about* the source. A proper noun appearing only
    inside one, and nowhere in the session's extractions, is exactly the
    invention the scan exists to catch, so masking here would build a blind
    spot into the one check that would notice the model making something up
    while summarising what it declined to write.
    """
    from session_doc.knowledge_check import find_unknown_names

    source = "**Alice** — *the door*\n> \"After you.\"\n"
    narration = (
        "She turned toward the door.\n\n"
        "[GM NARRATION — TO BE WRITTEN: Kazneporium Ketternopappux blocks the way]\n"
    )
    unknown = find_unknown_names(strip_audit_comments(narration), [source])
    assert any("Kazneporium" in name for name in unknown)


def test_a_name_drawn_from_the_source_is_not_reported():
    """The other side: the scan's `known_texts` already include the session's
    own extractions, so a marker summarising the source stays quiet."""
    from session_doc.knowledge_check import find_unknown_names

    source = "**Aurelan Vance** — *the counting house*\n> \"What are you making?\"\n"
    narration = (
        "[GM NARRATION — TO BE WRITTEN: Aurelan Vance hurries back, out of breath]\n"
    )
    unknown = find_unknown_names(strip_audit_comments(narration), [source])
    assert not any("Aurelan" in name for name in unknown)
