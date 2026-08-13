"""Disk I/O and plan parsing for session_doc and the sd_* CLIs.

Loads scene-extraction files written by scene_extract.py, splits them into
gm-assist scene summaries and verbatim moments, parses the narrative plan
file produced by Pass 3, extracts named scenes from a recap's ``## Scenes``
section, and reduces a raw WebVTT transcript to clean speaker dialogue.
"""

import re
import sys
from pathlib import Path

from campaignlib import find_scenes_section


def parse_vtt(text: str) -> str:
    """Strip VTT headers, cue numbers, and timestamps. Return clean speaker dialogue.

    Shared by the two VTT-reading stages, ``enhance_summary`` (Stage 1) and
    ``scene_extract`` (Stage 2). Lived in ``vtt_summary.py`` until that
    pipeline was retired; it is the one piece of it the live flow still
    needs, so it moved here rather than dying with its old home.

    This is the *lossy* reader for the generation stages: it flattens a tape
    to plain speaker dialogue, on purpose, because that is all those stages
    need. For the lossless reader — the one that preserves cue numbers and
    timing and can write a tape back out — use ``campaignlib.vtt``
    (``parse``/``render``). The two stay separate rather than being folded
    into one function: this one flattens deliberately, because the
    generation stages want dialogue, not structure.
    """
    lines = text.splitlines()
    dialogue: list[str] = []
    header_re = re.compile(r"^WEBVTT", re.IGNORECASE)
    timestamp_re = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}")
    cue_re = re.compile(r"^\d+\s*$")
    note_re = re.compile(r"^NOTE\b", re.IGNORECASE)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if header_re.match(stripped):
            continue
        if timestamp_re.match(stripped):
            continue
        if cue_re.match(stripped):
            continue
        if note_re.match(stripped):
            continue
        dialogue.append(stripped)

    return "\n".join(dialogue)


def load_extractions(path: Path) -> list[tuple[str, str]]:
    files = sorted(path.glob("extract_*.md"))
    return [(f.name, f.read_text(encoding="utf-8").strip()) for f in files]


_SCENE_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n\n?(.*)\Z", re.DOTALL)


#: What a moments section claims about the quotes inside it.
CLAIM_VERBATIM = "verbatim"   # `## Verbatim moments` — these are the tape's words
CLAIM_VOICED = "voiced"       # `## Voiced moments`  — tidied for reading; not exact
CLAIM_NONE = ""               # no dual-section layout at all

#: Heading → claim. The heading is the *promise*, and the extraction contract
#: (#250 R5) binds a section to what it promises: R1 asks which of two copies
#: is faithful and R3 objects to an editorial hand inside a span marked
#: verbatim, and neither question means anything in a section that declares it
#: edits. A voice-smoothed layer renames its heading rather than carrying a
#: claim it cannot keep — measured on ch46, smoothing more than doubles the
#: unverified rate, so the two layers cannot promise the same thing.
_MOMENTS_CLAIMS = {
    "verbatim moments": CLAIM_VERBATIM,
    "voiced moments": CLAIM_VOICED,
}

_MOMENTS_HEADING_RE = re.compile(
    r"(?ms)^## (?P<kind>Verbatim moments|Voiced moments)[^\n]*\n(?P<body>.*?)(?=^## |\Z)",
    re.IGNORECASE,
)


def split_scene_sections(body: str) -> tuple[str, str, str]:
    """Split a scene_extract.py file into (gm_summary, moments, claim).

    The conventional shape produced by scene_extract.py:
        # Scene Name
        ## Scene summary (from gm-assist, verbatim)
        <gm-assist body>
        ## Verbatim moments          <- or `## Voiced moments` in a smoothed layer
        <vtt-derived moments>

    Returns ('', body, CLAIM_NONE) when the headings are absent — the caller
    treats the whole file as moments and lets Pass 5 work out the structure.
    That fallback deliberately claims nothing: a file with no heading has made
    no promise, and inventing one for it would let the contract fire on a
    layout it was never shown.
    """
    summary_match = re.search(r"(?ms)^## Scene summary[^\n]*\n(.*?)(?=^## |\Z)", body)
    moments_match = _MOMENTS_HEADING_RE.search(body)
    if summary_match and moments_match:
        claim = _MOMENTS_CLAIMS[moments_match.group("kind").casefold()]
        return summary_match.group(1).strip(), moments_match.group("body").strip(), claim
    return "", body.strip(), CLAIM_NONE


