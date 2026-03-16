#!/usr/bin/env python3
"""D&D Campaign Session Prep — assembles a prompt from source docs and either
streams a response from the Claude API or copies the prompt to clipboard.

Modes:
  single   (default) — one API call using the main system_prompt.md
  pipeline            — three sequential calls: Lore Oracle → Encounter Architect → Voice Keeper

Session flag:
  --session           — accepts a numbered outline; runs the chosen mode once per beat,
                        producing one encounter document per line, saved to a combined log
"""

import argparse
import re
import sys
from pathlib import Path

from campaignlib import (
    assemble_docs,
    copy_to_clipboard,
    find_default_config,
    load_config,
    load_file,
    make_client,
    save_log,
    stream_api,
)


# ── Prompt assembly ───────────────────────────────────────────────────────────

def assemble_user_prompt(config: dict, beat: str, base_dir: Path | None = None) -> str:
    all_labels = [d["label"] for d in config.get("documents", []) if d.get("path")]
    docs = assemble_docs(config, all_labels, base_dir)
    return f"{docs}\n\n---\n\n## Session Beat\n\n{beat.strip()}"


# ── Session outline parsing ───────────────────────────────────────────────────

def parse_session_beats(outline: str) -> list[str]:
    """Split a numbered outline into individual beat strings.

    Supports:  1. Beat   1) Beat   1: Beat
    Multi-line beats (indented continuation lines) are joined.
    """
    numbered = re.compile(r'^\s*\d+[\.\)\:]\s+')
    beats: list[str] = []
    current: list[str] = []

    for line in outline.strip().splitlines():
        if numbered.match(line):
            if current:
                beats.append(" ".join(current).strip())
            current = [numbered.sub("", line).strip()]
        elif current and line.strip():
            current.append(line.strip())

    if current:
        beats.append(" ".join(current).strip())

    return [b for b in beats if b]


def get_session_outline_from_file(path: str) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        print(f"Error: session file not found: {p}", file=sys.stderr)
        sys.exit(1)
    return p.read_text(encoding="utf-8")


def get_session_outline_interactive(arg_text: str | None) -> str:
    if arg_text:
        return arg_text
    print("Enter the session outline (numbered list of beats).")
    print("Press Enter twice when done:\n")
    lines: list[str] = []
    blank_count = 0
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if line == "":
            blank_count += 1
            if blank_count >= 2:
                break
        else:
            blank_count = 0
            lines.append(line)
    outline = "\n".join(lines).strip()
    if not outline:
        print("Error: session outline cannot be empty.", file=sys.stderr)
        sys.exit(1)
    return outline


def get_beat(arg_beat: str | None) -> str:
    if arg_beat:
        p = Path(arg_beat).expanduser()
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
        return arg_beat
    print("Enter the session beat (what happens this session):")
    beat = sys.stdin.readline().strip()
    if not beat:
        print("Error: session beat cannot be empty.", file=sys.stderr)
        sys.exit(1)
    return beat


# ── Pipeline encounter ────────────────────────────────────────────────────────

def run_pipeline_encounter(
    client, agents: dict, user: str, model: str, base_dir: Path | None = None
) -> tuple[str, str, str] | None:
    """Run one beat through the three-agent pipeline.

    Returns (oracle, architect, voice) responses, or None if stopped at FLAGS.
    """
    required = ["lore_oracle", "encounter_architect", "voice_keeper"]
    for key in required:
        if key not in agents:
            print(f"Error: missing agents.{key} in config.", file=sys.stderr)
            sys.exit(1)

    # Stage 1: Lore Oracle
    print("  [1/3 Lore Oracle]")
    print("  " + "─" * 56)
    oracle_response = stream_api(client, load_file(agents["lore_oracle"], base_dir), user, model)
    print("  " + "─" * 56)

    if "FLAGS" in oracle_response:
        print("\n  Lore Oracle raised FLAGS. Continue to Encounter Architect? [y/N]: ", end="", flush=True)
        if sys.stdin.readline().strip().lower() != "y":
            return None

    # Stage 2: Encounter Architect
    print("  [2/3 Encounter Architect]")
    print("  " + "─" * 56)
    architect_response = stream_api(
        client,
        load_file(agents["encounter_architect"], base_dir),
        f"{user}\n\n---\n\n## Lore Oracle Report\n\n{oracle_response}",
        model,
    )
    print("  " + "─" * 56)

    # Stage 3: Voice Keeper
    print("  [3/3 Voice Keeper]")
    print("  " + "─" * 56)
    voice_response = stream_api(
        client,
        load_file(agents["voice_keeper"], base_dir),
        f"{user}\n\n---\n\n## Encounter Document\n\n{architect_response}",
        model,
    )
    print("  " + "─" * 56)

    return oracle_response, architect_response, voice_response


# ── Top-level mode runners ────────────────────────────────────────────────────

def run_single(client, config, system, user, model, clipboard, no_log, output=None):
    log_dir = config.get("log_dir", "logs/")

    if clipboard:
        full_prompt = f"{system.strip()}\n\n---\n\n{user}"
        copy_to_clipboard(full_prompt)
        if not no_log:
            print(f"Prompt log saved to: {save_log(log_dir, [('Assembled Prompt', full_prompt)])}")
        return

    print(f"\n[Mode: single | Model: {model}]\n")
    print("=" * 60)
    response = stream_api(client, system, user, model)
    print("=" * 60)

    if output:
        Path(output).expanduser().write_text(response.strip() + "\n", encoding="utf-8")
        print(f"\nOutput saved to: {output}")

    if not no_log:
        print(f"\nLog saved to: {save_log(log_dir, [('System Prompt', system), ('User Prompt', user), ('Response', response)])}")


