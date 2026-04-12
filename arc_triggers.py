#!/usr/bin/env python3
"""Search for arc score trigger candidates using mempalace.

Finds a character's arc score tracking document via mempalace search,
reads the trigger definitions from it, then searches the chronicle wing
for events that match each trigger. Returns candidates organized by
trigger with source references.

This is a candidate-finding tool — the DM makes the final precision
decision about whether a trigger actually fires.

Usage:
    python arc_triggers.py --character brewbarry
    python arc_triggers.py --character soma
    python arc_triggers.py --character brewbarry --top 5

Requires mempalace to be installed with chronicle and phandalin wings mined.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

CAMPAIGN_DIR = Path(os.environ.get("CAMPAIGN_DIR", Path.cwd())).resolve()
TRACKING_DIR = CAMPAIGN_DIR / "docs" / "tracking"
MP_BIN = "/home/kroussos/worldanvil_pipeline/venv/bin/mempalace"


# ── Mempalace search ────────────────────────────────────────────────────────

def search_mempalace(
    query: str, wing: str | None = None, room: str | None = None, top: int = 3
) -> list[dict]:
    """Run a mempalace search and parse the structured CLI output."""
    cmd = [MP_BIN, "search", query]
    if wing:
        cmd += ["--wing", wing]
    if room:
        cmd += ["--room", room]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return [{"error": str(e)}]

    results = []
    current: dict | None = None

    for line in output.splitlines():
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
        source_match = re.match(r"\s*Source:\s*(.+)", line)
        if source_match:
            current["source"] = source_match.group(1).strip()
            continue
        score_match = re.match(r"\s*Match:\s*(.+)", line)
        if score_match:
            current["score"] = score_match.group(1).strip()
            continue
        if re.match(r"\s*[─━]+\s*$", line):
            continue
        stripped = line.strip()
        if stripped:
            current["content"].append(stripped)

    if current:
        results.append(current)
    return results[:top]


# ── Score document discovery ─────────────────────────────────────────────────

def find_score_file(character: str) -> Path | None:
    """Search mempalace for the character's score tracking doc, return its path."""
    results = search_mempalace(
        f"{character} score triggers", wing="phandalin", room="arcs", top=5
    )
    # Look for a tracking file in the results
    for r in results:
        source = r.get("source", "")
        if not source:
            continue
        # Try to find it in the tracking directory
        candidate = TRACKING_DIR / source
        if candidate.exists():
            return candidate
    # Fallback: glob the tracking directory for the character name
    for f in TRACKING_DIR.glob("*.md"):
        if character.lower() in f.name.lower():
            return f
    return None


# ── Trigger extraction ───────────────────────────────────────────────────────

def extract_trigger_section(text: str) -> str:
    """Extract just the trigger-definition section from a score document.

    Looks for headers like:
      - "Score Increase Triggers:"
      - "Catalysts for Increase"
      - "Triggers" / "Score Triggers"

    Stops at the first section break after (horizontal rule, roman numeral
    header, "Score N:" ability block, or "Escalation" header).
    """
    # Find the start of the triggers section
    start_patterns = [
        r"\*\*.*(?:Trigger|Catalyst).*\*\*",
        r"^#+\s.*(?:Trigger|Catalyst)",
    ]
    start_pos = None
    for pat in start_patterns:
        m = re.search(pat, text, re.MULTILINE | re.IGNORECASE)
        if m:
            start_pos = m.end()
            break

    if start_pos is None:
        # No explicit trigger header — use the whole text up to the first
        # section break (some docs just start with bullet triggers)
        start_pos = 0

    remainder = text[start_pos:]

    # Find where triggers end
    end_patterns = [
        r"^-{3,}",                          # horizontal rule ---
        r"^\*\*(?:II|III)\.",                # roman numeral section headers
        r"^\*\*Score \d+:",                  # ability tier headers (Score 3:, Score 6:, etc.)
        r"(?:Escalation|Symptoms|Lore Master|Strategy)",  # named section breaks
        r"^#{1,3}\s",                        # markdown headings
    ]
    end_pos = len(remainder)
    for pat in end_patterns:
        m = re.search(pat, remainder, re.MULTILINE)
        if m and m.start() > 0:
            end_pos = min(end_pos, m.start())

    return remainder[:end_pos]


