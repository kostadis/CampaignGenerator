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
from session_doc.io import load_extractions, load_scene_extractions, parse_plan


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assign one narrator per scene from --characters using the "
                    "scene_extractions/ checklist. Writes plan.md."
    )
    parser.add_argument("--scene-extractions", required=True, metavar="DIR",
                        help="Directory of NN_*.md scene files (scene_extract output).")
    parser.add_argument("--party-config", metavar="FILE", help="Declared party.yaml; omitted --characters uses its roster, explicit subsets must match it.")
    parser.add_argument("--characters", metavar="NAMES",
                        help='Comma-separated narrator roster '
                             '(e.g. "Vukradin, Valphine, Soma, Brewbarry").')
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
    parser.add_argument("--require-proposal", action="store_true",
                        help="Refuse to run unless <campaign-dir>/docs/"
                             "dossier_proposal.md exists and has been approved.")
    args = parser.parse_args()

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

    from session_doc.workflow.context import narrator_selection
    characters = [c.strip() for c in args.characters.split(",") if c.strip()] if args.characters is not None else None
    if args.party_config:
        try:
            _, characters = narrator_selection(Path(args.party_config), Path(args.campaign_dir or Path.cwd()), characters)
        except ValueError as exc:
            parser.error(str(exc))
    elif not characters:
        parser.error("provide --party-config or an explicit --characters roster")
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
    scene_lines = [f"### {sx['name']}" for sx in scene_extractions]
    plan_parts.append(
        f"## Session Scenes (from scene_extractions/ — every scene below must "
        f"appear in your plan, in this exact order)\n\n"
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

    # Warn about narrators outside the roster
    if characters:
        roster_lower = {c.lower() for c in characters}
        intruders = [s["narrator"] for s in sections
                     if s["narrator"].lower() not in roster_lower]
        if intruders:
            parser.error("plan contains undeclared narrator(s): " + ", ".join(intruders))
        missing = [c for c in characters if c not in {s["narrator"] for s in sections}]
        if missing:
            print(f"Warning: these characters have no section: {', '.join(missing)}")

    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(plan_text, encoding="utf-8")
    print(f"\nPlan: {len(sections)} section(s) -> {out_path}")
    for i, s in enumerate(sections, 1):
        scene_label = f"  [{s['scene']}]" if s.get("scene") else ""
        print(f"  {i}. {s['narrator']:15s} {scene_label}  — {s.get('focus', '')}")


if __name__ == "__main__":
    main()