def _split_scene_body(body: str) -> tuple[str, str]:
    """(gm_summary, moments) — the claim-agnostic view, for Pass 5 and friends."""
    summary, moments, _claim = split_scene_sections(body)
    return summary, moments


#: A directory whose name ends in this holds a derived, voice-smoothed layer.
SMOOTHED_DIR_SUFFIX = "_smoothed"


def is_smoothed_dir(path: Path) -> bool:
    return path.name.endswith(SMOOTHED_DIR_SUFFIX)


def smoothed_claim_problems(path: Path) -> list[str]:
    """Files in a ``*_smoothed/`` directory that still claim ``## Verbatim moments``.

    The contract (#250 R5) binds a heading to what it promises: ``## Verbatim
    moments`` says *these are the tape's words*, and a smoothing pass edits
    them, so the smoothed layer renames its heading to ``## Voiced moments``
    rather than carrying a claim it cannot keep. Measured on ch46, smoothing
    more than doubles the unverified rate — the two layers cannot promise the
    same thing.

    Nothing enforced it at either end. Phandalin's
    ``scene_extractions_smoothed/`` carries ``## Verbatim moments`` on every
    file while its frontmatter correctly declares ``source: voice-smoothed``,
    and that directory is what ``paths.scene_extractions_dir`` points at — so
    quote verification measures edited prose against the tape as though it were
    a transcript, on the campaign where smoothing is standard.

    Detection only. Nothing here rewrites an extraction file: the heading is a
    claim about how the file was produced, and correcting it by guessing would
    be the pipeline asserting something it does not know (the producer is
    ``/voice-smooth``, kostadis/mytools#131).

    Returns ``[]`` for a directory that is not a smoothed layer, so callers can
    invoke it unconditionally.
    """
    if not is_smoothed_dir(path) or not path.is_dir():
        return []
    problems: list[str] = []
    for f in sorted(path.glob("*.md")):
        if f.name in {"plan.md", "consistency_report.md"} or f.name.startswith("_"):
            continue
        text = f.read_text(encoding="utf-8")
        m = _SCENE_FRONTMATTER_RE.match(text)
        body = m.group(2) if m else text
        _summary, _moments, claim = split_scene_sections(body)
        if claim == CLAIM_VERBATIM:
            problems.append(f.name)
    return problems


def warn_if_smoothed_claims_verbatim(path: Path) -> None:
    """Print the #304 warning for ``path``, if it earns one."""
    problems = smoothed_claim_problems(path)
    if not problems:
        return
    shown = ", ".join(problems[:5])
    more = f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""
    print(
        f"Warning: {path.name}/ is a voice-smoothed layer, but {len(problems)} "
        f"of its files still head their moments section '## Verbatim moments': "
        f"{shown}{more}.\n"
        f"  Smoothing edits the words, so that heading promises something the "
        f"file cannot keep — quote verification will measure this prose against "
        f"the tape as if it were a transcript and report inflated findings "
        f"(#250 R5, #304).\n"
        f"  -> the producer should write '## Voiced moments'. Nothing is "
        f"rewritten here.",
        file=sys.stderr,
    )


def load_scene_extractions(path: Path) -> list[dict]:
    """Load scene-anchored extraction files written by scene_extract.py.

    Looks for `NN_*.md` files (sorted), parses the YAML frontmatter for the
    canonical `scene:` name, and returns ordered dicts:
        [{"name": str, "path": Path, "summary": str, "moments": str, "body": str}, ...]

    For each scene, prefers the user-edited `NN_<slug>.scaffold.md` over
    the raw Stage-2 `NN_<slug>.md` when both exist — matching the Editor
    behavior in `server/routers/scene_editor.py` so Narrate consumes the
    same file the GM was looking at.

    `summary` is the gm-assist scene body (used as Pass 5's structural
    skeleton) and `moments` is the VTT-derived verbatim extraction (used as
    Pass 5's quote source). When a file does not follow the dual-section
    layout, `summary` is empty and `moments` holds the full body.

    Files named `plan.md`, `consistency_report.md`, or starting with `_` are
    skipped (they are sibling artifacts, not scene extractions).
    """
    warn_if_smoothed_claims_verbatim(path)
    SKIP = {"plan.md", "consistency_report.md"}
    by_stem: dict[str, Path] = {}
    for f in path.glob("*.md"):
        if f.name in SKIP or f.name.startswith("_"):
            continue
        if f.name.endswith(".scaffold.md"):
            stem = f.name[: -len(".scaffold.md")]
            is_scaffold = True
        else:
            stem = f.stem
            is_scaffold = False
        if not re.match(r"^\d{2}_", stem):
            continue
        if is_scaffold or stem not in by_stem:
            by_stem[stem] = f
    items: list[dict] = []
    for stem in sorted(by_stem):
        f = by_stem[stem]
        text = f.read_text(encoding="utf-8")
        fallback_name = stem.split("_", 1)[1].replace("_", " ").title() if "_" in stem else stem
        m = _SCENE_FRONTMATTER_RE.match(text)
        if m:
            name = ""
            for line in m.group(1).splitlines():
                if line.strip().lower().startswith("scene:"):
                    name = line.split(":", 1)[1].strip()
                    break
            body = m.group(2).strip()
            if not name:
                name = fallback_name
        else:
            name = fallback_name
            body = text.strip()
        summary, moments = _split_scene_body(body)
        items.append({
            "name": name,
            "path": f,
            "body": body,
            "summary": summary,
            "moments": moments,
        })
    return items


