#!/usr/bin/env python3
"""Pass 5 — per-scene narration standalone CLI.

Reads plan.md (sd_plan output) + scene_extractions/ + per-character voice
files + style examples + party.md, and writes one narration file per scene
to ``--per-scene-output DIR``. Optional filters: ``--scene N [M …]`` to
re-narrate a subset, ``--narrator NAME`` to render only one character's
sections.

This is the Phase-4 split of what used to be Passes 4–5 inside session_doc.py.
See docs/design/SessionDocRefactor.md.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from campaignlib import (
    DEFAULT_MODEL,
    add_backend_args,
    build_alias_normalizer,
    client_from_args,
    format_npc_roster,
    find_alias_registry,
    load_alias_map,
    stream_api,
)
from session_doc.examples import get_char_examples
from session_doc.io import (
    extract_scene_text,
    load_scene_extractions,
    parse_plan,
)
from session_doc.narrate import (
    build_narrate_prompt,
    build_narrate_system,
    estimate_narration_tokens,
)
from session_doc.roster import extract_character_roster
from session_doc.voice import (
    extract_contrast_sample,
    get_voice_note,
    load_voice_files,
)


@dataclass
class _SceneResult:
    label: str
    narration: str
    handoff: str


def _load_examples(examples_dir: Path | None,
                   characters: list[str]) -> tuple[str | None, dict[str, str]]:
    """Mirror session_doc.py's split between global and per-character examples.

    A file whose stem matches a character's first name (case-insensitive)
    routes to that character only; everything else is concatenated into
    the global block.
    """
    if examples_dir is None or not examples_dir.is_dir():
        return None, {}
    char_firsts = {c.lower().split()[0] for c in characters}
    global_parts: list[str] = []
    per_char: dict[str, str] = {}
    for f in sorted(examples_dir.glob("*.md")):
        stem = f.stem.lower()
        key = None
        for first in char_firsts:
            if stem == first or stem.startswith(first + "_") or stem.startswith(first + "-"):
                key = first
                break
        text = f.read_text(encoding="utf-8")
        if key:
            per_char[key] = (per_char.get(key, "") + ("\n\n" if per_char.get(key) else "") + text).strip()
        else:
            global_parts.append(text)
    examples_text = "\n\n---\n\n".join(global_parts) if global_parts else None
    return examples_text, per_char


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render per-scene first-person narration from a plan + scene extractions."
    )
    parser.add_argument("recap", metavar="FILE",
                        help="Session recap (used to extract scene event text when the "
                             "scene file lacks an explicit summary).")
    parser.add_argument("--plan", required=True, metavar="FILE",
                        help="plan.md (sd_plan output).")
    parser.add_argument("--scene-extractions", required=True, metavar="DIR",
                        help="Directory of NN_*.md scene files (scene_extract output).")
    parser.add_argument("--per-scene-output", required=True, metavar="DIR",
                        help="Where to write session_doc_scene_NN_<slug>.md files.")
    parser.add_argument("--party", metavar="FILE",
                        help="party.md — supplies character classes + roster + voice cues.")
    parser.add_argument("--voice-dir", metavar="DIR",
                        help="Directory of {name}_voice.md files.")
    parser.add_argument("--examples", metavar="DIR",
                        help="Directory of style-reference .md files.")
    parser.add_argument("--characters", metavar="NAMES",
                        help='Comma-separated roster for per-char example routing '
                             '(e.g. "Vukradin, Valphine, Soma, Brewbarry").')
    parser.add_argument("--narrator", metavar="NAME",
                        help="Render only this character's sections.")
    parser.add_argument("--scene", nargs="+", type=int, metavar="N",
                        help="Render only the listed scene number(s) (1-based).")
    parser.add_argument("--prose-mode", action="store_true",
                        help="Strip mechanical / GM framing from narration.")
    parser.add_argument("--narration-genre", default=None, metavar="TEXT",
                        help="One-line genre/register directive injected into Pass 5.")
    parser.add_argument("--reflections", action="store_true",
                        help="Inject campaign_state and world_state context into Pass 5 so "
                             "the narrator can draw on past events as memories.")
    parser.add_argument("--context", nargs="+", action="extend", metavar="FILE",
                        help="Campaign context files for --reflections.")
    parser.add_argument("--dossier-dir", default=None, metavar="DIR",
                        help="Per-NPC dossier files (planning --build-dossiers). "
                             "Aliases are normalised before Pass 5; a 'Known NPCs' roster "
                             "is seeded into the narrate prompt.")
    parser.add_argument("--narrate-tokens", type=int, default=16000, metavar="N",
                        help="Per-scene output token cap. Override per-scene with "
                             "'tokens: N' as the first line of the scene file.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build prompts but skip the API call.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    add_backend_args(parser)
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku (~4x cheaper, faster).")
    args = parser.parse_args()

    if args.fast:
        args.model = "claude-haiku-4-5-20251001"

    # ── Inputs ──
    recap_path = Path(args.recap).expanduser()
    recap = recap_path.read_text(encoding="utf-8") if recap_path.exists() else ""
    plan_path = Path(args.plan).expanduser()
    if not plan_path.exists():
        print(f"Error: --plan not found: {plan_path} (run sd_plan first)", file=sys.stderr)
        sys.exit(1)
    plan_text = plan_path.read_text(encoding="utf-8")

    sx_dir = Path(args.scene_extractions).expanduser()
    if not sx_dir.is_dir():
        print(f"Error: --scene-extractions not found: {sx_dir}", file=sys.stderr)
        sys.exit(1)
    scene_extractions = load_scene_extractions(sx_dir)
    if not scene_extractions:
        print(f"Error: no NN_*.md files in {sx_dir}", file=sys.stderr)
        sys.exit(1)

    per_scene_output_dir = Path(args.per_scene_output).expanduser()
    per_scene_output_dir.mkdir(parents=True, exist_ok=True)

    party = Path(args.party).read_text(encoding="utf-8") if args.party else None
    roster = extract_character_roster(party) if party else ""
    characters = [c.strip() for c in (args.characters or "").split(",") if c.strip()]
    voice_files = (
        load_voice_files(Path(args.voice_dir).expanduser())
        if args.voice_dir else {}
    )
    examples_text, per_char_examples = _load_examples(
        Path(args.examples).expanduser() if args.examples else None,
        characters,
    )

    context_parts: list[str] = []
    if args.context:
        for c in args.context:
            cp = Path(c).expanduser()
            if cp.exists():
                context_parts.append(cp.read_text(encoding="utf-8"))

    alias_map = load_alias_map(args.dossier_dir, registry_path=find_alias_registry(Path.cwd()))
    normalize, _ = build_alias_normalizer(alias_map)
    npc_roster = format_npc_roster(alias_map)
    if alias_map:
        recap = normalize(recap)
        for sx in scene_extractions:
            sx["moments"] = normalize(sx["moments"])
            sx["summary"] = normalize(sx["summary"])
            sx["body"]    = normalize(sx["body"])

    sections = parse_plan(plan_text, len(scene_extractions) or 1)
    if not sections:
        print("Error: could not parse plan.md.", file=sys.stderr)
        sys.exit(1)

    # plan-position lookup so single-scene re-runs still get the prev-narrator contrast
    plan_narrator_by_scene = {idx: s["narrator"] for idx, s in enumerate(sections, 1)}

    if args.narrator:
        wanted = args.narrator.strip().lower()
        sections = [s for s in sections if s["narrator"].lower() == wanted]
        if not sections:
            print(f"Error: narrator '{args.narrator}' not in plan.", file=sys.stderr)
            sys.exit(1)
    if args.scene:
        total = len(sections)
        bad = [n for n in args.scene if n < 1 or n > total]
        if bad:
            print(f"Error: scene number(s) out of range: {bad} (plan has {total})",
                  file=sys.stderr)
            sys.exit(1)
        sections = [(n, sections[n - 1]) for n in args.scene]
    else:
        sections = list(enumerate(sections, 1))

    client = client_from_args(args)
    handoff = ""
    written: list[Path] = []

    for i, section in sections:
        narrator   = section["narrator"]
        focus      = section.get("focus", "")
        scene_name = section.get("scene", "")
        label      = f"{narrator} — {scene_name}" if scene_name else narrator

        # Find the matching scene file (case-insensitive name match, fallback to index).
        match: dict | None = None
        sn = (scene_name or "").lower().strip()
        if sn:
            for sx in scene_extractions:
                if sx["name"].lower().strip() == sn:
                    match = sx
                    break
        if match is None and 1 <= i <= len(scene_extractions):
            match = scene_extractions[i - 1]
        if match is None:
            print(f"Error: no scene extraction matches '{scene_name}' (scene {i}).",
                  file=sys.stderr)
            sys.exit(1)
        char_moments = match["moments"] or match["body"]
        scene_summary_override = match["summary"] or None

        # Voice / examples / contrast
        voice_note = get_voice_note(voice_files, narrator) if voice_files else None
        char_examples = (get_char_examples(per_char_examples, narrator)
                         if per_char_examples else None)
        prev_narrator = plan_narrator_by_scene.get(i - 1)
        prev_voice_sample = None
        if prev_narrator and prev_narrator.lower() != narrator.lower():
            prev_text = (get_char_examples(per_char_examples, prev_narrator)
                         if per_char_examples else None)
            if prev_text:
                prev_voice_sample = extract_contrast_sample(prev_text)
            else:
                prev_narrator = None

        # Scene scope text
        scene_events_str = scene_summary_override or ""
        if not scene_events_str and scene_name and recap:
            scene_events_str = extract_scene_text(recap, scene_name)
        narrate_context = (context_parts
                           if args.reflections and context_parts else None)

        narrate_system = build_narrate_system(
            None if scene_name else examples_text,
            scene=scene_name or None,
            prose_mode=args.prose_mode,
            has_scene_events=bool(scene_events_str or narrate_context),
            scene_anchored=bool(scene_summary_override),
            narrator=narrator,
            char_examples=char_examples,
            voice_note=voice_note,
            genre=args.narration_genre,
        )
        narrate_prompt = build_narrate_prompt(
            narrator, focus, char_moments, party, handoff,
            roster or npc_roster,
            scene_text=scene_events_str or None,
            context_docs=narrate_context,
            prev_narrator=prev_narrator,
            prev_voice_sample=prev_voice_sample,
        )

        est = estimate_narration_tokens(char_moments)
        warn = (f"  ⚠ estimated {est} — add 'tokens: {est}' to override"
                if est > args.narrate_tokens else "")
        print(f"\n[sd_narrate scene {i}: {label}]"
              f"  ({len(char_moments):,} chars, est. ~{est}{warn})")

        if args.dry_run:
            print("─" * 60)
            print(narrate_prompt[:400] + ("...(truncated)" if len(narrate_prompt) > 400 else ""))
            print("─" * 60)
            continue

        print("─" * 60)
        narration = stream_api(client, narrate_system, narrate_prompt,
                               args.model, max_tokens=args.narrate_tokens,
                               verbose=args.verbose)
        print("─" * 60)
        narration = narration.strip()
        handoff = narration.rsplit("\n", 1)[-1].strip().strip('"').strip("'")

        slug_scene = re.sub(r"[^a-z0-9]+", "_", (scene_name or narrator).lower()).strip("_")
        session_id = recap_path.parent.name
        per_scene_file = (per_scene_output_dir
                          / f"session_doc_scene_{i:02d}_{slug_scene}.md")
        frontmatter = (
            "---\n"
            f"scene: {i:02d}\n"
            f"slug: {slug_scene}\n"
            f"narrator: {narrator}\n"
            f"scene_name: {scene_name}\n"
            f"session: {session_id}\n"
            "---\n\n"
        )
        per_scene_file.write_text(frontmatter + narration + "\n", encoding="utf-8")
        written.append(per_scene_file)
        print(f"  Wrote {per_scene_file.name}")

    if not args.dry_run:
        print(f"\nWrote {len(written)} per-scene narration file(s) to {per_scene_output_dir}/")
        print("Run assemble to combine them into a single session document.")


if __name__ == "__main__":
    main()
