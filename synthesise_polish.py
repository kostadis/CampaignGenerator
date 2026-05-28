#!/usr/bin/env python3
"""Layer-2 LLM render of merged.json into extract_NNN.md-shape markdown.

Takes the deterministic grouping of facts (from ``ensemble_extract.py`` →
``merged.json``), sends the structured input to Claude, and asks it to
render profile-style sections matching the shape of the campaign's
``distill_extractions/extract_NNN.md`` baseline.

This is the **"LLM renders inside verified structure"** step from the LLM
Pipeline Design Rule::

    local LLM extracts → deterministic merge → deterministic group
        → Claude renders inside that structure → human reviews

The merged.json artifact is the human-reviewable checkpoint between the
two LLM stages. Local LLMs do the noisy extraction; Claude does the
high-precision synthesis. Each LLM is used where it is strongest.

Output shape (modelled on existing ``extract_NNN.md`` files):

  ## NPCs
  **Name**
  - Current location: ...
  - Current state: ...
  - Recent actions: ...
  - Faction: ...
  - Motivations: ...
  - Notes: ...

  ## Monsters
  ## Factions
  ## Locations
  ## Objects
  ## World Events       (chronological bulleted list)
  ## Threads & Mysteries

Usage::

    python synthesise_polish.py runs/session/merged.json -o polished.md
    python synthesise_polish.py merged.json -o polished.md --aliases aliases.json
    python synthesise_polish.py merged.json -o polished.md --model claude-opus-4-7
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from campaignlib import DEFAULT_MODEL, make_client, stream_api

SYSTEM_PROMPT = """You are a campaign documentation writer for a D&D session. You receive a structured list of atomic facts about one session, grouped by type and subject. You render them as a clean markdown document matching the shape below.

Output shape:

## NPCs

