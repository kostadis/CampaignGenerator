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
    (r'\bfetch\s*\(', "a fetch() call"),
    (r'XMLHttpRequest', "an XMLHttpRequest"),
    (r'\bimport\s*\(\s*["\']https?:', "a remote dynamic import"),
    (r'<script[^>]+\bsrc\s*=', "an external script tag"),
])
def test_the_page_makes_no_network_request(pattern, what):
    """A GM opening this on a train has no network. Anything here would either
    fail silently or render the page wrong, and they would not know which."""
    assert not re.search(pattern, HTML, re.IGNORECASE), (
        f"reviewer.html contains {what}. The page must work offline, from a "
        f"file:// URL, with no server and no connection."
    )


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
    from session_doc.review.schema import ExportBlock

    fields = set(ExportBlock.model_fields)
    read = set(re.findall(r"\bb\.([A-Za-z_][A-Za-z0-9_]*)", HTML))
    unknown = read - fields
    assert not unknown, f"reviewer.html reads {sorted(unknown)} off a block"
