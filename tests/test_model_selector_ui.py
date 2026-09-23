"""The app-wide MODEL control accepts a typed id on every backend.

Feature 024 (``specs/024-claude-model-freetext/``). The sidebar used to fork:
a ``<select>`` over the ``server.config.MODELS`` registry on ``anthropic`` and
``claude-code``, a free-text ``<input>`` on the other three. That fork made a
hand-maintained snapshot authoritative on exactly the two backends where it goes
stale — a Claude model released after the last CampaignGenerator release was
unreachable from the UI at any price, while the CLI would have run it happily.
``campaignlib/selection.py::compatible()`` already spells out why, and then
declines to use ``MODELS``:

    testing against it would silently reject a legitimate Claude id that simply
    hadn't been added yet — quietly refusing a model the caller is entitled to
    run.

Constitution Principle XI names that shape: the Orphaned Capability, "a flag that
exists in the engine, works correctly, and no human can reach."

**What these assertions prove and what they do not.** There is no Vue
component-test harness in this repo (issue #345), so these are source-level
checks: they prove the control is *shaped* right in the file — one element, no
backend fork, suggestions not options — not that it renders, persists, or
round-trips. That is ``frontend/e2e/model-selector.spec.ts``'s job, and
``specs/024-claude-model-freetext/quickstart.md`` §4's. The gap is stated here
rather than counted as coverage.

The block-scoped helper below matters: ``.model-select`` is shared with the
THINKING / EFFORT / REASONING selects in the same sidebar footer, so *file-wide*
counting of that class or of ``<select`` proves nothing about the MODEL control.
Every structural assertion is made against the extracted ``model-selector``
block.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SIDEBAR = "frontend/src/components/layout/AppSidebar.vue"


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _model_selector_block(source: str) -> str:
    """The ``<div class="model-selector">…</div>`` markup, and only that.

    Anchored on the opening tag and closed by the first ``</div>`` at the same
    indentation, which is how the sidebar's footer blocks are written. Returns
    the inner markup so a caller can assert on what the control is made of
    without the rest of the footer leaking in.
    """
    match = re.search(
        r'<div class="model-selector">(.*?)\n      </div>',
        source,
        re.DOTALL,
    )
    assert match, (
        'no <div class="model-selector"> block found in the sidebar — the MODEL '
        "control was renamed or removed; update this test with it"
    )
    return match.group(1)


@pytest.fixture(scope="module")
def sidebar() -> str:
    return _source(SIDEBAR)


@pytest.fixture(scope="module")
def block(sidebar: str) -> str:
    return _model_selector_block(sidebar)


# ── The control is one input, on every backend ──────────────────────────────

def test_model_control_is_an_input(block):
    """FR-001 / contract C1. A ``<select>`` cannot express an id it was not
    built with, which is the whole defect."""
    assert "<input" in block


def test_model_control_has_no_select(block):
    """Block-scoped on purpose: the sidebar footer has three other
    ``.model-select`` selects (THINKING, EFFORT, REASONING) that are legitimate
    fixed vocabularies published by the server. Only the MODEL control must not
    be one."""
    assert "<select" not in block


def test_model_control_is_not_forked_by_backend(block):
    """Contract C2. The requirement is structural, not behavioural: as long as
    the component *can* render two different widgets, the two can drift, and
    drift is what this feature exists to end. A widened condition is a fork
    waiting to narrow again."""
    assert "v-if" not in block
    assert "v-else" not in block


def test_free_text_fork_computed_is_gone(sidebar):
    """``modelIsFreeText`` was the fork's condition. Deleting the branch but
    keeping the computed leaves the next contributor an obvious hook to
    re-fork on."""
    assert "modelIsFreeText" not in sidebar


# ── The curated ids are suggestions, not choices ────────────────────────────

def test_suggestions_are_offered_through_a_datalist(block):
    """FR-002 / contract C3. The shortlist survives — SC-004 forbids trading
    one friction for another — but as suggestions attached to a text field."""
    assert "<datalist" in block
    assert 'list="cg-model-ids"' in block


def test_datalist_is_wired_to_the_input(block):
    """An ``id`` that no input's ``list`` attribute names renders nothing, and
    fails silently. Assert both halves are present exactly once."""
    assert block.count('list="cg-model-ids"') == 1
    assert block.count('id="cg-model-ids"') == 1


def test_no_backend_is_named_inside_the_control_markup(block):
    """FR-011, the strong form. The markup must be backend-agnostic: every
    per-backend difference that remains (suggestions, placeholder text) is
    resolved in a computed and reaches the template as one expression.

    A backend literal appearing *in the block* is how the fork grows back —
    first as a ternary on the placeholder, then on the element. Keeping the
    branching in script means a re-fork has to be a visible structural edit.
    """
    for backend in ("'anthropic'", "'claude-code'", "'dgx'", "'openrouter'", "'codex-cli'"):
        assert backend not in block, (
            f"{backend} is named inside the MODEL control's markup; put the "
            "branch in a computed so the template stays uniform"
        )


def test_registry_is_not_rendered_as_options_of_a_chooser(sidebar):
    """The old markup was ``<option v-for="m in config.models">`` inside a
    ``<select>``. Its absence is what makes ``MODELS`` advisory: an id absent
    from the list must be enterable anyway (FR-007)."""
    assert '<option v-for="m in config.models"' not in sidebar


# ── The registry stays the server's to publish ──────────────────────────────

def test_no_model_id_is_hardcoded_in_the_component(sidebar):
    """A literal id list here would be a second declaration of a vocabulary
    that already has an owner (``server/config.py::MODELS``, served by
    ``GET /api/config/models``) — Principle XII. Placeholders naming one
    example id are fine and are excluded by requiring three on one line."""
    for line in sidebar.splitlines():
        assert line.count("claude-") < 3, (
            f"looks like an inlined model list, which server/config.py owns: {line.strip()}"
        )
