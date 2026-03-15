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
from datetime import datetime
from pathlib import Path

# ── File helpers ──────────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    try:
        import yaml
    except ImportError:
        print("Error: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_file(path: str) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return p.read_text(encoding="utf-8")


# ── Prompt assembly ───────────────────────────────────────────────────────────

def assemble_user_prompt(config: dict, beat: str) -> str:
    parts = []
    for doc in config.get("documents", []):
        label = doc["label"]
        content = load_file(doc["path"])
        parts.append(f"## {label}\n\n{content.strip()}")
    parts.append(f"## Session Beat\n\n{beat.strip()}")
    return "\n\n---\n\n".join(parts)


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


def get_session_outline(arg_session: str | None) -> str:
    if arg_session:
        return arg_session
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
        return arg_beat
    print("Enter the session beat (what happens this session):")
    beat = sys.stdin.readline().strip()
    if not beat:
        print("Error: session beat cannot be empty.", file=sys.stderr)
        sys.exit(1)
    return beat


# ── API ───────────────────────────────────────────────────────────────────────

def _anthropic_client():
    try:
        import anthropic
    except ImportError:
        print("Error: anthropic not installed. Run: pip install anthropic", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic()


def stream_api(client, system: str, user: str, model: str) -> str:
    chunks = []
    with client.messages.stream(
        model=model,
        max_tokens=8096,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            chunks.append(text)
    print()
    return "".join(chunks)


# ── Clipboard ─────────────────────────────────────────────────────────────────

def copy_to_clipboard(text: str) -> None:
    try:
        import pyperclip
        pyperclip.copy(text)
        print(f"Copied to clipboard ({len(text):,} chars).")
    except ImportError:
        print("pyperclip not installed. Run: pip install pyperclip", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Clipboard error: {e}", file=sys.stderr)
        print("On WSL you may need: sudo apt install xclip", file=sys.stderr)
        sys.exit(1)


# ── Logging ───────────────────────────────────────────────────────────────────

def save_log(log_dir: str, sections: list[tuple[str, str]], stem: str = "session") -> Path:
    """Save a log file. sections is a list of (heading, content) tuples."""
    log_path = Path(log_dir).expanduser()
    log_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = log_path / f"{timestamp}_{stem}.md"

    lines = [f"# Session Log — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    for heading, content in sections:
        lines += ["", "---", "", f"## {heading}", "", content.strip()]

    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_file


# ── Single encounter ──────────────────────────────────────────────────────────

def run_single_encounter(client, system: str, user: str, model: str) -> str:
    """Run one API call and return the response text."""
    return stream_api(client, system, user, model)


# ── Pipeline encounter ────────────────────────────────────────────────────────

def run_pipeline_encounter(
    client, agents: dict, user: str, model: str
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
    oracle_system = load_file(agents["lore_oracle"])
    oracle_response = stream_api(client, oracle_system, user, model)
    print("  " + "─" * 56)

    if "FLAGS" in oracle_response:
        print("\n  Lore Oracle raised FLAGS. Continue to Encounter Architect? [y/N]: ", end="", flush=True)
        answer = sys.stdin.readline().strip().lower()
        if answer != "y":
            return None

    # Stage 2: Encounter Architect
    print("  [2/3 Encounter Architect]")
    print("  " + "─" * 56)
    architect_system = load_file(agents["encounter_architect"])
    architect_input = f"{user}\n\n---\n\n## Lore Oracle Report\n\n{oracle_response}"
    architect_response = stream_api(client, architect_system, architect_input, model)
    print("  " + "─" * 56)

    # Stage 3: Voice Keeper
    print("  [3/3 Voice Keeper]")
    print("  " + "─" * 56)
    voice_system = load_file(agents["voice_keeper"])
    voice_input = f"{user}\n\n---\n\n## Encounter Document\n\n{architect_response}"
    voice_response = stream_api(client, voice_system, voice_input, model)
    print("  " + "─" * 56)

    return oracle_response, architect_response, voice_response


# ── Top-level mode runners ────────────────────────────────────────────────────

def run_single(client, config, system, user, model, clipboard, no_log):
    log_dir = config.get("log_dir", "logs/")

    if clipboard:
        full_prompt = f"{system.strip()}\n\n---\n\n{user}"
        copy_to_clipboard(full_prompt)
        if not no_log:
            log_file = save_log(log_dir, [("Assembled Prompt", full_prompt)])
            print(f"Prompt log saved to: {log_file}")
        return

    print(f"\n[Mode: single | Model: {model}]\n")
    print("=" * 60)
    response = run_single_encounter(client, system, user, model)
    print("=" * 60)

    if not no_log:
        log_file = save_log(log_dir, [
            ("System Prompt", system),
            ("User Prompt", user),
            ("Response", response),
        ])
        print(f"\nLog saved to: {log_file}")


def run_pipeline(client, config, user, model, clipboard, no_log):
    log_dir = config.get("log_dir", "logs/")
    agents = config.get("agents", {})

    print(f"\n[Mode: pipeline | Model: {model}]\n")
    print("=" * 60)
    result = run_pipeline_encounter(client, agents, user, model)
    print("=" * 60)

    if result is None:
        print("Pipeline stopped at FLAGS.")
        return

    oracle_response, architect_response, voice_response = result

    if clipboard:
        copy_to_clipboard(voice_response)

    if not no_log:
        log_file = save_log(log_dir, [
            ("User Prompt", user),
            ("Lore Oracle", oracle_response),
            ("Encounter Architect", architect_response),
            ("Voice Keeper (Final)", voice_response),
        ])
        print(f"\nLog saved to: {log_file}")


def run_session(client, config, outline: str, mode: str, model: str, clipboard: bool, no_log: bool):
    """Run all beats in the session outline, one encounter document per beat."""
    log_dir = config.get("log_dir", "logs/")
    agents = config.get("agents", {})
    system = load_file(config["system_prompt"]) if mode == "single" else None

    beats = parse_session_beats(outline)
    if not beats:
        print("Error: could not parse any beats from the session outline.", file=sys.stderr)
        sys.exit(1)

    call_count = len(beats) * (3 if mode == "pipeline" else 1)
    print(f"\n[Mode: session/{mode} | {len(beats)} beats | {call_count} API calls | Model: {model}]")
    print(f"Beats detected:")
    for i, b in enumerate(beats, 1):
        print(f"  {i}. {b[:80]}{'…' if len(b) > 80 else ''}")
    print()

    # Collect all sections for the combined log
    log_sections: list[tuple[str, str]] = [("Session Outline", outline)]
    all_final_outputs: list[str] = []

    for i, beat in enumerate(beats, 1):
        print(f"\n{'=' * 60}")
        print(f"  Encounter {i}/{len(beats)}: {beat}")
        print(f"{'=' * 60}\n")

        user = assemble_user_prompt(config, beat)

        if mode == "single":
            response = run_single_encounter(client, system, user, model)
            log_sections.append((f"Encounter {i} — {beat[:60]}", response))
            all_final_outputs.append(response)

        else:  # pipeline
            result = run_pipeline_encounter(client, agents, user, model)
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

    # Clipboard: copy all final outputs joined together
    if clipboard and all_final_outputs:
        combined = "\n\n---\n\n".join(all_final_outputs)
        copy_to_clipboard(combined)

    if not no_log:
        log_file = save_log(log_dir, log_sections, stem="session_arc")
        print(f"\nFull session log saved to: {log_file}")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="D&D session prep: assembles context docs + beat(s), "
        "then calls Claude or copies to clipboard."
    )

    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--beat", "-b", help="Single session beat")
    input_group.add_argument(
        "--session", "-s",
        nargs="?",
        const="",           # signals interactive mode when flag is present but no value given
        metavar="OUTLINE",
        help="Numbered session outline (e.g. '1. Travel 2. Climb 3. Boss'). "
             "Omit the value to enter interactively.",
    )

    parser.add_argument(
        "--mode", "-m",
        choices=["single", "pipeline"],
        default="single",
        help="single (default): one call with main system prompt | "
             "pipeline: Lore Oracle → Encounter Architect → Voice Keeper",
    )
    parser.add_argument(
        "--clipboard", "-c",
        action="store_true",
        help="Copy final output to clipboard. "
             "single/--beat: copies assembled prompt (no API call). "
             "pipeline/--beat: copies Voice Keeper output. "
             "session: copies all final encounter outputs joined.",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to config YAML (default: config/config.yaml)",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Claude model to use (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Skip saving a log file",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    # ── Session arc mode ──────────────────────────────────────────────────────
    if args.session is not None:
        outline = get_session_outline(args.session if args.session else None)
        client = _anthropic_client()
        run_session(client, config, outline, args.mode, args.model, args.clipboard, args.no_log)
        return

    # ── Single beat mode ──────────────────────────────────────────────────────
    beat = get_beat(args.beat)
    user = assemble_user_prompt(config, beat)

    # Clipboard-only in single mode skips the API
    if args.mode == "single" and args.clipboard:
        system = load_file(config["system_prompt"])
        run_single(None, config, system, user, args.model, clipboard=True, no_log=args.no_log)
        return

    client = _anthropic_client()

    if args.mode == "single":
        system = load_file(config["system_prompt"])
        run_single(client, config, system, user, args.model, clipboard=False, no_log=args.no_log)
    else:
        run_pipeline(client, config, user, args.model, clipboard=args.clipboard, no_log=args.no_log)


if __name__ == "__main__":
    main()
