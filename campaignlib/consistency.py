"""Pure prompt and wire-protocol helpers for grouped consistency audits."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class GroupedConsistencyProtocolError(ValueError):
    """The model response cannot be attributed completely and safely."""


@dataclass(frozen=True)
class ConsistencyDocument:
    """One explicitly selected peer document in a grouped audit."""

    identifier: str
    path: Path
    text: str


@dataclass(frozen=True)
class GroupedConsistencyResult:
    """A validated, human-readable grouped consistency report."""

    report: str
    issue_count: int


_MARKER_RE = re.compile(
    r"^<<<CG-(?:(?:CHECK (?P<identifier>D\d+))|(?P<cross>CROSS)) "
    r"(?P<action>BEGIN|END)>>>$",
    re.MULTILINE,
)
_REQUIRED_FINDING_FIELDS = (
    "**Location**",
    "**Issue**",
    "**Evidence**",
    "**Suggested fix**",
)
_TARGET_TEXT_FIELD = "**Target text**"
_TARGET_TEXT_RE = re.compile(
    r"^\s*(?:[-*]\s+)?\*\*Target text\*\*:\s*(?P<excerpt>\S.*)\s*$",
    re.MULTILINE,
)
_MARKDOWN_TABLE_ROW_RE = re.compile(
    r"^\|\s*(?P<wrong>[^|]+?)\s*\|\s*(?P<right>[^|]+?)\s*\|\s*$"
)


def _correction_anchors(
    document: ConsistencyDocument, context_parts: Sequence[str]
) -> list[tuple[str, str]]:
    """Return exact wrong-form table entries that occur in one target.

    Correction glossaries can be tens of thousands of characters long. These
    compact anchors are attention aids, not verdicts: the full glossary remains
    the authority and appears once in shared context.
    """
    anchors_by_form: dict[str, tuple[int, str, str]] = {}
    for context in context_parts:
        context_label = context[:250].casefold()
        if "correction" not in context_label and "glossar" not in context_label:
            continue
        for line in context.splitlines():
            match = _MARKDOWN_TABLE_ROW_RE.fullmatch(line)
            if match is None:
                continue
            wrong_cell = match.group("wrong").strip()
            right = match.group("right").strip()
            if wrong_cell.casefold() == "wrong" or set(wrong_cell) <= {"-", ":", " "}:
                continue
            for raw_form in wrong_cell.split(","):
                form = raw_form.strip().strip("`*_ ")
                if not form:
                    continue
                target_match = re.search(
                    rf"(?<!\w){re.escape(form)}(?!\w)",
                    document.text,
                    re.IGNORECASE,
                )
                if target_match is None:
                    continue
                position = target_match.start()
                folded_form = form.casefold()
                previous = anchors_by_form.get(folded_form)
                if previous is None or position < previous[0]:
                    anchors_by_form[folded_form] = (position, form, right)
    return [
        (form, right)
        for _position, form, right in sorted(anchors_by_form.values())
    ]


def render_grouped_prompt(
    documents: Sequence[ConsistencyDocument], context_parts: Sequence[str]
) -> str:
    """Render explicit peer targets followed by one shared context section."""
    target_blocks = []
    for document in documents:
        anchors = _correction_anchors(document, context_parts)
        if anchors:
            anchor_lines = "\n".join(
                f'- `{wrong}` → {right}' for wrong, right in anchors
            )
            anchor_block = (
                "\n\nMechanical glossary matches (review every item; these are "
                "attention anchors, not automatic verdicts):\n\n" + anchor_lines
            )
        else:
            anchor_block = ""
        target_blocks.append(
            f"### {document.identifier} — {document.path.as_posix()}\n\n"
            "Audit this target completely: prose/summary first, then every "
            "speaker header and every blockquote line. Do not declare it CLEAN "
            "after checking only its summary."
            f"{anchor_block}\n\n"
            f"<<<CG-TARGET {document.identifier} BEGIN>>>\n"
            f"{document.text}\n"
            f"<<<CG-TARGET {document.identifier} END>>>"
        )

    return "\n\n---\n\n".join(
        [
            "## Documents to Check\n\n"
            "The following files are peer targets under review. They are not "
            "campaign evidence for one another.\n\n"
            + "\n\n".join(target_blocks),
            "## Campaign Context\n\n" + "\n\n---\n\n".join(context_parts),
        ]
    )


def _section_key(match: re.Match) -> str:
    return "CROSS" if match.group("cross") else match.group("identifier")


def _validate_body(
    key: str, body: str, document: ConsistencyDocument | None = None
) -> None:
    if not body:
        raise GroupedConsistencyProtocolError(f"empty section {key}")
    if body == "CLEAN":
        return

    finding_count = body.count("**Location**")
    bad_counts = [
        field
        for field in _REQUIRED_FINDING_FIELDS
        if body.count(field) != finding_count or finding_count == 0
    ]
    if bad_counts:
        raise GroupedConsistencyProtocolError(
            f"section {key} has findings without one complete set of required "
            "fields per finding: " + ", ".join(bad_counts)
        )
    if key == "CROSS" and body.count("**Affected documents**") != finding_count:
        raise GroupedConsistencyProtocolError(
            "section CROSS does not have one **Affected documents** field per finding"
        )
    if key != "CROSS":
        if document is None:
            raise GroupedConsistencyProtocolError(
                f"section {key} cannot be attributed to a target document"
            )
        if body.count(_TARGET_TEXT_FIELD) != finding_count:
            raise GroupedConsistencyProtocolError(
                f"section {key} does not have one {_TARGET_TEXT_FIELD} field "
                "per finding"
            )
        excerpts = [
            match.group("excerpt").strip()
            for match in _TARGET_TEXT_RE.finditer(body)
        ]
        if len(excerpts) != finding_count:
            raise GroupedConsistencyProtocolError(
                f"section {key} has an empty or multiline {_TARGET_TEXT_FIELD} field"
            )
        missing_excerpts = [
            excerpt for excerpt in excerpts if excerpt not in document.text
        ]
        if missing_excerpts:
            raise GroupedConsistencyProtocolError(
                f"section {key} contains {_TARGET_TEXT_FIELD} not found verbatim "
                "in that target: " + "; ".join(repr(item) for item in missing_excerpts)
            )


def normalize_grouped_response(
    text: str, documents: Sequence[ConsistencyDocument]
) -> GroupedConsistencyResult:
    """Validate exact grouped coverage and render a marker-free report.

    The protocol is deliberately all-or-nothing. A missing, duplicated,
    unknown, nested, empty, or malformed section makes the entire response
    unusable; callers must not publish a partial review queue.
    """
    for line in text.splitlines():
        if "<<<CG-" in line and _MARKER_RE.fullmatch(line) is None:
            raise GroupedConsistencyProtocolError(
                f"malformed marker: {line.strip()}"
            )

    requested = [document.identifier for document in documents]
    requested_set = set(requested)
    documents_by_identifier = {
        document.identifier: document for document in documents
    }
    sections: dict[str, str] = {}
    completed_order: list[str] = []
    opened: set[str] = set()
    open_key: str | None = None
    body_start = 0
    cursor = 0

    matches = list(_MARKER_RE.finditer(text))
    if not matches:
        raise GroupedConsistencyProtocolError("missing section markers")

    for match in matches:
        key = _section_key(match)
        action = match.group("action")

        if open_key is None and text[cursor:match.start()].strip():
            raise GroupedConsistencyProtocolError("text outside section markers")

        if key != "CROSS" and key not in requested_set:
            raise GroupedConsistencyProtocolError(f"unknown section {key}")

        if action == "BEGIN":
            if open_key is not None:
                raise GroupedConsistencyProtocolError(
                    f"nested section {key} inside {open_key}"
                )
            if key in opened:
                raise GroupedConsistencyProtocolError(f"duplicate section {key}")
            opened.add(key)
            open_key = key
            body_start = match.end()
        else:
            if open_key is None:
                raise GroupedConsistencyProtocolError(
                    f"section {key} ended without a BEGIN marker"
                )
            if key != open_key:
                raise GroupedConsistencyProtocolError(
                    f"section {key} ended while {open_key} was open"
                )
            body = text[body_start:match.start()].strip()
            _validate_body(
                key,
                body,
                None if key == "CROSS" else documents_by_identifier[key],
            )
            sections[key] = body
            completed_order.append(key)
            open_key = None

        cursor = match.end()

    if open_key is not None:
        raise GroupedConsistencyProtocolError(f"section {open_key} is incomplete")
    if text[cursor:].strip():
        raise GroupedConsistencyProtocolError("text outside section markers")

    expected_order = requested + ["CROSS"]
    missing = [key for key in expected_order if key not in sections]
    if missing:
        raise GroupedConsistencyProtocolError(
            "missing section(s): " + ", ".join(missing)
        )
    if completed_order != expected_order:
        raise GroupedConsistencyProtocolError(
            "sections are out of order: expected "
            + ", ".join(expected_order)
            + "; received "
            + ", ".join(completed_order)
        )

    report_parts = [
        "# Grouped Consistency Report",
        f"**Documents checked:** {len(documents)}",
    ]
    for document in documents:
        display_path = document.path.as_posix().replace("`", "\\`")
        report_parts.append(
            f"## {document.identifier} — `{display_path}`\n\n"
            f"{sections[document.identifier]}"
        )
    report_parts.append(
        "## Cross-document findings\n\n" + sections["CROSS"]
    )
    report = "\n\n".join(report_parts).rstrip() + "\n"
    return GroupedConsistencyResult(
        report=report,
        issue_count=report.count("**Location**"),
    )
