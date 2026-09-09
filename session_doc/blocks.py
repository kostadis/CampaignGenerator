"""A narration read as an ordered list of blocks — issue #455.

`sd_narrate --gap-marking` writes `[GM NARRATION — TO BE WRITTEN: …]` where the
source attributes description to the GM, instead of letting a character absorb
it (#454). This module is what reads them back: a narration becomes prose and
gap blocks in reading order, and rejoining them reproduces the narration.

**Round-tripping is the contract, not a nicety.** ``join_blocks(parse_blocks(t))
== t`` for any input. Composing writes a document from these blocks, so a parser
that drops a blank line produces a `.composed.md` differing from its narration
*everywhere* — and the diff reads as the compose step misbehaving rather than as
a parse bug. It is asserted against the four real scenes in
``experiments/20260907-phandalin-gm-gaps-confirm/``, not against a fixture.

**A prose block is a run, not a paragraph.** Every paragraph between two gaps is
one block. That is the granularity the review page the GM actually used already
had, it keeps the count in the low tens — 9 to 25 per scene on the corpus, which
is what makes a phone workable — and block ids are an **interface**: they appear
in the reviewer's export and in `.authored.yaml`, so re-granulating later
invalidates every record written before the change.

**No model is called here, or anywhere in this layer.** Guarded by
``tests/test_block_model_no_llm.py`` rather than by this paragraph. Asked to
resolve its own eleven markers, the model discarded nothing and handed both of
the GM's Order-of-the-Gauntlet lines to a player character, on the one passage
the markers had protected (``experiments/20260907-phandalin-gm-gaps-selffill``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The one definition. Two consumers read it — this parser and `assemble`'s gate
#: — and `tests/test_gap_marker_pairing.py` ties it to the prompt fragment that
#: emits it. `26ec5b0` deleted a prompt and left its stripper, its tests and
#: three out-of-repo skills standing with nothing failing, because nothing tied
#: a marker to a producer; with two consumers here the exposure is worse, and
#: the symptom would be scenes that quietly stop having gaps.
GAP_MARKER = "[GM NARRATION — TO BE WRITTEN:"

#: How much of a block's opening text is kept as its anchor. Written in v1 and
#: matched by nothing: staleness is caught by a digest over the whole draft, and
#: an anchor that lands an authored block on the wrong prose is the same
#: attribution error this feature exists to prevent, committed by us instead of
#: by a model. Stored anyway, so a record authored today survives into #456's
#: matcher without a migration.
ANCHOR_CHARS = 80

#: A paragraph break. Captured rather than split away, so the exact run of blank
#: lines between two paragraphs survives the round trip — narrations are written
#: by a model and their spacing is not guaranteed to be uniform.
_PARA_SPLIT = re.compile(r"(\n[ \t]*\n)")


@dataclass(frozen=True)
class Block:
    """One span of a narration.

    ``id`` is ``{kind}-{ordinal}``, 1-based within kind, so a gap is ``gap-3``
    whether or not prose blocks surround it. It is stable for a given narration
    and it is the key an authored record refers to.
    """

    id: str
    kind: str            # "prose" | "gap"
    anchor: str
    text: str

    @property
    def is_gap(self) -> bool:
        return self.kind == "gap"


def _is_gap_paragraph(paragraph: str) -> bool:
    """Is this paragraph *solely* a gap marker?

    Solely, deliberately. A paragraph that mentions the marker while also
    carrying prose is prose — the model wrote around it — and treating it as a
    gap would delete that prose at compose time. The marker is emitted on its
    own line by contract (#454's `gm_attribution_gap.md` says so), so requiring
    it to stand alone costs nothing and refuses to guess.
    """
    stripped = paragraph.strip()
    return stripped.startswith(GAP_MARKER) and stripped.endswith("]")


def parse_blocks(text: str) -> list[Block]:
    """A narration -> its blocks, in reading order.

    Leading and trailing whitespace of the document, and the exact separators
    between paragraphs, are preserved inside the blocks so that
    :func:`join_blocks` reproduces the input byte for byte.
    """
    if not text:
        return []

    parts = _PARA_SPLIT.split(text)
    # `parts` alternates paragraph, separator, paragraph, … Rebuild each
    # paragraph with the separator that FOLLOWED it, so concatenating the
    # blocks in order is exactly the original string.
    chunks: list[str] = []
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        if para or sep:
            chunks.append(para + sep)

    blocks: list[Block] = []
    run: list[str] = []
    counts = {"prose": 0, "gap": 0}

    def flush_prose() -> None:
        if not run:
            return
        joined = "".join(run)
        run.clear()
        if not joined.strip():
            # Whitespace between two gaps. It belongs to the document but is
            # not a block a human would rule on; carry it on the gap that
            # follows so nothing is lost and no empty block is invented.
            pending.append(joined)
            return
        counts["prose"] += 1
        blocks.append(Block(
            id=f"prose-{counts['prose']}", kind="prose",
            anchor=_anchor(joined), text=joined,
        ))

    pending: list[str] = []
    for chunk in chunks:
        if _is_gap_paragraph(chunk):
            flush_prose()
            counts["gap"] += 1
            text_with_lead = "".join(pending) + chunk
            pending.clear()
            blocks.append(Block(
                id=f"gap-{counts['gap']}", kind="gap",
                anchor=_anchor(chunk), text=text_with_lead,
            ))
        else:
            if pending:
                run.append("".join(pending))
                pending.clear()
            run.append(chunk)
    flush_prose()
    if pending:
        # Trailing whitespace after the last gap. Append it to that gap rather
        # than emitting a blank prose block.
        tail = "".join(pending)
        if blocks:
            last = blocks[-1]
            blocks[-1] = Block(last.id, last.kind, last.anchor, last.text + tail)
        else:
            counts["prose"] += 1
            blocks.append(Block("prose-1", "prose", _anchor(tail), tail))
    return blocks


def join_blocks(blocks: list[Block]) -> str:
    """The inverse of :func:`parse_blocks`."""
    return "".join(b.text for b in blocks)


def _anchor(text: str) -> str:
    """The first :data:`ANCHOR_CHARS` characters of a block's own text.

    Whitespace-normalised so that a record stays readable and so two anchors
    are comparable without re-deriving the normalisation at every call site.

    Stripped *after* truncating, not before: cutting at a fixed length lands on
    a space often enough, and an anchor with a trailing blank compares unequal
    to the same anchor written by hand into a record.
    """
    return " ".join(text.split())[:ANCHOR_CHARS].strip()


def gap_text(block: Block) -> str:
    """The sentence inside a gap marker, without the marker or its brackets."""
    stripped = block.text.strip()
    if not (stripped.startswith(GAP_MARKER) and stripped.endswith("]")):
        return stripped
    return stripped[len(GAP_MARKER):-1].strip()


def has_open_gap(text: str) -> bool:
    """Does this document still contain a gap marker?

    What `assemble`'s gate asks. Deliberately a property of the **document**
    rather than of any record: a document carrying a marker is unfit for a
    chapter whatever a record says about it — including when the record is
    missing, stale, or describes a different draft — and the gate then holds for
    a scene composed by hand, by #456, or by anything else.
    """
    return GAP_MARKER in text
