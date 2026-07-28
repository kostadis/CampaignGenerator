"""Text cleaning and chunking helpers."""

import re

import yaml


_BASE64_IMAGE_RE = re.compile(
    r'^\[image\d+\]:\s*<data:image/[^>]+>\s*$',
    re.MULTILINE,
)

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?\n)---[ \t]*\n?", re.DOTALL)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a leading YAML frontmatter block (delimited by ``---`` lines)
    from its body. Returns ``(frontmatter_dict, body)``.

    ``frontmatter_dict`` is ``{}`` — never an exception — when there is no
    leading ``---`` block, when the block doesn't parse as YAML, or when it
    parses to something other than a mapping. A gate built on this (e.g. "is
    ``approved`` true?") should therefore default CLOSED: a missing or
    malformed marker reads the same as an explicit ``false``, never as
    permission. ``body`` is the full original text in every failure case
    (nothing is silently dropped), and just the post-frontmatter remainder on
    success.

    Shared by ``narrate_chapter.py`` (writes the ``approved:`` gate) and
    ``synthesise_world_state.py`` (reads it before treating a narrative as
    grounding) so the two sides can never drift on what counts as "approved".
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, text[m.end():]


def norm_subject(s: str) -> str:
    """Identity normalizer for entity keys: lowercase, strip all non-alphanumerics.

    This is the AGGRESSIVE identity comparison used to decide whether two
    strings name the same entity (e.g. "Ilvara Mizzrym" and "ilvara-mizzrym!"
    both normalize to "ilvaramizzrym"). Contrast with
    ``campaignlib.npc.normalize_npc_key``, which is a display/lookup text
    rewriter (keeps spaces, only strips a narrow punctuation set) and is NOT
    an identity key — do not use it for entity-identity comparisons.
    """
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def strip_base64_images(text: str) -> str:
    """Remove markdown reference-style base64 image definitions (e.g. [image1]: <data:image/png;base64,...>)."""
    return _BASE64_IMAGE_RE.sub('', text)


# ── Text chunking ─────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int) -> list[str]:
    """Split text into chunks at paragraph boundaries near chunk_size chars."""
    return [c for _off, c in chunk_text_with_offsets(text, chunk_size)]


def chunk_text_with_offsets(text: str, chunk_size: int) -> list[tuple[int, str]]:
    """Like ``chunk_text``, but pairs each chunk with its start offset in `text`.

    Same boundary logic (paragraph, then line, then hard cut at chunk_size) —
    this is the single implementation ``chunk_text`` delegates to, so the two
    can never drift. The offset is the UNSTRIPPED start of the slice (before
    ``.strip()`` trims it for output), which is exactly what a caller doing
    scene-boundary bisection over character offsets needs: it only has to be a
    monotonically increasing cut point, not the position of the first
    non-whitespace character.
    """
    chunks: list[tuple[int, str]] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            piece = text[start:]
            if piece.strip():
                chunks.append((start, piece.strip()))
            break
        boundary = text.rfind("\n\n", start, end)
        if boundary == -1 or boundary <= start:
            boundary = text.rfind("\n", start, end)
        if boundary == -1 or boundary <= start:
            boundary = end
        piece = text[start:boundary]
        if piece.strip():
            chunks.append((start, piece.strip()))
        start = boundary
    return chunks


def chunk_by_chapters(text: str, chapter_pattern: str) -> list[str]:
    """Split text at headings beginning with chapter_pattern."""
    parts = re.split(rf'(?m)(?=^{re.escape(chapter_pattern)})', text)
    return [p.strip() for p in parts if p.strip()]


_H3_RE = re.compile(r'^###\s+(.+)$', re.MULTILINE)
_H2_RE = re.compile(r'^##(?!#)\s+(.+)$', re.MULTILINE)
_H2_SPEAKER_RE = re.compile(r'^##(?!#)\s+(.+?)\s+—\s+(.+)$', re.MULTILINE)


def annotate_chunks_with_pov(chunks: list[str]) -> list[str]:
    """Prepend carry-forward speaker/date/scene context to chunks that lack a heading.

    Chapter documents use two conventions to mark POV sections, both live in
    real campaign data:

    - Legacy: ``### Name`` headings mark the speaker, ``## date`` marks date
      boundaries (two tiers).
    - Current (``assemble.py``): ``## Name — Scene`` marks the speaker AND
      scene in a single ``##``-level heading, with no ``###`` tier at all.

    When chunk_text splits mid-section those headings are absent from the
    next chunk, so the LLM loses track of who is speaking. This function
    scans each chunk for both heading shapes, maintains running state, and
    prepends a ``[Continuing — ...]`` banner to any chunk that does not open
    with its own ``##``-level heading.
    """
    last_speaker: str | None = None
    last_date: str | None = None
    last_scene: str | None = None
    result = []

    for chunk in chunks:
        needs_banner = not re.match(r'^##', chunk.lstrip())

        if needs_banner and (last_speaker or last_date or last_scene):
            parts = []
            if last_date:
                parts.append(f"Date: {last_date}")
            if last_speaker:
                parts.append(f"Speaker: {last_speaker}")
            if last_scene:
                parts.append(f"Scene: {last_scene}")
            chunk = f"[Continuing — {', '.join(parts)}]\n\n{chunk}"

        # Update running state from headings found in this chunk, in
        # document order, so a chunk that spans multiple sections leaves
        # state pointing at the final one. Each bare ##-level line is either
        # a "Name — Scene" speaker heading or a plain date/other heading —
        # never both — so they're classified individually rather than via
        # two independent findall() passes.
        for m in _H2_RE.finditer(chunk):
            line = m.group(1).strip()
            speaker_match = _H2_SPEAKER_RE.match(m.group(0))
            if speaker_match:
                last_speaker = speaker_match.group(1).strip()
                last_scene = speaker_match.group(2).strip()
            else:
                last_date = line

        h3s = _H3_RE.findall(chunk)
        if h3s:
            last_speaker = h3s[-1].strip()
            last_scene = None  # legacy ### speaker headings carry no scene

        result.append(chunk)
    return result


def chunk_by_scenes(
    text: str, chunk_size: int
) -> tuple[list[tuple[int, str]], str] | None:
    """Split text on the best available structural heading boundary, instead
    of by character count. Returns ``(chunks_with_offsets, convention)`` or
    ``None`` when the document has none of the recognized heading conventions
    (the caller should fall back to character-count chunking — see
    ``prepare_chunks(..., structural=True)``).

    Priority order, reusing the same three regexes ``annotate_chunks_with_pov``
    scans for:

    1. Any ``##``-level heading (``_H2_RE``) — whether it is a
       ``## Name — Scene`` speaker heading (``_H2_SPEAKER_RE``) or a plain
       ``## <date>`` heading, BOTH mark section boundaries at the same
       structural tier, so both are split on identically; the distinction is
       cosmetic (the returned ``convention`` label) rather than behavioural.
       ``convention`` is ``"h2_speaker"`` if any matched heading is in speaker
       form, else ``"h2_date"``.
    2. ``###``-level headings (``_H3_RE``, legacy POV-turn markers) — only
       consulted when there are NO ``##`` headings at all. ``convention`` is
       ``"h3"``.
    3. Neither present -> ``None``. The character-count fallback is
       load-bearing, not vestigial: a real corpus (OOTA) has chapters with no
       headings whatsoever.

    Content before the first heading (an ``# H1`` title, a stray blurb) is
    folded into the first scene rather than dropped or split out as its own
    headerless scene.

    A scene bigger than ``chunk_size`` is further split via
    ``chunk_text_with_offsets`` so no chunk handed downstream is unbounded —
    oversized scenes still get cut, just at their own boundaries first, and
    each sub-chunk's offset is adjusted back into the ORIGINAL document's
    coordinates (not the offset of the scene it was cut from).
    """
    h2_matches = list(_H2_RE.finditer(text))
    if h2_matches:
        starts = [m.start() for m in h2_matches]
        convention = "h2_speaker" if any(
            _H2_SPEAKER_RE.match(m.group(0)) for m in h2_matches
        ) else "h2_date"
    else:
        h3_matches = list(_H3_RE.finditer(text))
        if not h3_matches:
            return None
        starts = [m.start() for m in h3_matches]
        convention = "h3"

    # Fold any pre-heading content into the first scene instead of dropping it
    # or splitting it out as its own headerless scene.
    scene_starts = [0] + starts[1:]

    scenes: list[tuple[int, str]] = []
    for i, s in enumerate(scene_starts):
        end = scene_starts[i + 1] if i + 1 < len(scene_starts) else len(text)
        piece = text[s:end]
        if not piece.strip():
            continue
        if len(piece) > chunk_size:
            for off, sub in chunk_text_with_offsets(piece, chunk_size):
                scenes.append((s + off, sub))
        else:
            scenes.append((s, piece.strip()))
    return scenes, convention


def prepare_chunks(
    text: str,
    chunk_size: int,
    split_chapters: str | None = None,
    split_label: str = "section",
    annotate_pov: bool = False,
    structural: bool = False,
) -> tuple[list[str], str]:
    """Chunk text by chapter prefix, structural heading, or character count.

    Prints progress, returns (chunks, label). Strips embedded base64 image
    data (and a leading BOM) before chunking.

    split_label  — word used in the progress line when splitting by prefix
                   (e.g. "session", "chapter"). Defaults to "section".
    annotate_pov — if True, call annotate_chunks_with_pov() after
                   CHARACTER-COUNT chunking so each chunk carries
                   carry-forward speaker/date/scene context. Useful when the
                   source document uses ### Speaker headings or
                   ## Name — Scene headings (e.g. chapter files) and
                   character-count chunking would otherwise orphan those
                   headings from their content. Has no effect when
                   `structural` chunking succeeds (see below) — a chunk that
                   opens with its own heading needs no repair.
    structural   — OPT-IN (default False, so no existing caller's chunking
                   changes). When True, try `chunk_by_scenes()` first: split
                   on the best available heading boundary instead of by
                   character count. `annotate_pov` is skipped for the
                   resulting scene chunks — each one already opens with its
                   own heading, so the repair `annotate_pov` exists to do
                   (re-injecting context lost when character-count chunking
                   slices mid-scene) is unnecessary. If the document has none
                   of the recognized heading conventions, `chunk_by_scenes`
                   returns None and this falls through to the ordinary
                   character-count path below, WITH `annotate_pov` honoured —
                   the fallback is load-bearing, so it keeps the same repair
                   the non-structural path has always had.
    """
    text = strip_base64_images(text).lstrip("﻿")
    if split_chapters:
        chunks = chunk_by_chapters(text, split_chapters)
        print(f"  {len(chunks)} {split_label}(s) to process (split on: {split_chapters!r})\n")
        return chunks, split_label
    if structural:
        result = chunk_by_scenes(text, chunk_size)
        if result is not None:
            scenes, convention = result
            chunks = [c for _off, c in scenes]
            print(f"  {len(chunks)} scene(s) to process (structural split: "
                  f"{convention}, oversized scenes sub-split at "
                  f"{chunk_size:,} chars)\n")
            return chunks, "scene"
        # No recognized heading convention — fall through to character-count
        # chunking below, annotate_pov included (load-bearing fallback).
    chunks = chunk_text(text, chunk_size)
    if annotate_pov:
        chunks = annotate_chunks_with_pov(chunks)
        print(f"  {len(chunks)} chunk(s) to process (chunk size: {chunk_size:,} chars, POV annotated)\n")
    else:
        print(f"  {len(chunks)} chunk(s) to process (chunk size: {chunk_size:,} chars)\n")
    return chunks, "chunk"