**{Name}**
- Current location: {one-line summary from location-related facts; "Unknown" if none}
- Current state: {active / trapped / unconscious / dead / dying / etc.}
- Recent actions: {semicolon-joined list of this character's actions this session}
- Faction: {from faction-membership facts; omit if unknown}
- Motivations: {if stated or implied by the facts; omit if unknown}
- Notes: {anything else worth flagging — quirks, descriptors, history mentioned}

## Monsters

**{Creature type}**
- Count and location: {how many, where they appear}
- What it did: {actions taken in this session}
- Current state: {active / injured / killed / fled}

## Factions

**{Faction}**
- Goals: {what they want}
- Members: {key individuals if listed}
- Recent actions: {this session's activity}

## Locations

**{Place}**
- What it is: {one-line definition}
- What happened there: {events tied to this location in this session}
- Current state: {as of session end}

## Objects

**{Item}**
- What it is: {description}
- Who has it: {current owner if known}
- Notes: {how it was acquired, what it does, etc.}

## World Events

Chronological bulleted list of events. Each bullet is one sentence describing what happened. Order by inferred narrative time; if order is ambiguous, group related events together.

## Threads & Mysteries

- **{Thread label}**: {one-to-two-sentence description of the unresolved question}

Rules:

- Do NOT invent facts. If a field has no supporting data in the input, write "Unknown" or omit the field.
- Do NOT editorialize beyond what the input states. No "interestingly", no "notably".
- Use exactly one bold name header per entry.
- Within "Recent actions", separate items with semicolons.
- Order sections exactly as listed above.
- Within each section, order entries alphabetically by name (except World Events, which are chronological).
- Output ONLY the markdown document. No commentary, no preamble, no explanation.
- If multiple facts describe the same action with minor rephrasing, merge them into one bullet rather than repeating.
- If two subjects in the input clearly refer to the same entity (a spelling drift the merge missed), merge them in your output under the canonical spelling and add a "Notes" line noting the variant.
- When the input contains an in-world date, year, or temporal anchor (`type: date` facts, or "after a long rest" / "an hour later" anchors that landed as `event`), preserve it as a prefix or in-line element of the relevant World Events BULLET. Example bullet: "- On the 5th day of the 2nd Tenday of Taraskh 1493, the group began their march through the Underdark." Do NOT emit a separate "## Dates" section in the output — fold all `date`-type input facts into the World Events bullets where they belong chronologically. Each event remains its own separate bullet — DO NOT collapse World Events into a paragraph. The bulleted-list format of World Events MUST be preserved. Do not drop dates or temporal anchors.
"""


INVENTORY_PREAMBLE = """The following is the canonical name and entity inventory for this campaign, compiled by the GM from the source module. Treat it as the authoritative reference for spellings, factions, identities, and backgrounds.

When you use this inventory:

- If an atomic fact uses a variant spelling that clearly matches an inventory entry (Velkenyvelve → Velkynvelve, Sloopdopblop → Sloobludop, Bemeril → Bemeril, etc.), use the canonical spelling from the inventory in your output.
- Use inventory descriptions to enrich character profiles when the atomic facts are silent on faction, race, role, or background. For example, if the inventory says "Buppido — male derro; talkative serial killer who believes he is the incarnate god Diinkarazan," you may fill in Faction: Derro and Notes details even if the atomic facts only mention his actions.
- Do not invent details that are absent from BOTH the atomic facts AND the inventory. If the inventory has a detail the session didn't touch on (e.g., a character's lineage), only include it if it materially clarifies the session's events.
- The atomic facts are the authoritative source of WHAT HAPPENED this session. The inventory is the authoritative source of WHO/WHAT ENTITIES EXIST. Never let the inventory override the session's events.

---

CANONICAL INVENTORY:

"""


def load_inventory(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_aliases(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    flat: dict[str, str] = {}
    for canonical, variants in data.items():
        flat[canonical] = canonical
        for v in variants:
            flat[v] = canonical
    return flat


TYPE_ORDER = ["npc", "monster", "faction", "location", "object", "date", "event", "thread"]


def build_input(facts: list[dict], aliases: dict[str, str]) -> str:
    """Group facts by (type, canonical_subject) and format as structured input."""
    by_type: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for f in facts:
        t = f.get("type", "unknown")
        subject = f.get("subject", "")
        canonical = aliases.get(subject, subject)
        fact_text = f.get("fact", "").strip()
        if fact_text:
            by_type[t][canonical].append(fact_text)

    lines: list[str] = []
    for t in TYPE_ORDER:
        if t not in by_type:
            continue
        lines.append(f"# Type: {t}")
        lines.append("")
        for subject in sorted(by_type[t].keys(), key=str.lower):
            lines.append(f"## {subject}")
            for fact_text in by_type[t][subject]:
                lines.append(f"- {fact_text}")
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render merged.json into extract_NNN.md-shape markdown via Claude. "
            "Layer-2 of the synthesis pipeline; assumes Layer-1 (merge) has "
            "already been reviewed."
        )
    )
    parser.add_argument("merged", help="Path to merged.json from ensemble_extract.py")
    parser.add_argument("--output", "-o", required=True,
                        help="Where to write the polished markdown.")
    parser.add_argument("--aliases", default=None, metavar="FILE",
                        help="Optional aliases.json mapping canonical → [variants]. "
                             "Variants collapse into the canonical subject before "
                             "Claude sees the input.")
    parser.add_argument("--inventory", default=None, metavar="FILE",
                        help="Optional canonical-name inventory (markdown). Passed "
                             "to Claude as authoritative reference for spellings, "
                             "factions, and identities. Use the campaign's "
                             "module proper-noun inventory.")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Claude model id (default: {DEFAULT_MODEL}). "
                             f"Use claude-opus-4-7 for highest quality, "
                             f"claude-sonnet-4-6 for speed/cost.")
    parser.add_argument("--max-tokens", type=int, default=16000,
                        help="max_tokens for the render call (default: 16000). "
                             "Synthesis can be long; raise if output is truncated.")
    parser.add_argument("--dump-input", default=None, metavar="FILE",
                        help="Also write the structured input we send to Claude. "
                             "Useful for debugging the prompt without spending tokens.")
    args = parser.parse_args()

    merged_path = Path(args.merged).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    aliases_path = Path(args.aliases).expanduser().resolve() if args.aliases else None
    inventory_path = Path(args.inventory).expanduser().resolve() if args.inventory else None

    if not merged_path.exists():
        print(f"Error: merged.json not found: {merged_path}", file=sys.stderr)
        sys.exit(1)

    facts = json.loads(merged_path.read_text(encoding="utf-8"))
    aliases = load_aliases(aliases_path)
    inventory_text = load_inventory(inventory_path)
    input_text = build_input(facts, aliases)

    system_prompt = SYSTEM_PROMPT
    if inventory_text:
        system_prompt = SYSTEM_PROMPT + "\n\n" + INVENTORY_PREAMBLE + inventory_text

    if args.dump_input:
        Path(args.dump_input).expanduser().resolve().write_text(
            input_text, encoding="utf-8"
        )
        print(f"Dumped structured input: {args.dump_input}")

    inv_note = f" | inventory: {inventory_path.name}" if inventory_text else ""
    print(f"[Polish | {len(facts)} facts | model: {args.model}{inv_note}]")
    print("=" * 60)

    client = make_client()
    response = stream_api(
        client,
        system_prompt,
        input_text,
        args.model,
        max_tokens=args.max_tokens,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(response.strip() + "\n", encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"Wrote polished synthesis: {output_path}")
    print(f"Source facts: {len(facts)}")
    if aliases:
        canonicals = len({v for v in aliases.values()})
        print(f"Aliases applied: {canonicals} canonical entities "
              f"({len(aliases)} variant mappings)")
    if inventory_text:
        print(f"Inventory: {len(inventory_text):,} chars from {inventory_path}")


if __name__ == "__main__":
    main()
