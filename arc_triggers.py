#!/usr/bin/env python3
"""Search for arc score trigger candidates using mempalace.

Reads a character's arc score tracking file, extracts trigger definitions,
then searches the chronicle wing for events that match each trigger type.
Returns candidates organized by trigger, with source references.

This is a candidate-finding tool — the DM makes the final precision decision
about whether a trigger actually fires.

Usage:
    python arc_triggers.py --character brewbarry
    python arc_triggers.py --character soma
    python arc_triggers.py --character brewbarry --top 5
    python arc_triggers.py --list

Requires mempalace to be installed and the chronicle wing to be mined.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

CAMPAIGN_DIR = Path(os.environ.get("CAMPAIGN_DIR", Path.cwd())).resolve()
TRACKING_DIR = CAMPAIGN_DIR / "docs" / "tracking"
MP_BIN = "/home/kroussos/worldanvil_pipeline/venv/bin/mempalace"

# Map character names to their score tracking files and search queries per trigger.
# Each trigger has a name and a list of search queries to run against the chronicle wing.
SCORE_REGISTRY: dict[str, dict] = {
    "brewbarry": {
        "score_name": "The Thistle's Echo Score",
        "character": "Brewbarry",
        "file_pattern": "Thistle*Echo*",
        "triggers": [
            {
                "name": "Goodberry Sedation",
                "description": "Magically conjured food, berries, or herbal remedies used to solve a problem",
                "queries": [
                    "goodberry magical food berries herbal remedy",
                    "Soma conjured food pacify berries",
                    "magical sustenance enchanted food",
                ],
            },
            {
                "name": "Hiss of the Drake",
                "description": "Party encounters drakes, or reptilian hiss in the dark",
                "queries": [
                    "drake encounter reptilian hiss",
                    "guard drake creature stalking",
                    "drake combat lizard serpent",
                ],
            },
            {
                "name": "Death from Above",
                "description": "Aerial archery advantage — flying to elevated position and striking with precision",
                "queries": [
                    "aerial archery flying elevated position bow",
                    "attack from above ranged elevated",
                    "flying archer striking from height",
                ],
            },
            {
                "name": "Seelie Condescension",
                "description": "Deception or performative manipulation to trick a guard or sentry",
                "queries": [
                    "Vukradin deception trick guard sentry",
                    "Valphine manipulation deceive performance",
                    "tricked guard deception performance sentry",
                ],
            },
        ],
    },
    "soma": {
        "score_name": "Soma's Meril's Legacy Score",
        "character": "Soma",
        "file_pattern": "soma-legacy*",
        "triggers": [
            {
                "name": "+1 Subtle Discernment",
                "description": "Prioritizes broader natural balance over radical naturalism; uncovers subtle unnatural interference",
                "queries": [
                    "Soma natural balance druidic choice",
                    "Adabra radical naturalism misdirected",
                    "psionic influence subtle interference unnatural",
                    "Whispering Grove planar corruption contain",
                ],
            },
            {
                "name": "+2 Active Intervention",
                "description": "Thwarts immediate threat to natural order; counters Kraken Society or misdirected actions",
                "queries": [
                    "Kraken Society outpost psionic disrupting",
                    "Soma intervene natural order threat",
                    "Adabra undermine Interventionist sabotage",
                    "corrupted energy unnatural harvest",
                ],
            },
            {
                "name": "+3 Unveiling Deception",
                "description": "Uncovers deeper manipulation behind natural disturbances or faction conflicts",
                "queries": [
                    "Adabra secret dealings draconic cultists",
                    "Kraken Society artifacts stolen ancient",
                    "illithid technology weaponry alien Kraken",
                    "psionic influence key figures manipulate",
                ],
            },
            {
                "name": "+4 Planar Harmony",
                "description": "Combats extraplanar distortions, cosmic engineering, or advanced plots of Tiamat/Iymrith",
                "queries": [
                    "planar breach distortion rift stabilize",
                    "KP cosmic engineering ruinstone beacon",
                    "Adabra pact Tiamat Iymrith unleash",
                    "Aletra Planar Energy Conduit confronting",
                ],
            },
        ],
    },
}


def search_mempalace(query: str, wing: str = "chronicle", top: int = 3) -> list[dict]:
    """Run a mempalace search and parse the output into structured results."""
    cmd = [MP_BIN, "search", query, "--wing", wing]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return [{"error": str(e)}]

    results = []
    current: dict | None = None

    for line in output.splitlines():
        # Match result header: [N] wing / room
        header_match = re.match(r"\s*\[(\d+)\]\s+(\S+)\s*/\s*(\S+)", line)
        if header_match:
            if current:
                results.append(current)
            current = {
                "rank": int(header_match.group(1)),
                "wing": header_match.group(2),
                "room": header_match.group(3),
                "source": "",
                "score": "",
                "content": [],
            }
            continue

        if current is None:
            continue

        # Source line
        source_match = re.match(r"\s*Source:\s*(.+)", line)
        if source_match:
            current["source"] = source_match.group(1).strip()
            continue

        # Match score
        score_match = re.match(r"\s*Match:\s*(.+)", line)
        if score_match:
            current["score"] = score_match.group(1).strip()
            continue

        # Separator line
        if re.match(r"\s*[─━]+\s*$", line):
            continue

        # Content lines
        stripped = line.strip()
        if stripped:
            current["content"].append(stripped)

    if current:
        results.append(current)

    return results[:top]


def format_results(character_config: dict, top: int = 3) -> str:
    """Search for all triggers and format results."""
    lines = []
    score_name = character_config["score_name"]
    character = character_config["character"]

    lines.append(f"# Arc Score Trigger Candidates: {score_name}")
    lines.append(f"**Character:** {character}")
    lines.append(f"**Source wing:** chronicle (timeline facts)")
    lines.append("")
    lines.append("---")
    lines.append("")

    for trigger in character_config["triggers"]:
        lines.append(f"## Trigger: {trigger['name']}")
        lines.append(f"*{trigger['description']}*")
        lines.append("")

        # Search with each query and deduplicate by source
        seen_sources: set[str] = set()
        all_results: list[dict] = []

        for query in trigger["queries"]:
            results = search_mempalace(query, wing="chronicle", top=top)
            for r in results:
                if "error" in r:
                    lines.append(f"  **Error:** {r['error']}")
                    continue
                source_key = r["source"]
                if source_key not in seen_sources:
                    seen_sources.add(source_key)
                    all_results.append(r)

        if not all_results:
            lines.append("*No candidates found in chronicle.*")
            lines.append("")
            continue

        for r in all_results[:top * 2]:  # show more since we deduplicated
            content_preview = " ".join(r["content"][:6])
            if len(content_preview) > 300:
                content_preview = content_preview[:300] + "..."
            lines.append(f"- **{r['source']}** (score: {r['score']})")
            lines.append(f"  {content_preview}")
            lines.append("")

        lines.append("")

    lines.append("---")
    lines.append("*Candidates only — DM decides whether a trigger actually fires.*")
    return "\n".join(lines)


def list_characters() -> str:
    """List available characters and their scores."""
    lines = ["Available arc score searches:", ""]
    for key, config in SCORE_REGISTRY.items():
        triggers = ", ".join(t["name"] for t in config["triggers"])
        lines.append(f"  **{key}** — {config['score_name']}")
        lines.append(f"    Triggers: {triggers}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Search for arc score trigger candidates")
    parser.add_argument("--character", "-c", help="Character name (e.g. brewbarry, soma)")
    parser.add_argument("--top", "-t", type=int, default=3, help="Max results per query (default: 3)")
    parser.add_argument("--list", "-l", action="store_true", help="List available characters")
    args = parser.parse_args()

    if args.list or not args.character:
        print(list_characters())
        return

    character = args.character.lower()
    if character not in SCORE_REGISTRY:
        print(f"Unknown character: {args.character}")
        print(f"Available: {', '.join(SCORE_REGISTRY.keys())}")
        sys.exit(1)

    print(format_results(SCORE_REGISTRY[character], top=args.top))


if __name__ == "__main__":
    main()
