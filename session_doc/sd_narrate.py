#!/usr/bin/env python3
"""Pass 5 — per-scene narration standalone CLI.

Reads plan.md (sd_plan output) + scene_extractions/ + per-character voice
files + style examples + party.md, and writes one narration file per scene
to ``--per-scene-output DIR``. Optional filters: ``--scene N [M …]`` to
re-narrate a subset, ``--narrator NAME`` to render only one character's
sections.

This is the Phase-4 split of what used to be Passes 4–5 inside session_doc.py.
See docs/design/SessionDocRefactor.md.

``--batch`` (Claude API backend only; see campaignlib.api.client.add_backend_args):
each scene's narration call is still made one at a time, in plan order — this
loop is order-dependent (each scene's ``handoff`` line feeds the next scene's
prompt, and ``prev_voice_sample`` depends on plan position), so scenes are
NEVER grouped into a single multi-item batch. Every call instead goes through
``run_single_batch`` as its own one-item batch: slower than a grouped batch
(no overlap between scenes) but still billed at the 50% batch rate. If a
scene's batch item fails, an error is printed and the run exits non-zero;
narration files already written for earlier scenes are left on disk.
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
    find_registry,
    load_alias_map,
    run_single_batch,
    stream_api,
)
from session_doc.examples import get_char_examples
from session_doc.knowledge_check import find_unknown_names, format_warning
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
from campaignlib.party_config import load_party_config_arg, require_from_config
from session_doc.roster import roster_from_config
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


def _load_genre_file(path: str | None) -> str | None:
    """Read the genre rulebook from disk, or warn loudly and return None.

    The file is the single source of truth (#276 fix 2): it is not mirrored
    into ``session_doc.yaml``, so a missing or empty file means Pass 5 runs
    with **no** genre directive at all. That is a big silent quality change —
    the rulebook is where the per-narrator bookkeeping caps and the banned-tic
    list live — so say so rather than proceeding quietly.
    """
    if not path:
        return None
    p = Path(path).expanduser()
    if not p.is_file():
        print(f"Warning: --narration-genre-file {p} does not exist. Pass 5 will run "
              f"with NO genre directive — no register rules, no banned-tic list, no "
              f"bookkeeping caps.\n"
              f"  -> create the file, or drop the flag if that was intended.",
              file=sys.stderr)
        return None
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        print(f"Warning: --narration-genre-file {p} is empty. Pass 5 will run with NO "
              f"genre directive.", file=sys.stderr)
        return None
    return text


def _load_examples(examples_dir: Path | None,
                   characters: list[str]) -> tuple[str | None, dict[str, str]]:
    """Mirror session_doc.py's split between global and per-character examples.

    A file whose stem matches a character's first name (case-insensitive)
    routes to that character only; everything else is concatenated into
    the global block. Files whose name starts with ``_`` are skipped entirely.
    """
    if examples_dir is None or not examples_dir.is_dir():
        return None, {}
    char_firsts = {c.lower().split()[0] for c in characters}
    global_parts: list[str] = []
    per_char: dict[str, str] = {}
    for f in sorted(examples_dir.glob("*.md")):
        if f.name.startswith("_"):
            # Shared campaign material (e.g. `_genre.md`), not a style example.
            # An unmatched `_`-file would otherwise join the GLOBAL examples
            # block and reach every narrator (mirrors session_doc/io.py).
            continue
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
    parser.add_argument("--party-config", metavar="FILE", default=None,
                        help="party.yaml (conventionally <campaign>/config/party.yaml). "
                             "REQUIRED: the roster comes from each character's D&D Beyond "
                             "sheet frontmatter (issue #265) and there is no party.md "
                             "fallback — a sheet without frontmatter is a hard error. Run "
                             "sheet_frontmatter --apply to add it.")
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
    parser.add_argument("--narration-genre-file", default=None, metavar="PATH",
                        help="File holding the genre/register rulebook injected into "
                             "Pass 5 (conventionally <campaign>/voice/_genre.md). A "
                             "one-line directive or a full document both work; anything "
                             "longer than a short label is injected as its own delimited "
                             "block. Replaces --narration-genre, which took the text "
                             "inline and made session_doc.yaml a second copy of the file "
                             "(#276).")
    parser.add_argument("--reflections", action="store_true",
                        help="Inject campaign_state and world_state context into Pass 5 so "
                             "the narrator can draw on past events as memories.")
    parser.add_argument("--context", nargs="+", action="extend", metavar="FILE",
                        help="Campaign context files for --reflections.")
    parser.add_argument("--dossier-dir", default=None, metavar="DIR",
                        help="Per-NPC dossier files (planning --build-dossiers). "
                             "Aliases are normalised before Pass 5; a 'Known NPCs' roster "
                             "is seeded into the narrate prompt.")
    parser.add_argument("--alias-registry", default=None, metavar="PATH",
                        help="entity_registry.yaml, or a campaign dir holding "
                             "docs/entity_registry.yaml, to source canonical names from. "
                             "Default: auto-discover docs/entity_registry.yaml under CWD.")
    parser.add_argument("--known-lore", nargs="+", metavar="FILE",
                        help="Documents the whole party is assumed to know — normally the "
                             "campaign bible, or docs/chapters/*.md up to the chapter "
                             "BEFORE this session. Enables a post-narration warning for "
                             "names that appear neither there nor in this session's scene "
                             "extractions (#223 A.3). Warning only; nothing is rewritten.")
    parser.add_argument("--no-alias-normalize", "--no-alias-normalise",
                        dest="no_alias_normalize", action="store_true",
                        help="Do not rewrite aliases to canonical names in the source text. "
                             "The 'Known NPCs' roster still reaches the prompt, so canonical "
                             "spellings remain available to the model as knowledge.")
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

    # A voice-smoothed layer next door is easy to produce and easy to forget to
    # point at; nothing downstream reveals which layer was narrated (#223, C).
    smoothed = sx_dir.parent / f"{sx_dir.name}_smoothed"
    if smoothed.is_dir() and smoothed.resolve() != sx_dir.resolve():
        print(f"Warning: {smoothed.name}/ exists alongside {sx_dir.name}/, but "
              f"--scene-extractions points at {sx_dir.name}/ — the voice-smoothed "
              f"extractions will NOT reach narration.\n"
              f"  -> pass --scene-extractions {smoothed} if that was the intent.",
              file=sys.stderr)

    per_scene_output_dir = Path(args.per_scene_output).expanduser()
    per_scene_output_dir.mkdir(parents=True, exist_ok=True)

    party = Path(args.party).read_text(encoding="utf-8") if args.party else None

    # The roster comes from each character's sheet frontmatter (#265). There is
    # no party.md fallback: --party still supplies the party document's
    # narrative content to the prompt, but not the "never contradict these"
    # class block, which must come from the sheets.
    #
    # Only required when a roster was actually asked for. Running with neither
    # flag is a legitimate mode that predates #265 — the class block is simply
    # absent — so deleting the fallback must not turn "no roster wanted" into
    # an error. Passing --party alone IS an error: it used to be a roster
    # source and is not read as one any more, and failing is how you find out.
    if args.party_config or args.party:
        resolved_party_config = load_party_config_arg(args.party_config)
        roster = require_from_config(
            roster_from_config(resolved_party_config) if resolved_party_config else None,
            what="character roster",
            party_config_arg=args.party_config,
        )
    else:
        roster = ""
    narration_genre = _load_genre_file(args.narration_genre_file)
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

    if args.alias_registry:
        given = Path(args.alias_registry).expanduser()
        registry_path = find_registry(given) if given.is_dir() else given
        if registry_path is None or not registry_path.is_file():
            print(f"Error: --alias-registry not found: {args.alias_registry}",
                  file=sys.stderr)
            sys.exit(1)
        print(f"Entity registry: {registry_path} (--alias-registry)", file=sys.stderr)
    else:
        registry_path = find_alias_registry(Path.cwd())

    alias_map = load_alias_map(args.dossier_dir, registry_path=registry_path)
    npc_roster = format_npc_roster(alias_map)

    # Snapshot the session's own source BEFORE alias normalisation. The check
    # below exists to catch names the PIPELINE introduced, so an alias the
    # normaliser just expanded must not get to vouch for itself: normalising
    # first would put "Aldus Hern" in the known set and hide the one finding
    # this is here to make (#223 A.3).
    session_source = "\n".join(
        f"{sx['moments']}\n{sx['summary']}\n{sx['body']}" for sx in scene_extractions
    )
    known_lore_texts: list[str] = []
    for k in (args.known_lore or []):
        kp = Path(k).expanduser()
        if kp.is_file():
            known_lore_texts.append(kp.read_text(encoding="utf-8"))
        else:
            print(f"Warning: --known-lore file not found: {kp}", file=sys.stderr)

    # Alias rewriting is scoped to prose: quoted and italic spans are a verbatim
    # record of what a person said at the table and are never edited here (#223).
    # The canonical names reach the model as knowledge via `npc_roster` instead —
    # the same channel scene_extract settled on in #231.
    if alias_map and not args.no_alias_normalize:
        normalize, _ = build_alias_normalizer(alias_map, preserve_quoted=True)
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

        # The global examples block reaches scene mode too. It used to be
        # dropped here (de12e2b, "keep the prompt lean — the style constraint
        # is already carried by voice notes and the handoff"), back when scene
        # mode capped narration at 3000 tokens. That rationale is stale: the
        # cap is 16000 now, and voice notes carry a *character's* voice, not
        # the campaign's house style. Suppressing it meant a non-character
        # example file was silently inert in the only mode the pipeline
        # actually runs — every plan section carries a `scene:` line.
        # Per-char examples and the voice spec still outrank it downstream
        # (see build_narrate_system's block order).
        narrate_system = build_narrate_system(
            examples_text,
            scene=scene_name or None,
            prose_mode=args.prose_mode,
            has_scene_events=bool(scene_events_str or narrate_context),
            scene_anchored=bool(scene_summary_override),
            narrator=narrator,
            char_examples=char_examples,
            voice_note=voice_note,
            genre=narration_genre,
        )
        narrate_prompt = build_narrate_prompt(
            narrator, focus, char_moments, party, handoff,
            roster,
            npc_roster=npc_roster,
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
        if args.batch:
            # Order-dependent chain (handoff / prev_voice_sample) — never
            # grouped; one sequential one-item batch per scene (FR-006).
            try:
                narration = run_single_batch(
                    client, system=narrate_system, user=narrate_prompt,
                    model=args.model, max_tokens=args.narrate_tokens,
                )
            except RuntimeError as e:
                print(f"Error: batch item failed for scene {label}: {e}",
                      file=sys.stderr)
                sys.exit(1)
        else:
            narration = stream_api(client, narrate_system, narrate_prompt,
                                   args.model, max_tokens=args.narrate_tokens,
                                   verbose=args.verbose, cache_system=True)
        print("─" * 60)
        narration = narration.strip()
        handoff = narration.rsplit("\n", 1)[-1].strip().strip('"').strip("'")

        if args.known_lore:
            warning = format_warning(
                f"scene {i} ({label})",
                find_unknown_names(narration, [*known_lore_texts, session_source]),
            )
            if warning:
                print(warning, file=sys.stderr)

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