def format_extractions(extractions: list[tuple[str, str]], heading: str) -> str:
    parts = [f"### Chunk {i}\n\n{content}"
             for i, (_, content) in enumerate(extractions, 1)]
    return f"## {heading}\n\n" + "\n\n---\n\n".join(parts)


def parse_plan(plan_text: str, total_chunks: int) -> list[dict]:
    sections = []
    for block in re.split(r"(?m)^## (?:Section|Scene) \d+", plan_text):
        block = block.strip()
        if not block:
            continue
        section: dict = {}
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("narrator:"):
                section["narrator"] = line.split(":", 1)[1].strip()
            elif line.startswith("chunks:"):
                raw = line.split(":", 1)[1].strip()
                m = re.match(r"(\d+)\s*[-–]\s*(\d+)", raw)
                if m:
                    section["chunk_start"] = int(m.group(1))
                    section["chunk_end"]   = int(m.group(2))
                else:
                    single = re.match(r"(\d+)", raw)
                    if single:
                        n = int(single.group(1))
                        section["chunk_start"] = n
                        section["chunk_end"]   = n
            elif line.startswith("scene:"):
                section["scene"] = line.split(":", 1)[1].strip()
            elif line.startswith("focus:"):
                section["focus"] = line.split(":", 1)[1].strip()
        if "narrator" in section and "chunk_start" in section:
            section["chunk_start"] = max(1, min(section["chunk_start"], total_chunks))
            section["chunk_end"]   = max(section["chunk_start"],
                                         min(section["chunk_end"], total_chunks))
            sections.append(section)
    return sections


def extract_scene_text(recap: str, scene_name: str) -> str:
    """Return the text of a single named scene from the recap's ## Scenes section.

    The ``## Scenes`` heading match is ``find_scenes_section``
    (campaignlib/scenes.py) — one of four independent heading rules in this
    codebase before issue #262 unified them; see that function's docstring
    for why. This caller keeps its own ``### `` scene-title matching.

    The first ``## Scenes`` section only — a small, deliberate narrowing. The
    old loop tested ``line.strip() == "## Scenes"`` *before* its
    ``break``-on-next-``##``, and with no "am I already inside one" guard, so
    a second ``## Scenes`` heading was swallowed by the entry test and the
    scan carried straight on into it — while any *other* ``##`` heading still
    stopped it dead. The extra text it could reach was therefore only ever a
    section sitting immediately after this one, with no other H2 between.

    Exactly one file in a 16,896-file corpus has that shape, and it is a
    chapter bible rather than a recap: ``sd_narrate.py:389`` derives
    ``session_id`` from the recap file's parent directory, so the expected
    input is one session's document, which has one ``## Scenes`` section.
    A concatenated multi-chapter recap was never reliably supported anyway —
    a single ``## NPCs`` between two chapters already ended the scan.

    Contrast ``campaignlib.scenes.parse_gmassist_scenes``, which accumulates
    across every section. The two callers really did differ here, in opposite
    directions, and both differences were accidents of statement order rather
    than decisions. Each is kept where keeping it costs nothing.
    """
    found = find_scenes_section(recap)
    if found is None:
        return ""
    body, _ = found
    in_target = False
    collected: list[str] = []
    for line in body.splitlines():
        if line.startswith("### "):
            if in_target:
                break
            if line.strip("# ").strip().lower() == scene_name.lower():
                in_target = True
            continue
        if in_target:
            collected.append(line)
    return "\n".join(collected).strip()
