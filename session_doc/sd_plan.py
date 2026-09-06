#!/usr/bin/env python3
"""Pass 3 — narrative plan standalone CLI.

Reads the scene_extractions/ directory (the authoritative scene list) + party
roster + character names + optional session summary, runs one LLM call to
assign one narrator per scene, writes plan.md (and prints it).

This is the Phase-4 split of what used to be Pass 3 inside session_doc.py.
``--plan-only`` is no longer a flag — invoking ``sd_plan`` *is* the
plan-and-exit operation. See docs/design/SessionDocRefactor.md.
"""

import argparse
import sys
from pathlib import Path

from campaignlib import (
    DEFAULT_MODEL,
    add_backend_args,
    client_from_args,
    load_agent_prompt,
    run_single_batch,
    stream_api,
)
from campaignlib.api.client import resolve_cli_model
from campaignlib.players_config import load_players_config
from session_doc.io import load_extractions, load_scene_extractions, parse_plan
from session_doc.plan_alternates import (
    ALTERNATE_KEYS,
    assemble_alternates,
    parse_treatments,
)
from session_doc.plan_eligibility import (
    compute_eligibility,
    report_eligibility,
    write_eligibility_record,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assign one narrator per scene from --characters using the "
                    "scene_extractions/ checklist. Writes plan.md."
    )
    parser.add_argument("--scene-extractions", required=True, metavar="DIR",
                        help="Directory of NN_*.md scene files (scene_extract output).")
    parser.add_argument("--characters", required=True, metavar="NAMES",
                        help='Comma-separated narrator roster '
                             '(e.g. "Vukradin, Valphine, Soma, Brewbarry").')
    parser.add_argument("--vtt", metavar="FILE",
                        help="The session transcript. Attendance is read from "
                             "its speaker labels: a character whose player has "
                             "no label on this tape cannot narrate (#385). "
                             "Required — there is no fall back to the "
                             "unnarrowed roster.")
    parser.add_argument("--players-config", metavar="FILE",
                        help="players.yaml (conventionally "
                             "<campaign>/config/players.yaml). Maps the tape's "
                             "display names to the characters they play. "
                             "Required, for the same reason as --vtt.")
    parser.add_argument("--party", metavar="FILE",
                        help="party.md — appended to the plan prompt for character voice "
                             "reference when assigning narrators.")
    parser.add_argument("--session-summary", metavar="FILE",
                        help="Synthesised VTT session summary — used as the authoritative "
                             "event log when assigning scenes to narrators.")
    parser.add_argument("--summary-extract-dir", metavar="DIR",
                        help="Optional vtt_extractions/ chunks — extra event context.")
    parser.add_argument("--session-name", default="", metavar="NAME",
                        help='Title injected at the top of the plan prompt '
                             '(e.g. "Session 12 — Icespire Hold").')
    parser.add_argument("--out", metavar="FILE", default="plan.md",
                        help="Where to write plan.md (default: plan.md in cwd).")
    parser.add_argument("--model", default=None)
    add_backend_args(parser)
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku (~4x cheaper, faster).")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--campaign-dir", default=None, metavar="DIR",
                        help="Campaign workspace root (default: $CAMPAIGN_DIR or "
                             "--scene-extractions parent). Used to locate "
                             "docs/dossier_proposal.md.")
    parser.add_argument("--choose", metavar="KEY", choices=ALTERNATE_KEYS,
                        help="Resolve a pending choice: copy plan.<KEY>.md to "
                             "plan.md and exit. Written when a scene has no "
                             "eligible narrator and the planner produced three "
                             "treatments of it. Equivalent to "
                             "`cp plan.b.md plan.md` — the choice is a file.")
    parser.add_argument("--require-proposal", action="store_true",
                        help="Refuse to run unless <campaign-dir>/docs/"
                             "dossier_proposal.md exists and has been approved.")
    args = parser.parse_args()

    # Resolving a pending choice is a file copy, not a planning run: no model,
    # no scene loading, no attendance derivation.
    if args.choose:
        out_path = Path(args.out).expanduser()
        alternate = out_path.with_name(f"{out_path.stem}.{args.choose}{out_path.suffix}")
        if not alternate.is_file():
            print(f"Error: no alternate to choose at {alternate}. "
                  f"Expected one of: "
                  + ", ".join(
                      str(out_path.with_name(f"{out_path.stem}.{k}{out_path.suffix}").name)
                      for k in ALTERNATE_KEYS
                  ),
                  file=sys.stderr)
            sys.exit(1)
        out_path.write_text(alternate.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Chose {alternate.name} -> {out_path}")
        return

    if args.fast:
        args.model = "claude-haiku-4-5-20251001"

    try:
        model_intent = resolve_cli_model(args, legacy_default=DEFAULT_MODEL)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    effective_model = model_intent.effective_model
    args.model = effective_model

    # Proposal gate runs BEFORE anything else so unapproved proposals abort
    # before scene-extraction loading or any Claude calls.
    if args.require_proposal:
        import os as _os

        from pipelines.rlm.proposal_loader import (
            ProposalNotApproved,
            ProposalRequired,
            require_approved_proposal,
        )
        campaign_dir = (
            args.campaign_dir
            or _os.environ.get("CAMPAIGN_DIR")
            or str(Path(args.scene_extractions).expanduser().resolve().parent)
        )
        try:
            require_approved_proposal(campaign_dir)
        except (ProposalRequired, ProposalNotApproved) as exc:
            parser.error(str(exc))

    # Load scene extractions (the authoritative scene checklist).
    sx_dir = Path(args.scene_extractions).expanduser()
    if not sx_dir.is_dir():
        print(f"Error: --scene-extractions not found: {sx_dir}", file=sys.stderr)
        sys.exit(1)
    scene_extractions = load_scene_extractions(sx_dir)
    if not scene_extractions:
        print(f"Error: no NN_*.md files in {sx_dir} "
              "(run scene_extract first)", file=sys.stderr)
        sys.exit(1)

    characters = [c.strip() for c in args.characters.split(",") if c.strip()]

    # ── Eligibility (#385) ──────────────────────────────────────────────────
    # Who may narrate is settled here, deterministically, before the model sees
    # anything. Narrator assignment is an attribution decision (Constitution
    # II); this takes the eligibility half of it out of the prompt, where it
    # was being made from a scene title under an instruction to rotate through
    # the whole cast.
    if not args.vtt:
        print("Error: --vtt is required — attendance cannot be established "
              "without the session tape, and planning without it would hand "
              "the model the whole campaign roster, which is the defect "
              "#385 is about.", file=sys.stderr)
        sys.exit(1)
    if not args.players_config:
        print("Error: --players-config is required — the tape's speaker labels "
              "are player display names, and players.yaml is what maps them to "
              "the characters they play.", file=sys.stderr)
        sys.exit(1)

    vtt_path = Path(args.vtt).expanduser()
    if not vtt_path.is_file():
        print(f"Error: --vtt not found: {vtt_path}", file=sys.stderr)
        sys.exit(1)
    players_path = Path(args.players_config).expanduser()
    if not players_path.is_file():
        print(f"Error: --players-config not found: {players_path}", file=sys.stderr)
        sys.exit(1)

    eligibility = compute_eligibility(
        scenes=scene_extractions,
        roster=characters,
        players=load_players_config(players_path),
        vtt_text=vtt_path.read_text(encoding="utf-8", errors="replace"),
    )
    report_eligibility(eligibility, vtt_path=vtt_path)

    if not eligibility.pool:
        print(
            "Error: no narrator survived the attendance filter — not one "
            f"roster character's player has a speaker label in {vtt_path.name}. "
            "That is almost always the wrong VTT for this session rather than "
            "a session nobody attended. Refusing rather than planning with the "
            "full roster.",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(eligibility.uncoverable) == len(scene_extractions):
        print(
            "Error: no scene in this session has an eligible narrator — no "
            "player character speaks anywhere in the extractions. That is the "
            "wrong scene_extractions directory, or an extraction pass that "
            "produced no speaker labels, rather than a session to plan.",
            file=sys.stderr,
        )
        sys.exit(1)

    record = write_eligibility_record(
        eligibility, out_dir=Path(args.out).expanduser().parent, vtt_path=vtt_path
    )
    print(f"[eligibility] evidence: {record}")

    party = Path(args.party).read_text(encoding="utf-8") if args.party else None
    session_summary = (
        Path(args.session_summary).read_text(encoding="utf-8")
        if args.session_summary else ""
    )
    summary_extractions = (
        load_extractions(Path(args.summary_extract_dir))
        if args.summary_extract_dir else []
    )

    # Build the plan prompt.
    plan_parts: list[str] = []
    if args.session_name:
        plan_parts.append(f"# Session: {args.session_name}")
    if characters:
        plan_parts.append("## Available narrators\n"
                          + "\n".join(f"- {c}" for c in characters))
    if summary_extractions:
        s_parts = [f"### Chunk {i}\n\n{content}"
                   for i, (_, content) in enumerate(summary_extractions, 1)]
        plan_parts.append("## Session Extractions\n"
                          "(action detail, events, environmental context)\n\n"
                          + "\n\n---\n\n".join(s_parts))
    if session_summary:
        plan_parts.append(
            "## Session Summary (authoritative — use to understand the full event arc "
            "and assign scenes to the character with the most interesting perspective)\n\n"
            + session_summary.strip()
        )
    if party:
        plan_parts.append(f"## Party Document\n\n{party.strip()}")
    # Every scene carries the characters who actually speak in it. This used to
    # be `### {name}` and nothing else — the extraction bodies were loaded and
    # discarded, so the model chose a first-person narrator from a title (#385).
    scene_lines: list[str] = []
    for sx in scene_extractions:
        name = sx["name"]
        eligible = sorted(eligibility.candidates.get(name, set()))
        counts = eligibility.line_counts.get(name, {})
        scene_lines.append(f"### {name}")
        if eligible:
            shown = ", ".join(
                f"{c} ({counts.get(c, 0)} labelled turns)" for c in eligible
            )
            scene_lines.append(f"eligible narrators: {shown}")
        else:
            scene_lines.append(
                "eligible narrators: NONE — no player character speaks in this "
                "scene."
            )
    plan_parts.append(
        "## Session Scenes (from scene_extractions/ — every scene below must "
        "appear in your plan, in this exact order)\n\n"
        "The `eligible narrators` line under each scene is derived from that "
        "scene's own speaker labels and is NOT a suggestion: assign one of "
        "those names and no other. Turn counts are context for choosing "
        "between them, never a threshold — one labelled turn is full "
        "eligibility.\n\n"
        + "\n".join(scene_lines)
    )

    client = client_from_args(args)
    system = load_agent_prompt("session_doc/plan")
    user_prompt = "\n\n---\n\n".join(plan_parts)
    print(f"[sd_plan: Pass 3 | model: {args.model} | "
          f"{len(scene_extractions)} scene(s) | {len(characters)} narrator(s)]")
    print("=" * 60)
    if args.batch:
        try:
            plan_text = run_single_batch(client, system=system, user=user_prompt,
                                         model=args.model, max_tokens=8096,
                                         cache_system=False)
        except RuntimeError as e:
            print(f"Error: batch item failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        plan_text = stream_api(client, system, user_prompt,
                               args.model, verbose=args.verbose)
    print("=" * 60)

    sections = parse_plan(plan_text, len(scene_extractions) or 1)
    if not sections:
        print("Error: could not parse plan. Raw output above.", file=sys.stderr)
        sys.exit(1)

    # A narrator the scene never contained is refused, not warned about. The
    # whole point of the filter is that this is not a judgement call.
    violations: list[str] = []
    for i, s in enumerate(sections):
        if i >= len(scene_extractions):
            break
        scene_name = scene_extractions[i]["name"]
        eligible = eligibility.candidates.get(scene_name, set())
        narrator = s.get("narrator", "")
        if eligible and narrator not in eligible:
            violations.append(
                f"  - {scene_name}: assigned {narrator!r}, but only "
                f"{', '.join(sorted(eligible))} speak in that scene"
            )
    if violations:
        print("\nError: the plan assigns narrators who were not in their "
              "scenes:\n" + "\n".join(violations), file=sys.stderr)
        sys.exit(1)

    # Warn about narrators outside the ELIGIBLE set, and about eligible
    # characters with no section.
    #
    # This warning used to be computed against `characters` — the whole
    # campaign roster — which is how it came to demand a scene for a character
    # whose player was not at the table. It was the third mechanism behind
    # #385, and the only "coverage" check in the system: coverage of the
    # roster, never of the scene. Computed against the pool, an absent
    # character having no section is the correct outcome, not a gap.
    if eligibility.pool:
        pool_lower = {c.lower() for c in eligibility.pool}
        intruders = [s["narrator"] for s in sections
                     if s["narrator"].lower() not in pool_lower]
        if intruders:
            print(f"\nWarning: plan contains narrator(s) who were not at this "
                  f"session, or not in --characters: {', '.join(intruders)}")
        assigned = {s["narrator"] for s in sections}
        missing = [c for c in sorted(eligibility.pool) if c not in assigned]
        if missing:
            print(f"Warning: these characters were at the session but have no "
                  f"section: {', '.join(missing)}")

    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if eligibility.uncoverable:
        # A scene nobody can narrate is not the planner's to settle. Write three
        # treatments of it and NO plan.md — the missing file is what stops Pass
        # 5, using the gate that already exists.
        names = list(eligibility.uncoverable)
        indexes = [
            i for i, sx in enumerate(scene_extractions) if sx["name"] in set(names)
        ]
        treatment_prompt = "\n\n---\n\n".join(
            [
                "## The scene(s) with no eligible narrator\n\n"
                + "\n".join(f"- {n}" for n in names),
                "## The plan so far (every other scene is settled)\n\n" + plan_text,
                user_prompt,
            ]
        )
        print(f"\n[sd_plan: treatments | {len(names)} uncoverable scene(s)]")
        print("=" * 60)
        if args.batch:
            treatment_text = run_single_batch(
                client, system=load_agent_prompt("session_doc/plan_treatments"),
                user=treatment_prompt, model=args.model, max_tokens=4096,
                cache_system=False,
            )
        else:
            treatment_text = stream_api(
                client, load_agent_prompt("session_doc/plan_treatments"),
                treatment_prompt, args.model, verbose=args.verbose,
            )
        print("=" * 60)

        treatments = parse_treatments(treatment_text)
        if len(treatments) < len(ALTERNATE_KEYS):
            print(f"Error: expected {len(ALTERNATE_KEYS)} treatments, parsed "
                  f"{len(treatments)}. Raw output above.", file=sys.stderr)
            sys.exit(1)

        alternates = assemble_alternates(
            plan_text, scene_indexes=indexes, treatments=treatments,
            uncoverable_names=names,
        )
        written = []
        for key, text in alternates.items():
            alt = out_path.with_name(f"{out_path.stem}.{key}{out_path.suffix}")
            alt.write_text(text, encoding="utf-8")
            written.append(alt)

        print(f"\nNo eligible narrator for: {', '.join(names)}")
        print("Three plans written; they are identical except that scene:")
        for key, alt in zip(ALTERNATE_KEYS, written):
            print(f"  {key}. {alt.name:20s} — {treatments[ALTERNATE_KEYS.index(key)].label}")
        print(f"\nNo {out_path.name} was written. Choose one before narrating:")
        print(f"  sd_plan --choose <{'|'.join(ALTERNATE_KEYS)}> --out {out_path}")
        return

    out_path.write_text(plan_text, encoding="utf-8")
    print(f"\nPlan: {len(sections)} section(s) -> {out_path}")
    for i, s in enumerate(sections, 1):
        scene_label = f"  [{s['scene']}]" if s.get("scene") else ""
        print(f"  {i}. {s['narrator']:15s} {scene_label}  — {s.get('focus', '')}")


if __name__ == "__main__":
    main()
