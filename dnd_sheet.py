#!/usr/bin/env python3
"""Convert a D&D Beyond character sheet PDF into a structured markdown document.

Uses the Claude API's document vision to read the PDF directly — no text
extraction library required. Works with D&D Beyond's rendered/visual PDFs.

Usage:
  python dnd_sheet.py Soma.pdf --output soma.md
  python dnd_sheet.py Soma.pdf         # prints to stdout
  python dnd_sheet.py *.pdf --output-dir ~/campaigns/Phandalin/characters/
"""

import argparse
import base64
import sys
from pathlib import Path

from campaignlib import make_client, call_api

SYSTEM_PROMPT = """\
You are converting a D&D Beyond character sheet PDF into a clean markdown document \
for use as a campaign reference.

Extract ALL information visible on the sheet and structure it as follows:

# [Character Name]

## Identity
- **Class & Level:**
- **Species:**
- **Background:**
- **Player:**
- **Alignment:**
- **Age / Gender / Size:**

## Ability Scores
| Ability | Score | Modifier |
|---|---|---|
| Strength | | |
| Dexterity | | |
| Constitution | | |
| Intelligence | | |
| Wisdom | | |
| Charisma | | |

## Combat
- **HP:** (max / current)
- **AC:**
- **Initiative:**
- **Speed:**
- **Hit Dice:**
- **Proficiency Bonus:**

## Saving Throws
List each with modifier and whether proficient.

## Skills
List each skill with modifier and proficiency status.

## Proficiencies & Languages
List armor, weapons, tools, and languages.

## Attacks & Cantrips
| Name | Hit | Damage | Notes |
|---|---|---|---|

## Features & Traits
List all class features, racial traits, and background features with their descriptions.

## Feats
List each feat with its description.

## Equipment
List all items carried.

## Spells
If applicable, list spell slots and known/prepared spells by level.

## Personality
- **Traits:**
- **Ideals:**
- **Bonds:**
- **Flaws:**

## Notes
Any additional information from the sheet.

Rules:
- Include every piece of information visible on the sheet.
- Preserve modifier signs (e.g. +4, -1).
- For features and traits, include the full description text, not just the name.
- If a field is blank on the sheet, omit it.
- Output only the markdown document. No preamble or commentary.
"""


def pdf_to_markdown(client, pdf_path: Path, model: str) -> str:
    pdf_data = base64.standard_b64encode(pdf_path.read_bytes()).decode("utf-8")
    content = [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_data,
            },
        },
        {
            "type": "text",
            "text": "Please convert this D&D Beyond character sheet into the structured markdown format.",
        },
    ]
    return call_api(client, SYSTEM_PROMPT, content, model)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a D&D Beyond character sheet PDF to markdown."
    )
    parser.add_argument("pdfs", nargs="+", metavar="PDF",
                        help="PDF file(s) to convert")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Output file (single PDF only)")
    parser.add_argument("--output-dir", metavar="DIR",
                        help="Output directory for multiple PDFs (uses <name>.md as filename)")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    args = parser.parse_args()

    if args.output and len(args.pdfs) > 1:
        print("Error: --output can only be used with a single PDF. Use --output-dir for multiple.", file=sys.stderr)
        sys.exit(1)

    client = make_client()

    for pdf_path_str in args.pdfs:
        pdf_path = Path(pdf_path_str).expanduser().resolve()
        if not pdf_path.exists():
            print(f"Error: file not found: {pdf_path}", file=sys.stderr)
            sys.exit(1)

        print(f"Converting {pdf_path.name}...", file=sys.stderr)
        markdown = pdf_to_markdown(client, pdf_path, args.model)

        if args.output:
            out = Path(args.output).expanduser()
            out.write_text(markdown.strip() + "\n", encoding="utf-8")
            print(f"Saved to: {out}", file=sys.stderr)
        elif args.output_dir:
            out_dir = Path(args.output_dir).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / (pdf_path.stem + ".md")
            out.write_text(markdown.strip() + "\n", encoding="utf-8")
            print(f"Saved to: {out}", file=sys.stderr)
        else:
            print(markdown)


if __name__ == "__main__":
    main()
