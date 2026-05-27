"""Disk I/O and plan parsing for session_doc and the sd_* CLIs.

Loads scene-extraction files written by scene_extract.py, splits them into
gm-assist scene summaries and verbatim moments, parses the narrative plan
file produced by Pass 3, and extracts named scenes from a recap's ``##
Scenes`` section.
"""

import re
from pathlib import Path


def load_extractions(path: Path) -> list[tuple[str, str]]:
    files = sorted(path.glob("extract_*.md"))
    return [(f.name, f.read_text(encoding="utf-8").strip()) for f in files]


_SCENE_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n\n?(.*)\Z", re.DOTALL)


def _split_scene_body(body: str) -> tuple[str, str]:
    """Split the body of a scene_extract.py file into (gm_summary, verbatim_moments).

    The conventional shape produced by scene_extract.py:
        # Scene Name
        ## Scene summary (from gm-assist, verbatim)
        <gm-assist body>
        ## Verbatim moments
        <vtt-derived moments>

    Returns ('', body) when the headings are absent — the caller treats the
    whole file as moments and lets Pass 5 work out the structure.
    """
    summary_match = re.search(r"(?ms)^## Scene summary[^\n]*\n(.*?)(?=^## |\Z)", body)
    moments_match = re.search(r"(?ms)^## Verbatim moments[^\n]*\n(.*?)(?=^## |\Z)", body)
    if summary_match and moments_match:
        return summary_match.group(1).strip(), moments_match.group(1).strip()
    return "", body.strip()


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
    """Return the text of a single named scene from the recap's ## Scenes section."""
    lines = recap.splitlines()
    in_scenes = False
    in_target = False
    collected: list[str] = []
    for line in lines:
        if line.strip() == "## Scenes":
            in_scenes = True
            continue
        if in_scenes and line.startswith("## "):
            break
        if in_scenes and line.startswith("### "):
            if in_target:
                break
            if line.strip("# ").strip().lower() == scene_name.lower():
                in_target = True
            continue
        if in_target:
            collected.append(line)
    return "\n".join(collected).strip()
