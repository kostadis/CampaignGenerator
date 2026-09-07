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
