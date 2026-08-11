#!/usr/bin/env python3
"""Stage 4 — assemble per-scene narration files into one session document.

Reads `session_doc_scene_NN_<slug>.md` files written by Stage 3
(`session_doc.py --per-scene-output`), sorts them by their YAML
frontmatter `scene` field (numeric), and concatenates them into a single
session document.

If a scene has both a raw `.md` and a `.scrubbed.md` variant (the latter
produced by `scrub_mechanics`), the scrubbed version is used. Pass
`--no-prefer-scrubbed` to fall back to the raw narration even when a
scrubbed variant exists.

No LLM calls. The point is to make narration incremental: the user can
edit one scene file, re-run a single scene through `session_doc.py`,
and re-assemble without touching the others.

Usage:
  assemble narration/ --output session_doc.md \\
      [--title "Chapter 37 — A Gem of a Problem"]
"""

import argparse
import re
import sys
from pathlib import Path

from campaignlib.textproc import split_frontmatter

# Pass 5 appends `<!-- table-speech reclassified: "…" | "…" -->` after the
# narration when it reclassifies a mislabelled quoted span as GM table speech
# (issue #245). The comment is the GM's review queue and stays in the per-scene
# file; it is not part of the assembled document.
_AUDIT_COMMENT_RE = re.compile(
    r"[ \t]*<!--\s*table-speech reclassified:.*?-->[ \t]*\n?",
    re.DOTALL | re.IGNORECASE,
)


def strip_audit_comments(body: str) -> str:
    """Remove Pass 5's table-speech audit comments from a scene body."""
    return _AUDIT_COMMENT_RE.sub("", body)


def humanise_slug(slug: str) -> str:
    """'harvesting_the_dragon' → 'Harvesting the Dragon'."""
    return " ".join(w.capitalize() for w in slug.split("_"))


