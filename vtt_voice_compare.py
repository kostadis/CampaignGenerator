#!/usr/bin/env python3
"""Compare a player's VTT lines against an existing voice file and suggest additions.

Extracts all lines attributed to a named player from a Zoom VTT transcript,
then calls Claude to:
  1. Identify which lines are in-character (vs OOC table talk / rules questions)
  2. Compare against the existing voice file
  3. Suggest new lines to add with context annotations, in the voice file format

Usage:
  python vtt_voice_compare.py session.vtt --player Gabe --voice-file voice/zalthir_voice.md
  python vtt_voice_compare.py session.vtt --player Gabe --voice-file voice/zalthir_voice.md --update
  python vtt_voice_compare.py session.vtt --player Gabe --character Zalthir --voice-file voice/zalthir_voice.md

Options:
  --player NAME       Speaker label as it appears in the VTT (e.g. "Gabe")
  --character NAME    Character name, if different from player (used in prompts)
  --voice-file PATH   Existing voice file to compare against and optionally update
  --update            Append suggested lines to the voice file after analysis
  --model MODEL       Claude model (default: claude-sonnet-4-6)
  --no-log            Skip saving a log file
"""

import argparse
import re
import sys
from pathlib import Path

from campaignlib import (
    find_default_config,
    make_client,
    stream_api,
    save_log,
    DEFAULT_MODEL,
)


ANALYSIS_SYSTEM = """\
You are a D&D voice archivist. Your job is to help build per-character voice files
that capture how a player's character sounds — their rhythms, their humor, their silences,
their tells — so that future narration can stay true to the character.

You will receive:
1. All lines spoken by a specific player in a session transcript
2. The character's existing voice file

Your tasks:
A. Identify which player lines are IN-CHARACTER (the player speaking as or about their character
   in a way that reveals character voice) vs OUT-OF-CHARACTER (rules questions, tech issues,
   scheduling, crosstalk, filler responses like "yeah", "okay", "got it").

B. Compare the in-character lines against the existing voice file. Note:
   - Lines that confirm what's already described
   - Lines that reveal something NEW or NUANCED not yet in the voice file
   - Lines that complicate or contradict the existing characterization

C. Recommend specific lines to add to the "## Lines that capture the voice" section.
   Format each recommendation exactly like the existing entries:

   > "[exact quote]"
   — [one-sentence context annotation explaining why this line is characteristic]

   Only recommend lines that add something genuinely new to the voice file.
   Do not recommend lines already covered by existing examples.
   Do not invent context — base annotations only on what you can infer from the transcript.

D. If the analysis reveals a gap or nuance in the prose description of the voice
   (the paragraphs above "## Lines that capture the voice"), suggest a brief addition
   or clarification in plain language. Keep it short — one or two sentences at most.

Output format:

## In-Character Lines
[list the lines you identified as in-character, with a brief note on each]

## Comparison with Voice File
[what the lines confirm, what's new, what contradicts]

## Recommended Additions

### New lines for "## Lines that capture the voice"
[formatted recommendations]

### Suggested prose addition (if any)
[optional: one or two sentences to add to the prose description]
"""


def parse_vtt(vtt_path: Path) -> list[tuple[str, str]]:
    """Parse a Zoom VTT file into (speaker, text) pairs.

    Zoom VTT format:
        sequence_number
        timestamp --> timestamp
        Speaker Name: dialogue text
        [blank line]
    """
    text = vtt_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    pairs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip WEBVTT header and cue metadata
        if line.startswith("WEBVTT") or re.match(r"^\d+$", line):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}", line):
            continue
        # Speaker line: "Name: text"
        m = re.match(r"^([^:]+):\s*(.+)$", line)
        if m:
            pairs.append((m.group(1).strip(), m.group(2).strip()))
    return pairs


def extract_player_lines(pairs: list[tuple[str, str]], player: str) -> list[str]:
    """Return all dialogue lines attributed to the named player."""
    return [text for speaker, text in pairs if speaker.lower() == player.lower()]


def build_user_prompt(player: str, character: str, player_lines: list[str], voice_text: str) -> str:
    char_label = f"{player} (playing {character})" if character != player else player
    lines_block = "\n".join(f"- {line}" for line in player_lines)
    return f"""\
## Player: {char_label}

### All lines from the transcript

{lines_block}

---

### Existing voice file

{voice_text.strip()}
"""


def append_to_voice_file(voice_path: Path, additions: str) -> None:
    """Append a clearly marked additions block to the voice file."""
    existing = voice_path.read_text(encoding="utf-8")
    separator = "\n\n---\n\n## Suggested additions from VTT analysis\n\n"
    voice_path.write_text(existing.rstrip() + separator + additions.strip() + "\n", encoding="utf-8")
    print(f"\nAppended suggestions to {voice_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("vtt", help="Path to the Zoom .vtt transcript file")
    parser.add_argument("--player", "-p", required=True, help="Speaker label in the VTT (e.g. 'Gabe')")
    parser.add_argument("--character", "-c", help="Character name if different from player label")
    parser.add_argument("--voice-file", "-v", required=True, help="Existing voice file to compare against")
    parser.add_argument("--update", action="store_true", help="Append suggested lines to the voice file")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Claude model to use")
    parser.add_argument("--no-log", action="store_true", help="Skip saving a log file")
    args = parser.parse_args()

    vtt_path = Path(args.vtt).expanduser()
    if not vtt_path.exists():
        print(f"Error: VTT file not found: {vtt_path}", file=sys.stderr)
        sys.exit(1)

    voice_path = Path(args.voice_file).expanduser()
    if not voice_path.exists():
        print(f"Error: voice file not found: {voice_path}", file=sys.stderr)
        sys.exit(1)

    character = args.character or args.player

    print(f"Parsing {vtt_path.name}…")
    pairs = parse_vtt(vtt_path)
    player_lines = extract_player_lines(pairs, args.player)

    if not player_lines:
        print(f"No lines found for speaker '{args.player}' in {vtt_path.name}.", file=sys.stderr)
        print("Available speakers:", sorted({s for s, _ in pairs}), file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(player_lines)} lines for {args.player} ({character}).")

    voice_text = voice_path.read_text(encoding="utf-8")
    user_prompt = build_user_prompt(args.player, character, player_lines, voice_text)

    client = make_client()
    print(f"\nAnalysing against {voice_path.name}…\n")
    response = stream_api(client, ANALYSIS_SYSTEM, user_prompt, args.model)

    if args.update:
        append_to_voice_file(voice_path, response)

    if not args.no_log:
        log_dir = voice_path.parent / "logs"
        save_log(
            str(log_dir),
            [
                ("Player lines extracted", "\n".join(f"- {l}" for l in player_lines)),
                ("Voice file", voice_text),
                ("Analysis", response),
            ],
            stem=f"vtt_voice_{args.player.lower()}",
        )
        print(f"Log saved to {log_dir}/")


if __name__ == "__main__":
    main()
