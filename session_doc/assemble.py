#!/usr/bin/env python3
"""Stage 4 — assemble per-scene narration files into one session document.

Reads `session_doc_scene_NN_<slug>.md` files written by Stage 3
(`session_doc.py --per-scene-output`), sorts them by their YAML
frontmatter `scene` field (numeric), and concatenates them into a single
session document.

If a scene has both a raw `.md` and a `.scrubbed.md` variant (the latter
produced by a scrub pass — e.g. the `/scrub` Claude Code skill), the
scrubbed version is used. Pass `--no-prefer-scrubbed` to fall back to the
raw narration even when a scrubbed variant exists.

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

# The marker registry lives in session_doc/apparatus.py: sd_narrate (Stage 3)
# needs the same regex to keep a trailing audit comment out of the prose
# handoff and out of the unknown-name scan (#396).
from session_doc.apparatus import strip_audit_comments
from session_doc.blocks import has_open_gap


def humanise_slug(slug: str) -> str:
    """'harvesting_the_dragon' → 'Harvesting the Dragon'."""
    return " ".join(w.capitalize() for w in slug.split("_"))


def collect_scene_files(in_dir: Path, pattern: str, prefer_scrubbed: bool,
                       chosen: set[str] | None = None) -> list[Path]:
    """Return one file per scene, preferring `.scrubbed.md` when present.

    The glob pattern matches `foo.md`, `foo.scrubbed.md` and `foo.composed.md`,
    so we dedupe by base stem. With `prefer_scrubbed`, the scrubbed variant wins
    over the raw one; without it, `.scrubbed.md` files are ignored.

    **A scrubbed and a composed variant together is refused** (#455). They come
    from independent passes — scrubbing polishes prose, composing fills the GM's
    gaps — and nothing in the inputs says which is final. Picking by sort order
    would silently drop one, which is the failure `resolve_scene_collisions`
    already exists to prevent one level up. `--use` records the ruling in the
    command, exactly as it does there.

    The two refusals are deliberately the same exception and the same flag
    (Principle XII) and deliberately different sentences: that one is *two
    scenes with one number*, this one is *one scene with two final variants*.
    """
    named = {Path(c).name for c in (chosen or ())}
    by_stem: dict[str, Path] = {}
    variants: dict[str, dict[str, Path]] = {}
    for path in sorted(in_dir.glob(pattern)):
        name = path.name
        for suffix, kind in ((".scrubbed.md", "scrubbed"),
                             (".composed.md", "composed")):
            if name.endswith(suffix):
                base = name[: -len(suffix)]
                variants.setdefault(base, {})[kind] = path
                break
        else:
            if not name.endswith(".md"):
                continue
            base = name[: -len(".md")]
            variants.setdefault(base, {})["raw"] = path

    clashes: list[tuple[str, Path, Path]] = []
    for base, found in sorted(variants.items()):
        scrubbed, composed = found.get("scrubbed"), found.get("composed")
        if scrubbed is not None and composed is not None:
            picked = [p for p in (scrubbed, composed) if p.name in named]
            if len(picked) == 1:
                by_stem[base] = picked[0]
                continue
            clashes.append((base, scrubbed, composed))
            continue
        if composed is not None:
            by_stem[base] = composed
        elif scrubbed is not None and prefer_scrubbed:
            by_stem[base] = scrubbed
        elif "raw" in found:
            by_stem[base] = found["raw"]
        elif scrubbed is not None:
            # --no-prefer-scrubbed with no raw sibling: the scrubbed file is the
            # only thing there, and dropping the scene silently would be worse
            # than honouring a preference that has nothing to prefer.
            by_stem[base] = scrubbed

    if clashes:
        lines = [
            "Refusing to assemble: a scene has two final variants and nothing "
            "says which one is it.",
            "",
            "A scrubbed file and a composed file come from different passes — "
            "scrubbing polishes the prose,",
            "composing fills the GM's gaps — so neither supersedes the other by "
            "name.",
        ]
        for base, scrubbed, composed in clashes:
            lines += ["", f"  {base}:", f"    {scrubbed.name}", f"    {composed.name}"]
        lines += [
            "",
            "Choose the final one per scene and re-run, e.g.:",
            f"    --use {clashes[0][2].name}",
            "",
            "Deleting or moving the other file works too; --use records the "
            "decision in the command.",
        ]
        raise SceneCollision("\n".join(lines))
    return [by_stem[k] for k in sorted(by_stem)]


class SceneCollision(Exception):
    """Two files claim one scene and nothing in the inputs says which is final."""


def resolve_scene_collisions(scenes, chosen: set[str]):
    """One file per `scene:`, or refuse.

    `collect_scene_files` dedupes on the filename stem, which correctly
    collapses the `foo.md` / `foo.scrubbed.md` pair it was written for. But
    scene identity is the `scene:` frontmatter, not the slug — so two renders of
    one scene saved under different titles are two stems, both survive
    collection, and both land in the assembled document under the same number
    (#429). `Assembled 7 scene(s)` reads like success; the exit status is 0.

    That is how a discarded draft ships as canon. Renaming a regenerated scene —
    the natural thing to do when trying a second title, or keeping a version to
    compare — is enough to reintroduce the rejected one, and the chapter then
    tells the same scene twice, two different ways.

    Refusal rather than a warning, and rather than picking one: which revision
    is final is knowledge only the operator has, and this repo's convention is
    that a precision decision gets a human checkpoint rather than a silent
    default — `sd_plan` refuses an empty narrator pool instead of falling back
    to the roster, for the same reason.

    `chosen` is `--use`, which makes that ruling explicit and recorded in the
    command rather than implied by which filename sorted first.
    """
    by_scene: dict[int, list] = {}
    for entry in scenes:
        by_scene.setdefault(entry[0], []).append(entry)

    named = {Path(c).name for c in chosen}
    unknown = named - {e[3].name for e in scenes}
    if unknown:
        # A stale --use must fail loudly rather than silently selecting nothing,
        # for the reason transcript_corrections checks `was` against the tape.
        raise SceneCollision(
            "--use names files that are not in this directory: "
            + ", ".join(sorted(unknown))
        )

    resolved, unresolved = [], []
    for scene_num in sorted(by_scene):
        entries = by_scene[scene_num]
        if len(entries) == 1:
            resolved.append(entries[0])
            continue
        picked = [e for e in entries if e[3].name in named]
        if len(picked) == 1:
            resolved.append(picked[0])
        else:
            unresolved.append((scene_num, entries, len(picked)))

    if unresolved:
        lines = [
            "Refusing to assemble: more than one file claims the same scene.",
            "",
            "Scene identity is the `scene:` frontmatter, not the filename, so "
            "these are the same scene told twice —",
            "assembling them both would put a discarded draft in the chapter "
            "beside the one that replaced it.",
        ]
        for scene_num, entries, n_picked in unresolved:
            lines.append("")
            lines.append(f"  scene {scene_num}:")
            for e in entries:
                mark = " <-- --use" if e[3].name in named else ""
                lines.append(f"    {e[3].name}{mark}")
            if n_picked > 1:
                lines.append(f"    (--use names {n_picked} of these; name exactly one)")
        lines += [
            "",
            "Choose the final one per scene and re-run, e.g.:",
            f"    --use {unresolved[0][1][0][3].name}",
            "",
            "Deleting or moving the other file works too; --use records the "
            "decision in the command.",
        ]
        raise SceneCollision("\n".join(lines))
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 4 — combine per-scene narration files into a single session document."
    )
    parser.add_argument("input_dir", metavar="DIR",
                        help="Directory holding session_doc_scene_*.md files "
                             "(written by session_doc.py --per-scene-output).")
    parser.add_argument("--use", metavar="FILENAME", action="append", default=[],
                        help="When two files claim the same scene, assemble this "
                             "one. Repeatable, one per contested scene (#429).")
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
    parser.add_argument("--require-composed", action="store_true",
                        help="Refuse to assemble any scene that still holds a "
                             "gap marker (#455). Off by default. A chapter with "
                             "[GM NARRATION — TO BE WRITTEN: ...] in it feeds "
                             "the release append and the chapter split, so a "
                             "marker that reaches it travels.")
    args = parser.parse_args()

    in_dir = Path(args.input_dir).expanduser()
    if not in_dir.is_dir():
        print(f"Error: input directory not found: {in_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        files = collect_scene_files(in_dir, args.pattern,
                                    prefer_scrubbed=not args.no_prefer_scrubbed,
                                    chosen=set(args.use or []))
    except SceneCollision as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
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
    try:
        scenes = resolve_scene_collisions(scenes, set(args.use or []))
    except SceneCollision as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    scenes.sort(key=lambda x: x[0])

    if args.require_composed:
        # Read the DOCUMENTS, never the records (#455 research D3). A file
        # carrying a marker is unfit for a chapter whatever any record says
        # about it — including when the record is missing, stale, or describes a
        # different draft — so this also holds for a scene composed by hand.
        holding = [(n, p.name) for n, _m, body, p in scenes if has_open_gap(body)]
        if holding:
            print(
                "Error: refusing to assemble — these scenes still have gaps "
                "nobody has written or cut:\n"
                + "\n".join(f"  scene {n:02d}: {name}" for n, name in holding)
                + "\n\nReview them (sd_review export), then compose "
                  "(sd_compose). Drop --require-composed to assemble anyway, "
                  "markers and all.",
                file=sys.stderr,
            )
            sys.exit(1)

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