def collect_scene_files(in_dir: Path, pattern: str, prefer_scrubbed: bool) -> list[Path]:
    """Return one file per scene, preferring `.scrubbed.md` when present.

    The glob pattern matches both `foo.md` and `foo.scrubbed.md`, so we
    dedupe by base stem (filename minus `.scrubbed.md` or `.md`). With
    `prefer_scrubbed`, the scrubbed variant wins when both exist; without
    it, the raw `.md` variant wins and `.scrubbed.md` files are ignored.
    """
    by_stem: dict[str, Path] = {}
    for path in sorted(in_dir.glob(pattern)):
        name = path.name
        if name.endswith(".scrubbed.md"):
            base = name[: -len(".scrubbed.md")]
            if not prefer_scrubbed:
                continue
            by_stem[base] = path
        elif name.endswith(".md"):
            base = name[: -len(".md")]
            by_stem.setdefault(base, path)
        else:
            continue
    return [by_stem[k] for k in sorted(by_stem)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 4 — combine per-scene narration files into a single session document."
    )
    parser.add_argument("input_dir", metavar="DIR",
                        help="Directory holding session_doc_scene_*.md files "
                             "(written by session_doc.py --per-scene-output).")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to write the assembled session document.")
    parser.add_argument("--title", metavar="TEXT", default=None,
                        help="Top-level H1 title. Defaults to the input directory's "
                             "parent dir name (typically the session date).")
    parser.add_argument("--chapter", type=int, metavar="N", default=None,
                        help="Canonical chapter number (issue #213). When given, the "
                             "assembled document opens with YAML frontmatter "
                             "(chapter/session/title) and the H1 becomes "
                             "'# Chapter N <title>'. This is where chapter identity "
                             "is minted — the release append and split carry it.")
    parser.add_argument("--session", metavar="YYYYMMDD", default=None,
                        help="Session date for the frontmatter. Defaults to the "
                             "first YYYYMMDD-shaped directory name on the input "
                             "path (summaries/YYYYMMDD/narration).")
    parser.add_argument("--pattern", default="session_doc_scene_*.md",
                        help="Glob pattern for per-scene files (default: "
                             "session_doc_scene_*.md).")
    parser.add_argument("--no-prefer-scrubbed", action="store_true",
                        help="Use raw .md files even when a .scrubbed.md "
                             "variant exists. Default behaviour prefers "
                             "scrubbed.")
    args = parser.parse_args()

    in_dir = Path(args.input_dir).expanduser()
    if not in_dir.is_dir():
        print(f"Error: input directory not found: {in_dir}", file=sys.stderr)
        sys.exit(1)

    files = collect_scene_files(in_dir, args.pattern,
                                prefer_scrubbed=not args.no_prefer_scrubbed)
    if not files:
        print(f"Error: no files matching '{args.pattern}' in {in_dir}", file=sys.stderr)
        sys.exit(1)

    scenes: list[tuple[int, dict, str, Path]] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        meta, body = split_frontmatter(text)
        # `meta` now comes from real YAML (campaignlib.textproc.split_frontmatter),
        # not the old hand-rolled `k: v` line splitter, so `scene` may arrive as
        # an int (`scene: 04` -> 4) or a str (`scene: 08` -> '08' — PyYAML's
        # octal resolver rejects 08/09 as invalid octal and falls back to str).
        # str(...) normalises both before int() — don't drop it back to a bare
        # `.strip()`, which raises AttributeError on the int case.
        scene_str = str(meta.get("scene", "")).strip()
        try:
            scene_num = int(scene_str)
        except ValueError:
            print(f"  Skipping {path.name}: missing or non-numeric 'scene' frontmatter "
                  f"(got {scene_str!r})", file=sys.stderr)
            continue
        scenes.append((scene_num, meta, strip_audit_comments(body).strip(), path))
    scenes.sort(key=lambda x: x[0])

    if not scenes:
        print(f"Error: no usable scene files in {in_dir} "
              f"(every file was missing 'scene' frontmatter).", file=sys.stderr)
        sys.exit(1)

    title = args.title or in_dir.parent.name or "Session"
    if args.chapter is not None:
        # Minting point for chapter identity (issue #213 Phase 0). The bare
        # title goes in the frontmatter; a pre-prefixed --title like
        # "Chapter 37 — A Gem of a Problem" is stripped so the number is
        # stated exactly once, by --chapter. The separator is then re-emitted
        # as ": " in the H1 — stripping it and rejoining with a bare space
        # produced "# Chapter 37 A Gem of a Problem", which reads as a
        # four-word title rather than a numbered one.
        bare_title = re.sub(r"^Chapter\s+[\d.]+\s*[:\-—]?\s*", "", title).strip()
        session = args.session
        if session is None:
            for part in [in_dir.name, *(p.name for p in in_dir.parents)]:
                if re.fullmatch(r"\d{8}", part):
                    session = part
                    break
        meta_lines = [f"chapter: {args.chapter}"]
        if session:
            meta_lines.append(f"session: '{session}'")
        if bare_title:
            quoted = bare_title.replace("'", "''")
            meta_lines.append(f"title: '{quoted}'")
        frontmatter = "---\n" + "\n".join(meta_lines) + "\n---\n"
        heading = (f"# Chapter {args.chapter}: {bare_title}" if bare_title
                   else f"# Chapter {args.chapter}")
        parts: list[str] = [frontmatter + "\n" + heading + "\n"]
    else:
        parts = [f"# {title}\n"]
    for scene_num, meta, body, path in scenes:
        scene_name = meta.get("scene_name") or humanise_slug(meta.get("slug", "scene"))
        narrator = meta.get("narrator", "")
        header = f"## {narrator} — {scene_name}" if narrator else f"## {scene_name}"
        parts.append("---\n\n" + header + "\n\n" + body)

    full_doc = "\n\n".join(parts) + "\n"

    out_path = Path(args.output).expanduser().resolve()
    if out_path.exists():
        print(f"Error: output file already exists: {out_path}\n"
              f"Delete it or choose a different path.", file=sys.stderr)
        sys.exit(1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_doc, encoding="utf-8")
    scrubbed_count = sum(1 for _, _, _, p in scenes if p.name.endswith(".scrubbed.md"))
    print(f"\nAssembled {len(scenes)} scene(s) → {out_path}"
          f" ({scrubbed_count} scrubbed, {len(scenes) - scrubbed_count} raw)")
    for scene_num, meta, _body, path in scenes:
        print(f"  {scene_num:02d}. {meta.get('scene_name') or meta.get('slug', '?')}"
              f" ({path.name})")


if __name__ == "__main__":
    main()
