"""Narration + authored record -> `.composed.md` (#455).

Deterministic: the same two inputs produce byte-identical output, every time.
No model call — this places prose a human wrote and removes blocks a human cut,
and nothing here decides anything.

**A stale record refuses.** The record names the digest of the draft it was
authored against; if the narration has changed since, composing would place the
GM's prose against text it was never written for. That is the same
self-invalidating property `transcript_corrections` gets from checking `was`
against the tape: a stale record fails loudly rather than pasting yesterday's
repair over today's words.

Anchors are written into records but matched by **nothing** here. Per-block
matching is what would let a record survive a re-narrate, and an anchor landing
an authored block on the wrong prose is the same attribution error this whole
feature exists to prevent — committed by us instead of by a model. v1 refuses;
`#456` brings the matcher and the merge-review UX to go with it.
"""

from __future__ import annotations

from pathlib import Path

from campaignlib.textproc import split_frontmatter
from session_doc.authored import AuthoredError, AuthoredRecord
from session_doc.blocks import parse_blocks

#: Stamped into the composed document so it is visibly not a thing to hand-edit
#: — the role `cg-generated` plays for a generated tape.
GENERATED_NOTE = (
    "<!-- cg-generated: composed from the narration and its .authored.yaml. "
    "Edit the record, not this file. -->"
)


class ComposeError(Exception):
    """The record does not fit the narration."""


def compose(narration_text: str, record: AuthoredRecord, *,
            digest_of=None) -> str:
    """Merge a record into a narration.

    ``authored`` and ``edited`` place the human's text; ``cut`` removes the
    block; ``mine`` and an absent entry leave the block exactly as it was — a
    gap stays a gap, which is what keeps an unfinished review visible instead
    of quietly composing to a chapter with a hole in it.
    """
    from session_doc.review.export import digest as _digest

    digest_of = digest_of or _digest
    actual = digest_of(narration_text)
    if actual != record.generated_sha256:
        raise ComposeError(
            f"Refusing to compose: the record was authored against a different "
            f"draft of {record.narration}.\n"
            f"  record was authored against: {record.generated_sha256}\n"
            f"  the narration on disk is:    {actual}\n\n"
            f"Composing anyway would place the GM's prose against text it was "
            f"never written for. Re-review the scene, or restore the draft the "
            f"record names."
        )

    meta_text, body = _split_keeping_frontmatter(narration_text)
    entries = record.by_id()
    out: list[str] = []
    for block in parse_blocks(body):
        e = entries.get(block.id)
        if e is None or e.disposition == "mine":
            out.append(block.text)
            continue
        if e.disposition == "cut":
            continue
        # authored | edited — the human's text, with the block's own trailing
        # separator preserved so the document's spacing survives.
        out.append((e.text or "").rstrip() + _trailing_separator(block.text))
    composed = "".join(out)
    return meta_text + GENERATED_NOTE + "\n\n" + composed


def _split_keeping_frontmatter(text: str) -> tuple[str, str]:
    """Return the frontmatter *as written* plus the body.

    `split_frontmatter` parses the metadata into a dict, which would round-trip
    through a YAML dumper and reorder keys. The composed document should carry
    the narration's own frontmatter unchanged.
    """
    meta, body = split_frontmatter(text)
    if not meta:
        return "", text
    head, _, rest = text.partition("---\n")
    block, _, remainder = rest.partition("---\n")
    return head + "---\n" + block + "---\n\n", remainder.lstrip("\n")


def _trailing_separator(text: str) -> str:
    """The blank-line run that ended a block, so replacing its text keeps the
    document's spacing rather than running two paragraphs together."""
    stripped = text.rstrip()
    return text[len(stripped):] or "\n"


def compose_file(narration: Path, record: AuthoredRecord) -> tuple[Path, str]:
    """Compose one scene and return where it goes plus its content."""
    text = narration.read_text(encoding="utf-8")
    composed = compose(text, record)
    return narration.with_name(narration.stem + ".composed.md"), composed


def open_gap_ids(narration_text: str, record: AuthoredRecord | None) -> list[str]:
    """Gaps that are neither written nor cut — what holds up assembly.

    Reported per block so a refusal can say *which*, and so a GM can tell a
    finished triage (everything `mine`) from an untouched scene.
    """
    entries = record.by_id() if record else {}
    open_ids: list[str] = []
    _meta, body = split_frontmatter(narration_text)
    for block in parse_blocks(body):
        if not block.is_gap:
            continue
        e = entries.get(block.id)
        if e is None or e.disposition not in ("authored", "cut"):
            open_ids.append(block.id)
    return open_ids


__all__ = [
    "AuthoredError", "ComposeError", "GENERATED_NOTE",
    "compose", "compose_file", "open_gap_ids",
]