def extract_triggers(text: str) -> list[dict]:
    """Parse trigger definitions from a score tracking document.

    Extracts the trigger section first, then finds bullet points matching:
      * **Name:** description
      - **+N for Name:** description

    Returns list of {name, description} dicts.
    """
    section = extract_trigger_section(text)

    triggers = []
    pattern = re.compile(
        r"^[\*\-]\s+\*\*(.+?):\*\*\s+(.+)",
        re.MULTILINE,
    )
    for match in pattern.finditer(section):
        name = match.group(1).strip()
        description = match.group(2).strip()
        triggers.append({"name": name, "description": description})

    return triggers


def truncate_for_search(description: str, max_len: int = 200) -> str:
    """Take the first sentence or two for a focused semantic search query."""
    # Cut at sentence boundaries
    sentences = re.split(r"(?<=[.!?])\s+", description)
    result = ""
    for s in sentences:
        if len(result) + len(s) > max_len and result:
            break
        result = (result + " " + s).strip()
    # Strip markdown artifacts
    result = re.sub(r"\*+", "", result)
    result = re.sub(r"\[.*?\]", "", result)
    return result


# ── Main search logic ────────────────────────────────────────────────────────

def search_triggers(character: str, top: int = 3) -> str:
    """Find score doc, extract triggers, search chronicle for candidates."""
    # Step 1: Find the score tracking document
    score_file = find_score_file(character)
    if score_file is None:
        return (
            f"Could not find a score tracking document for '{character}'.\n"
            f"Searched mempalace (phandalin/arcs) and {TRACKING_DIR}/.\n"
            f"Available tracking files: {', '.join(f.name for f in TRACKING_DIR.glob('*.md'))}"
        )

    # Step 2: Read and extract triggers
    text = score_file.read_text(encoding="utf-8")
    triggers = extract_triggers(text)

    if not triggers:
        return (
            f"Found score file: {score_file.name}\n"
            f"But could not extract any trigger definitions from it.\n"
            f"Expected bullet points like: * **Trigger Name:** description"
        )

    # Extract score name from the first bold line
    score_name_match = re.search(r"\*\*(.+?Score.*?)\*\*", text[:500])
    score_name = score_name_match.group(1) if score_name_match else score_file.stem

    # Step 3: Search chronicle wing for each trigger
    lines = []
    lines.append(f"# Arc Score Trigger Candidates: {score_name}")
    lines.append(f"**Character:** {character.title()}")
    lines.append(f"**Score file:** {score_file.name}")
    lines.append(f"**Source wing:** chronicle (timeline facts)")
    lines.append(f"**Triggers found:** {len(triggers)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for trigger in triggers:
        lines.append(f"## Trigger: {trigger['name']}")
        lines.append(f"*{truncate_for_search(trigger['description'], max_len=300)}*")
        lines.append("")

        # Use the trigger description as the semantic search query
        query = truncate_for_search(trigger["description"])
        results = search_mempalace(query, wing="chronicle", top=top)

        has_results = False
        for r in results:
            if "error" in r:
                lines.append(f"  **Error:** {r['error']}")
                continue
            has_results = True
            content_preview = " ".join(r["content"][:6])
            if len(content_preview) > 300:
                content_preview = content_preview[:300] + "..."
            lines.append(f"- **{r['source']}** (score: {r['score']})")
            lines.append(f"  {content_preview}")
            lines.append("")

        if not has_results:
            lines.append("*No candidates found in chronicle.*")
            lines.append("")

        lines.append("")

    lines.append("---")
    lines.append("*Candidates only — DM decides whether a trigger actually fires.*")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Search for arc score trigger candidates via mempalace"
    )
    parser.add_argument(
        "--character", "-c",
        help="Character name (searches mempalace for their score tracking doc)",
    )
    parser.add_argument(
        "--top", "-t", type=int, default=3,
        help="Max chronicle results per trigger (default: 3)",
    )
    args = parser.parse_args()

    if not args.character:
        # List available tracking files
        print("Usage: arc_triggers.py --character <name>")
        print("")
        print(f"Tracking files in {TRACKING_DIR}:")
        for f in sorted(TRACKING_DIR.glob("*.md")):
            print(f"  {f.name}")
        print("")
        print("The character name is used to search mempalace for the")
        print("matching score document — it doesn't need to be exact.")
        return

    print(search_triggers(args.character, top=args.top))


if __name__ == "__main__":
    main()