def run_pipeline(client, config, user, model, clipboard, no_log, base_dir=None, output=None):
    log_dir = config.get("log_dir", "logs/")
    agents = config.get("agents", {})

    print(f"\n[Mode: pipeline | Model: {model}]\n")
    print("=" * 60)
    result = run_pipeline_encounter(client, agents, user, model, base_dir)
    print("=" * 60)

    if result is None:
        print("Pipeline stopped at FLAGS.")
        return

    oracle_response, architect_response, voice_response = result

    if output:
        Path(output).expanduser().write_text(voice_response.strip() + "\n", encoding="utf-8")
        print(f"\nOutput saved to: {output}")

    if clipboard:
        copy_to_clipboard(voice_response)

    if not no_log:
        print(f"\nLog saved to: {save_log(log_dir, [('User Prompt', user), ('Lore Oracle', oracle_response), ('Encounter Architect', architect_response), ('Voice Keeper (Final)', voice_response)])}")


def run_session(client, config, outline: str, mode: str, model: str, clipboard: bool, no_log: bool, base_dir=None, output=None):
    """Run all beats in the session outline, one encounter document per beat."""
    log_dir = config.get("log_dir", "logs/")
    agents = config.get("agents", {})
    system = load_file(config["system_prompt"], base_dir) if mode == "single" else None

    beats = parse_session_beats(outline)
    if not beats:
        print("Error: could not parse any beats from the session outline.", file=sys.stderr)
        sys.exit(1)

    call_count = len(beats) * (3 if mode == "pipeline" else 1)
    print(f"\n[Mode: session/{mode} | {len(beats)} beats | {call_count} API calls | Model: {model}]")
    print("Beats detected:")
    for i, b in enumerate(beats, 1):
        print(f"  {i}. {b[:80]}{'…' if len(b) > 80 else ''}")
    print()

    log_sections: list[tuple[str, str]] = [("Session Outline", outline)]
    all_final_outputs: list[str] = []

    for i, beat in enumerate(beats, 1):
        print(f"\n{'=' * 60}")
        print(f"  Encounter {i}/{len(beats)}: {beat}")
        print(f"{'=' * 60}\n")

        user = assemble_user_prompt(config, beat, base_dir)

        if mode == "single":
            response = stream_api(client, system, user, model)
            log_sections.append((f"Encounter {i} — {beat[:60]}", response))
            all_final_outputs.append(response)
        else:
            result = run_pipeline_encounter(client, agents, user, model, base_dir)
            if result is None:
                print(f"\n  Encounter {i} stopped at FLAGS. Skipping to next beat.")
                log_sections.append((f"Encounter {i} — {beat[:60]} [STOPPED AT FLAGS]", "Stopped at Lore Oracle FLAGS."))
                continue
            oracle, architect, voice = result
            log_sections += [
                (f"Encounter {i} — Lore Oracle", oracle),
                (f"Encounter {i} — Architect", architect),
                (f"Encounter {i} — Voice Keeper (Final)", voice),
            ]
            all_final_outputs.append(voice)

    if output and all_final_outputs:
        combined = "\n\n---\n\n".join(all_final_outputs)
        Path(output).expanduser().write_text(combined.strip() + "\n", encoding="utf-8")
        print(f"\nOutput saved to: {output}")

    if clipboard and all_final_outputs:
        copy_to_clipboard("\n\n---\n\n".join(all_final_outputs))

    if not no_log:
        print(f"\nFull session log saved to: {save_log(log_dir, log_sections, stem='session_arc')}")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="D&D session prep: assembles context docs + beat(s), "
        "then calls Claude or copies to clipboard."
    )

    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--beat", "-b", metavar="TEXT_OR_FILE",
                             help="Single session beat (inline text or path to a .md file)")
    input_group.add_argument("--session", "-s", metavar="FILE",
                             help="Path to a file containing a numbered session outline")
    input_group.add_argument(
        "--session-text",
        nargs="?",
        const="",
        metavar="OUTLINE",
        help="Numbered session outline as inline text "
             "(e.g. '1. Travel 2. Climb 3. Boss'). Omit the value to enter interactively.",
    )
    parser.add_argument("--mode", "-m", choices=["single", "pipeline"], default="single",
                        help="single (default) or pipeline")
    parser.add_argument("--clipboard", "-c", action="store_true",
                        help="Copy final output to clipboard")
    parser.add_argument("--config", default=find_default_config(__file__),
                        help="Path to config YAML")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Save final output to file (Voice Keeper responses for pipeline, "
                             "encounter doc for single)")
    parser.add_argument("--no-log", action="store_true", help="Skip saving a log file")
    args = parser.parse_args()

    config, base_dir = load_config(args.config)

    if args.session is not None:
        outline = get_session_outline_from_file(args.session)
        run_session(make_client(), config, outline, args.mode, args.model, args.clipboard, args.no_log, base_dir, args.output)
        return

    if args.session_text is not None:
        outline = get_session_outline_interactive(args.session_text if args.session_text else None)
        run_session(make_client(), config, outline, args.mode, args.model, args.clipboard, args.no_log, base_dir, args.output)
        return

    beat = get_beat(args.beat)
    user = assemble_user_prompt(config, beat, base_dir)

    if args.mode == "single" and args.clipboard:
        system = load_file(config["system_prompt"], base_dir)
        run_single(None, config, system, user, args.model, clipboard=True, no_log=args.no_log, output=args.output)
        return

    client = make_client()
    if args.mode == "single":
        run_single(client, config, load_file(config["system_prompt"], base_dir), user, args.model, clipboard=False, no_log=args.no_log, output=args.output)
    else:
        run_pipeline(client, config, user, args.model, clipboard=args.clipboard, no_log=args.no_log, base_dir=base_dir, output=args.output)


if __name__ == "__main__":
    main()
