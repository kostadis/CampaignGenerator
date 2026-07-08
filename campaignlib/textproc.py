"""Text cleaning and chunking helpers."""

import re


_BASE64_IMAGE_RE = re.compile(
    r'^\[image\d+\]:\s*<data:image/[^>]+>\s*$',
    re.MULTILINE,
)


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
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        boundary = text.rfind("\n\n", start, end)
        if boundary == -1 or boundary <= start:
            boundary = text.rfind("\n", start, end)
        if boundary == -1 or boundary <= start:
            boundary = end
        chunks.append(text[start:boundary])
        start = boundary
    return [c.strip() for c in chunks if c.strip()]


def chunk_by_chapters(text: str, chapter_pattern: str) -> list[str]:
    """Split text at headings beginning with chapter_pattern."""
    parts = re.split(rf'(?m)(?=^{re.escape(chapter_pattern)})', text)
    return [p.strip() for p in parts if p.strip()]


_H3_RE = re.compile(r'^###\s+(.+)$', re.MULTILINE)
_H2_RE = re.compile(r'^##(?!#)\s+(.+)$', re.MULTILINE)


def annotate_chunks_with_pov(chunks: list[str]) -> list[str]:
    """Prepend carry-forward speaker/date context to chunks that lack a heading.

    Chapter documents use ``### Name`` headings to mark POV sections and
    ``## date`` for date boundaries. When chunk_text splits mid-section those
    headings are absent from the next chunk, so the LLM loses track of who is
    speaking. This function scans each chunk for those headings, maintains
    running state, and prepends a ``[Continuing — ...]`` banner to any chunk
    that does not open with its own ``##``-level heading.
    """
    last_speaker: str | None = None
    last_date: str | None = None
    result = []

    for chunk in chunks:
        needs_banner = not re.match(r'^##', chunk.lstrip())

        if needs_banner and (last_speaker or last_date):
            parts = []
            if last_date:
                parts.append(f"Date: {last_date}")
            if last_speaker:
                parts.append(f"Speaker: {last_speaker}")
            chunk = f"[Continuing — {', '.join(parts)}]\n\n{chunk}"

        # Update running state from headings found in this chunk.
        # Use the LAST heading of each type so a chunk that spans multiple
        # sections leaves state pointing at the final one.
        h2s = _H2_RE.findall(chunk)
        h3s = _H3_RE.findall(chunk)
        if h2s:
            last_date = h2s[-1].strip()
        if h3s:
            last_speaker = h3s[-1].strip()

        result.append(chunk)
    return result


def prepare_chunks(
    text: str,
    chunk_size: int,
    split_chapters: str | None = None,
    split_label: str = "section",
    annotate_pov: bool = False,
) -> tuple[list[str], str]:
    """Chunk text by chapter prefix or character count, print progress, return (chunks, label).

    Strips embedded base64 image data before chunking.

    split_label  — word used in the progress line when splitting by prefix
                   (e.g. "session", "chapter"). Defaults to "section".
    annotate_pov — if True, call annotate_chunks_with_pov() after chunking so
                   each chunk carries carry-forward speaker/date context. Useful
                   when the source document uses ### Speaker headings (e.g.
                   chapter files) and character-count chunking would otherwise
                   orphan those headings from their content.
    """
    text = strip_base64_images(text).lstrip("﻿")
    if split_chapters:
        chunks = chunk_by_chapters(text, split_chapters)
        print(f"  {len(chunks)} {split_label}(s) to process (split on: {split_chapters!r})\n")
        return chunks, split_label
    chunks = chunk_text(text, chunk_size)
    if annotate_pov:
        chunks = annotate_chunks_with_pov(chunks)
        print(f"  {len(chunks)} chunk(s) to process (chunk size: {chunk_size:,} chars, POV annotated)\n")
    else:
        print(f"  {len(chunks)} chunk(s) to process (chunk size: {chunk_size:,} chars)\n")
    return chunks, "chunk"
