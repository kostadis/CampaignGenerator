#!/usr/bin/env python3
"""Convert a D&D Beyond character sheet PDF into a structured markdown document.

Extracts text via PyMuPDF (no vision required) and sends it to Claude as a
plain-text prompt. Works with the claude-code (subscription) backend.

Usage:
  python dnd_sheet.py Soma.pdf --output soma.md
  python dnd_sheet.py Soma.pdf                    # writes to doc/
  python dnd_sheet.py *.pdf --output-dir ~/campaigns/Phandalin/characters/
"""

import argparse
import sys
from pathlib import Path

import fitz  # pymupdf

from campaignlib import make_client, call_api, DEFAULT_MODEL

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


def extract_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n\n".join(pages)


def pdf_to_markdown(client, pdf_path: Path, model: str) -> str:
    text = extract_text(pdf_path)
    user_prompt = (
        "Please convert this D&D Beyond character sheet into the structured "
        f"markdown format.\n\n{text}"
    )
    return call_api(client, SYSTEM_PROMPT, user_prompt, model)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a D&D Beyond character sheet PDF to markdown."
    )
    parser.add_argument("pdfs", nargs="+", metavar="PDF",
                        help="PDF file(s) to convert")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Output file (single PDF only). Overrides --output-dir.")
    parser.add_argument("--output-dir", metavar="DIR", default="doc",
                        help="Output directory (default: doc). One .md per PDF.")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Claude model to use")
    args = parser.parse_args()

    client = make_client()

    for pdf_path_str in args.pdfs:
        pdf_path = Path(pdf_path_str).expanduser().resolve()
        if not pdf_path.exists():
            print(f"Error: file not found: {pdf_path}", file=sys.stderr)
            sys.exit(1)

        print(f"Converting {pdf_path.name}...", file=sys.stderr)
        markdown = pdf_to_markdown(client, pdf_path, args.model)

        if args.output and len(args.pdfs) == 1:
            out = Path(args.output).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(markdown.strip() + "\n", encoding="utf-8")
        else:
            out_dir = Path(args.output_dir).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / (pdf_path.stem + ".md")
            out.write_text(markdown.strip() + "\n", encoding="utf-8")
        print(f"Saved to: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
