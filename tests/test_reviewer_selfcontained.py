"""The reviewer is one offline file, and it agrees with the exporter (#455).

Contract W1 and W2. These are the two things about the reviewer that CAN be
checked here, and they are the two that matter:

- **W1, self-containment.** The page's whole premise is that it works at work,
  on a phone, in airplane mode, from local storage. One `<link>` to a font would
  make it render wrong offline; one `fetch` would make it fail. A remote
  reference is not a style issue, it is the feature not working.
- **W2, version agreement.** The page is no longer regenerated with the data —
  that is the point of #455 — so the page and the export drift independently.
  This is the only thing standing between that and a scene rendering wrong on a
  train.

What is NOT tested: the page's behaviour in a browser. No headless browser is in
this repo's dependencies, and adding one to test a review page is a poor trade.
The device checks are in `specs/029-block-document-model/tasks.md` (T047-T049).
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from session_doc.review.schema import EXPORT_VERSION, SceneExport  # noqa: E402

PAGE = ROOT / "session_doc/review/reviewer.html"

if not PAGE.is_file():
    raise AssertionError(f"the gap reviewer is missing: {PAGE}")

HTML = PAGE.read_text(encoding="utf-8")


# ── W1: no network, of any kind ─────────────────────────────────────────────

@pytest.mark.parametrize("pattern,what", [
    (r'src\s*=\s*["\']https?:', "an external script or image"),
    (r'href\s*=\s*["\']https?:', "an external stylesheet or link"),
    (r'src\s*=\s*["\']//', "a protocol-relative resource"),
    (r'@import\s', "a CSS @import"),
    (r'XMLHttpRequest', "an XMLHttpRequest"),
    (r'\bimport\s*\(\s*["\']https?:', "a remote dynamic import"),
    (r'<script[^>]+\bsrc\s*=', "an external script tag"),
    (r'fetch\s*\(\s*["\`\']https?:', "a fetch to an absolute URL"),
    (r'fetch\s*\(\s*["\`\']//', "a fetch to another origin"),
])
def test_the_page_never_reaches_another_origin(pattern, what):
    """**Amended, with the reason.**

    W1 originally forbade `fetch` outright, because the page was designed as an
    offline file on the premise that the machine holding the campaign was
    unreachable from work. That premise was false — a tailnet reaches it — and
    the offline route did not even run scripts on the device, while the served
    route did. So the page now saves to whatever served it (#455, Q3 amended).

    What must NOT weaken is the part that was actually load-bearing: it talks to
    its own origin and to nothing else. No absolute URL appears anywhere, so the
    page cannot phone home wherever it is opened from, and opened as a plain
    file it degrades to the clipboard rather than failing.
    """
    assert not re.search(pattern, HTML, re.IGNORECASE), (
        f"reviewer.html contains {what}. It may talk to the origin that served "
        f"it and to nothing else."
    )


def test_every_fetch_is_a_relative_path():
    """The positive form of the rule above: enumerate them and check each."""
    targets = re.findall(r'fetch\(\s*("(?:[^"]*)"|[^,)]+)', HTML)
    assert targets, "no fetch at all — the save path is missing"
    for target in targets:
        assert not re.search(r'https?:|^\s*["\']//', target), target
        assert '"record/' in target or '"scene/' in target, target


def test_the_page_still_works_with_no_server():
    """Opened as a file it must degrade, not break: the paste box remains, and
    the GM is told their rulings are not being written anywhere."""
    assert "servedFromDisk" in HTML
    assert 'if (!servedFromDisk()) setSaveState("offline")' in HTML
    assert "copy the review before you leave" in HTML


def test_a_failed_save_is_reported_loudly():
    """A closed laptop or a dropped tailnet must not look like a save. The
    rulings are still in the page, so the clipboard is the fallback — but only
    if the GM knows to use it."""
    assert "NOT SAVED" in HTML
    assert "could not reach the server" in HTML


def test_the_page_is_one_file_with_its_own_styles_and_script():
    assert "<style>" in HTML and "<script>" in HTML
    assert "</html>" in HTML


def test_the_page_declares_a_viewport_so_it_is_readable_on_a_phone():
    """The primary surface is a mobile browser. Without this the page renders at
    desktop width and the review is unusable on the device it was built for."""
    assert re.search(r'<meta[^>]+name=["\']viewport["\']', HTML)


# ── W2: the page and the exporter agree ─────────────────────────────────────

def test_the_page_declares_the_exporter_s_schema_version():
    """The guard that exists BECAUSE the page is not regenerated per session.

    `#455` inverts the artifact workflow: one versioned page, saved once, fed
    versioned data. That makes the export an interface, and an interface with
    two independently-edited sides needs exactly this check.
    """
    m = re.search(r"const\s+SCHEMA_VERSION\s*=\s*(\d+)\s*;", HTML)
    assert m, "reviewer.html does not declare SCHEMA_VERSION"
    assert int(m.group(1)) == EXPORT_VERSION, (
        f"the reviewer understands version {m.group(1)} and the exporter writes "
        f"{EXPORT_VERSION}. One of them was changed without the other."
    )


def test_the_page_refuses_a_version_it_does_not_understand():
    """W3 — reported, not rendered. A partial render is the failure a GM would
    not notice until the rulings were already against the wrong text."""
    assert "parsed.version !== SCHEMA_VERSION" in HTML


def test_the_page_reports_a_truncated_paste_rather_than_rendering_it():
    """W4. A mobile clipboard truncating mid-paste is realistic; half a scene
    rendered as though whole is not something the GM can see."""
    assert "truncated" in HTML


# ── The two figures, and the two payloads ───────────────────────────────────

def test_the_page_shows_ruled_and_written_separately():
    """W5 / SC-002a. A single number would understate a finished triage or
    overstate an unfinished chapter — and the triage-then-write split is the
    GM's actual workflow, not an edge case."""
    assert "ruled" in HTML and "written" in HTML
    assert re.search(r'id="ruledBar"', HTML) and re.search(r'id="writtenBar"', HTML)


def test_the_page_offers_both_clipboard_payloads():
    """Copy as prompt for drafting anywhere; copy review for the record."""
    assert "Copy as prompt" in HTML and "Copy review" in HTML


def test_every_prose_block_is_editable():
    """W6 / US3 — #418's own framing, because the seam is where a sentence
    usually needs a tweak."""
    assert "edit this passage" in HTML


def test_the_page_warns_when_it_cannot_save():
    """FR-016. localStorage under file:// is inconsistent across mobile
    browsers, so it is probed and the GM is told BEFORE they start — not after
    twenty rulings are gone."""
    assert "probeStorage" in HTML
    assert "will be lost" in HTML


def test_every_export_field_the_page_reads_actually_exists():
    """The other half of W2, and cheap.

    The version check catches a deliberate schema change. This catches the
    careless one: the page reading `data.sceneName` while the exporter writes
    `scene_name`. Both sides are hand-edited and they are in different
    languages, so nothing else would notice until a phone showed `undefined`.
    """
    fields = set(SceneExport.model_fields)
    read = set(re.findall(r"\bdata\.([A-Za-z_][A-Za-z0-9_]*)", HTML))
    unknown = read - fields
    assert not unknown, (
        f"reviewer.html reads {sorted(unknown)} off the export, which "
        f"session_doc/review/schema.py does not define. Known fields: "
        f"{sorted(fields)}"
    )


def test_every_block_field_the_page_reads_actually_exists():
    """Union of both block shapes, because the page handles both.

    `b` is an export block when rendering a scene and an **authored** block when
    loading a record back from disk, and a regex cannot tell them apart. Pinning
    only the export's fields made this fail on `b.disposition` — a false alarm
    against correct code, which is the way a guard like this earns deletion.
    Widened rather than dropped: it still catches `b.sceneName` for
    `b.scene_name`, which is the typo it exists for.
    """
    from session_doc.authored import AuthoredBlock
    from session_doc.review.schema import ExportBlock

    fields = set(ExportBlock.model_fields) | set(AuthoredBlock.model_fields)
    read = set(re.findall(r"\bb\.([A-Za-z_][A-Za-z0-9_]*)", HTML))
    unknown = read - fields
    assert not unknown, f"reviewer.html reads {sorted(unknown)} off a block"


def test_a_block_can_be_copied_out_for_editing_elsewhere():
    """Editing a paragraph in a phone textarea is possible and unpleasant.

    The block model's value on a mobile device is that one piece can be lifted
    out, rewritten somewhere with a real keyboard, and pasted back — so "every
    block is editable" needs a copy affordance beside the edit one, not just the
    edit one.
    """
    assert "copy this passage" in HTML     # the model's prose
    assert "copy this gap" in HTML         # the model's statement of what belongs there


def test_the_bar_still_offers_the_two_whole_scene_payloads():
    """Per-block copy is additional, not a replacement: drafting every
    outstanding gap at once is a different job from rewriting one paragraph."""
    assert "Copy as prompt" in HTML and "Copy review" in HTML


def test_the_review_payload_is_escaped_to_ascii_too():
    """The way OUT is the same channel as the way in, and it carries prose the
    GM actually wrote — so it gets the same defence as the export."""
    assert "function asciiSafe" in HTML
    assert "asciiSafe(JSON.stringify" in HTML


def test_the_review_is_written_in_document_order():
    """`Object.entries` hands back the order the gaps were CLICKED, which put
    gap-4 before gap-1 in the first real review off this page. A record is read
    and diffed against the scene it belongs to, so it follows the scene."""
    assert "data.blocks.map((b, i) => [b.id, i])" in HTML
    assert "order.get(a[0])" in HTML


def test_the_scene_can_be_filtered_to_what_is_outstanding():
    """Two filters, not one 'unanswered' toggle.

    The reviewer tracks two completions, and "unanswered" means a different
    thing in each session: a triage pass on a phone ends with every gap ruled
    `mine` and nothing written, and that is success rather than a backlog. One
    toggle would have to pick a side and be wrong for the other.
    """
    assert 'data-view="unruled"' in HTML
    assert 'data-view="unwritten"' in HTML
    assert 'data-view="all"' in HTML


def test_a_filtered_gap_keeps_its_real_number():
    """`Gap 4 / 6` says where you are in the scene. Renumbering a worklist
    would lose that, and the number is how a gap is referred to."""
    assert "keeps its real number even when filtered" in HTML


def test_the_source_turns_are_available_in_every_view():
    """The GM turns are the context a gap is ruled against; the surrounding
    prose is not. So filtering hides the prose and never the table."""
    assert "The source turns stay put in every view" in HTML
