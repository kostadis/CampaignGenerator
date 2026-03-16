#!/usr/bin/env python3
"""Generate a markdown NPC reference table from one or more campaign documents.

Usage:
  python npc_table.py                          # uses world_state from config
  python npc_table.py --docs world_state planning
  python npc_table.py --output npc_table.md
  python npc_table.py --clipboard
  python npc_table.py --config /path/to/config.yaml
"""

import argparse
from pathlib import Path

from campaignlib import (
    assemble_docs,
    copy_to_clipboard,
    find_default_config,
    load_config,
    make_client,
    save_log,
    stream_api,
)

SYSTEM_PROMPT = """\
You are a campaign document analyst for a D&D game. Your only job is to extract \
every named NPC from the provided document(s) and output a markdown table with \
exactly these four columns:

| NPC Name | Faction / Affiliation | Current State | Core Motivations |

Rules:
- Include every named NPC or organisation that functions as an actor (has agency or \
motivations). Omit unnamed mobs or generic soldiers.
- **NPC Name** — bold the name. Include epithets or aliases in the same cell.
- **Faction / Affiliation** — the group, cult, or power the NPC serves.
- **Current State** — where they are and what they are actively doing *right now* \
in the story. Be specific and concrete.
- **Core Motivations** — what they ultimately want. Surface the hidden agenda where \
known.
- Do not add commentary, headers, or any text outside the table.
- Output only the markdown table, nothing else.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an NPC reference table from campaign documents."
    )
    parser.add_argument("--docs", "-d", nargs="+", default=["world_state"], metavar="LABEL",
                        help="Document labels from config (default: world_state)")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Save the table to this file")
    parser.add_argument("--clipboard", "-c", action="store_true",
                        help="Copy the table to clipboard")
    parser.add_argument("--config", default=find_default_config(__file__),
                        help="Path to config YAML")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    parser.add_argument("--no-log", action="store_true", help="Skip saving a log file")
    args = parser.parse_args()

    config, config_dir = load_config(args.config)
    user_prompt = assemble_docs(config, args.docs, config_dir)

    client = make_client()
    print(f"\n[NPC Table | docs: {', '.join(args.docs)} | model: {args.model}]\n")
    print("=" * 60)
    table = stream_api(client, SYSTEM_PROMPT, user_prompt, args.model, max_tokens=4096)
    print("=" * 60)

    if args.output:
        out = Path(args.output).expanduser()
        out.write_text(table.strip() + "\n", encoding="utf-8")
        print(f"Table saved to: {out}")

    if args.clipboard:
        copy_to_clipboard(table)

    if not args.no_log:
        log_dir = config.get("log_dir", "logs/")
        log_file = save_log(log_dir, [("NPC Table", table)], stem="npc_table")
        print(f"Log saved to: {log_file}")


if __name__ == "__main__":
    main()
