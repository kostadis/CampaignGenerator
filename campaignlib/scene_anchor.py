"""Locate a summary's scenes inside the chapter prose they were derived from.

The problem this solves. ``event_spine`` keys rows on ``(chapter, scene, seq)``
where ``scene`` is the ``scene_index`` stamped at extraction time from
``chunk_by_scenes`` — a header-driven split. Early-campaign chapters carry no
scene headings: they are organised by in-world date (``## 8/1 of Taraksh 1495``)
with POV names beneath (``### Soma``), or have no ``##`` at all. So ``scene``
degenerates to "which day", or to nothing.

A derived ``session-summary.md`` *does* have a scene list, but its prose is a
compression of the chapter — on the Phandalin corpus the ``## Scenes`` body is
26% of the chapter's word count. Extracting from it to gain a scene key would
trade three quarters of the source text for that key.

This module takes the third option: use the summary's scenes **only as a
boundary map**, and extract from the full prose. Scene titles and their
positions are kept; the summary's own prose is discarded.

Deterministic — no model call. Anchoring a scene is nonetheless a *scope*
decision (a misplaced boundary misattributes events between adjacent scenes),
so the proposed map is written for human approval before anything is injected;
see ``pipelines/ensemble/scene_map.py``.
"""

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["Anchor", "anchor_scenes", "snap_to_paragraph",
           "inject_scene_headings", "demote_h2"]

# Words too common to identify a position. Deliberately short: the anchor keys
# on tokens that are RARE IN THIS CHAPTER (<= _MAX_DF occurrences), so ordinary
# vocabulary filters itself out and this list only trims the stubborn cases.
_STOP = frozenset("""
that this with from they were have been their there which when what them then than
would could should about into over after before again more most some such only other
""".split())

_MIN_TOKEN = 4      # shorter tokens carry too little signal
_MAX_DF = 4         # a token appearing more than this often is not distinctive
_MIN_HITS = 3       # fewer distinct rare hits than this: refuse to anchor
_WINDOW = 400       # word-distance defining "these hits cluster together"


@dataclass
class Anchor:
    """Where one scene begins in the chapter prose."""
    title: str
    offset: int          # character offset, snapped to a paragraph boundary
    raw_offset: int      # pre-snap position of the first clustered rare token
    hits: int            # clustered rare-token hits backing this position
    context: str         # prose at the anchor, for the human reviewing the map


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'),
                 ("”", '"'), ("—", " "), ("–", " ")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9 ]", " ", s.lower())


def _tokens(s: str) -> list[str]:
    return [w for w in _norm(s).split() if len(w) >= _MIN_TOKEN]


def snap_to_paragraph(text: str, offset: int) -> int:
    """Move an offset back to the start of its paragraph.

    A raw anchor lands on a word, which can be mid-sentence; splitting there
    would strand half a sentence in the previous scene. Returns 0 when no
    earlier blank line exists.
    """
    if offset <= 0:
        return 0
    br = text.rfind("\n\n", 0, offset)
    return 0 if br < 0 else br + 2


def anchor_scenes(chapter_text: str, scene_texts: list[str],
                  titles: list[str] | None = None) -> list[Anchor | None]:
    """Place each scene in ``chapter_text``, in order.

    Alignment is monotonic: scene N is searched only at or after scene N-1's
    position, which is what makes a single mismatched scene degrade locally
    instead of scrambling the rest. A scene that cannot be placed returns
    ``None``; the caller folds it into its predecessor rather than guessing.

    Scoring: tokens that occur at most ``_MAX_DF`` times in the chapter are
    treated as identifying. The scene's position is the start of the densest
    cluster of its own rare tokens within a ``_WINDOW``-word span. Frequency
    is measured per chapter, so no global vocabulary is needed.
    """
    titles = titles or [""] * len(scene_texts)
    words = _tokens(chapter_text)
    if not words:
        return [None] * len(scene_texts)

    # word index -> character offset in the original text
    low, offsets, cursor = _norm(chapter_text), [], 0
    for w in words:
        i = low.find(w, cursor)
        offsets.append(i)
        cursor = i + len(w)

    positions: dict[str, list[int]] = {}
    for i, w in enumerate(words):
        positions.setdefault(w, []).append(i)

    out: list[Anchor | None] = []
    floor = 0
    for title, scene in zip(titles, scene_texts):
        rare = [w for w in set(_tokens(scene))
                if w not in _STOP and 0 < len(positions.get(w, ())) <= _MAX_DF]
        hits = sorted(i for w in rare for i in positions[w] if i >= floor)
        if len(hits) < _MIN_HITS:
            out.append(None)
            continue
        best_count, best_at = -1, None
        for k, start in enumerate(hits):
            j = k
            while j + 1 < len(hits) and hits[j + 1] - start <= _WINDOW:
                j += 1
            if j - k > best_count:
                best_count, best_at = j - k, start
        if best_at is None or best_count + 1 < _MIN_HITS:
            out.append(None)
            continue
        raw = offsets[best_at]
        snapped = snap_to_paragraph(chapter_text, raw)
        out.append(Anchor(
            title=title, offset=snapped, raw_offset=raw, hits=best_count + 1,
            context=re.sub(r"\s+", " ", chapter_text[snapped:snapped + 180]).strip(),
        ))
        floor = max(floor, best_at)
    return out


_H2_LINE = re.compile(r"(?m)^##(?!#)[ \t]+")


def demote_h2(text: str) -> str:
    """Turn existing ``## x`` headings into ``### x``.

    Required before injecting scene headings. ``chunk_by_scenes`` splits on
    ``##`` and consults ``###`` only when no ``##`` exists, so leaving the
    chapter's in-world-date H2s in place would mix two conventions and produce
    a chunk per date *and* per scene. Demoted headings stay visible in the
    prose — the information is kept, just no longer structural.
    """
    return _H2_LINE.sub("### ", text)


def inject_scene_headings(chapter_text: str,
                          anchors: list[Anchor | None]) -> str:
    """Return a copy of the chapter with ``## <title>`` at each anchor.

    Existing H2s are demoted first, so the injected headings are the only
    structural boundaries. Insertion runs back-to-front so earlier offsets stay
    valid. ``None`` anchors are skipped: that scene merges into its predecessor.

    Content before the first heading is not orphaned — ``chunk_by_scenes``
    folds it into the first scene.
    """
    placed = [a for a in anchors if a is not None]
    # Demotion only rewrites '## ' to '### ' at line starts, adding one
    # character per H2 line; offsets computed on the original would drift, so
    # inject first and demote after (demotion never touches injected lines
    # because they are re-inserted below, after the sub).
    out = chapter_text
    for a in sorted(placed, key=lambda x: x.offset, reverse=True):
        out = out[:a.offset] + f"@@SCENE@@{a.title}\n\n" + out[a.offset:]
    out = demote_h2(out)
    return out.replace("@@SCENE@@", "## ")
