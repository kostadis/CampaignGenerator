#!/usr/bin/env python3
"""Pull Kanka CE world state → render a CampaignGenerator `world_state.md`.

Kanka Community Edition is a self-hosted campaign wiki (NPCs, factions,
locations, events, notes). CampaignGenerator's prep and narration tools read
flat grounding markdown — `world_state.md` is its "living canon" layer.
This script bridges the two: it reads every entity for a campaign out of
Kanka's REST API and renders the same
``## NPCs / ## Factions / ## Locations / ## World Events / ## Threads``
profile shape ``synthesise_world_state.py`` emits, so the output drops
straight into a CampaignGenerator grounding-docs slot.

Direction: Kanka CE  →  world_state.md  (read-only against Kanka).
The reverse (post-session push of updated NPC/location states back into Kanka)
lives in ``kanka_push.py``; it is intentionally NOT done here so a pull can
never mutate canon.

Safety (mirrors synthesise_world_state.py):
  --output is REQUIRED and never defaults to a canonical doc. Point it at a
  scratch file, diff, then promote. A partial/empty pull cannot silently
  overwrite a hand-curated world_state.md.

Entity → section mapping:
  characters     → NPCs            (title as subtitle; is_dead → "(deceased)")
  organisations  → Factions
  locations      → Locations       (is_destroyed → "(destroyed)")
  events         → World Events     (date prefixed when present)
  notes          → Threads & Mysteries

Private entities (is_private=true) are GM-secret and skipped by default; pass
--include-private to fold them in (mark the output clearly before sharing).

Usage:
    export KANKA_TOKEN=<your-api-token>
    export KANKA_BASE_URL=http://localhost:8081   # default
    kanka_sync --campaign 1 --output docs/world_state.generated.md
    kanka_sync --campaign 1 --stdout        # preview, no file write
"""

import argparse
import html
import os
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from .kanka_client import KankaClient

# Render order mirrors CampaignGenerator's TYPE_HEADINGS so the output is a
# drop-in for the distill / synthesise pipeline.
SECTIONS = [
    ("characters", "NPCs"),
    ("organisations", "Factions"),
    ("locations", "Locations"),
    ("events", "World Events"),
    ("notes", "Threads & Mysteries"),
]


class _TextExtractor(HTMLParser):
    """Collapse Kanka's stored HTML `entry` into readable plain text.

    Kanka entries are HTML (``<p>…</p>``, ``<ul><li>…``, ``<strong>``). The
    grounding doc is markdown read by an LLM, so we want clean prose, not tags.
    Block elements become paragraph/line breaks; list items become "- " bullets.
    Stdlib only — no bleach/bs4 dependency for a one-way strip.
    """

    _BLOCKS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
               "tr", "blockquote"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self._parts.append("\n- ")
        elif tag in self._BLOCKS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._BLOCKS:
            self._parts.append("\n")

    def handle_data(self, data):
        self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [ln.strip() for ln in raw.splitlines()]
        out: list[str] = []
        blank = False
        for ln in lines:
            if ln:
                out.append(ln)
                blank = False
            elif not blank and out:
                out.append("")
                blank = True
        return "\n".join(out).strip()


def html_to_text(value: str | None) -> str:
    """HTML entry → trimmed plain text (entities unescaped, tags stripped)."""
    if not value:
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    return html.unescape(parser.text())


def entity_block(ent: dict, entity_type: str) -> str:
    """One ``**Name** … prose`` profile for a single Kanka entity."""
    name = (ent.get("name") or "Unnamed").strip()

    flags: list[str] = []
    subtype = (ent.get("type") or "").strip()
    if subtype:
        flags.append(subtype)
    if ent.get("is_dead"):
        flags.append("deceased")
    if ent.get("is_destroyed"):
        flags.append("destroyed")
    if ent.get("is_private"):
        flags.append("GM-private")

    header = f"**{name}**"
    if flags:
        header += f" — _{', '.join(flags)}_"

    lines = [header]

    title = (ent.get("title") or "").strip()
    if title:
        lines.append(f"- {title}")

    if entity_type == "events":
        date = (ent.get("date") or "").strip()
        if date:
            lines.append(f"- In-world date: {date}")

    body = html_to_text(ent.get("entry"))
    if body:
        lines.append("")
        lines.append(body)

    return "\n".join(lines)


def render_section(heading: str, entities: list[dict], entity_type: str) -> str:
    """A ``## Heading`` block, entities sorted by name (deterministic output)."""
    ordered = sorted(entities, key=lambda e: (e.get("name") or "").lower())
    blocks = [entity_block(e, entity_type) for e in ordered]
    return f"## {heading}\n\n" + "\n\n".join(blocks)


def build_world_state(client: KankaClient, campaign_id: int,
                      include_private: bool) -> tuple[str, dict[str, int]]:
    """Pull all sections and render the full world_state markdown.

    Returns (markdown, counts-per-type) so the CLI can report what it captured.
    """
    campaign = next(
        (c for c in client.list_campaigns() if c["id"] == campaign_id), None
    )
    campaign_name = campaign["name"] if campaign else f"Campaign {campaign_id}"

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = [
        f"# World State — {campaign_name}",
        "",
        f"> Generated from Kanka CE (campaign {campaign_id}) by "
        f"`kanka_sync.py` on {stamp}.",
        "> This is a derived grounding document — edit Kanka CE, not this file, "
        "then regenerate.",
    ]

    counts: dict[str, int] = {}
    for entity_type, heading in SECTIONS:
        entities = client.list_all(campaign_id, entity_type)
        if not include_private:
            entities = [e for e in entities if not e.get("is_private")]
        counts[entity_type] = len(entities)
        if not entities:
            continue
        parts.append("")
        parts.append(render_section(heading, entities, entity_type))

    return "\n".join(parts).strip() + "\n", counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull Kanka CE world state into a CampaignGenerator "
                    "world_state.md grounding document."
    )
    parser.add_argument("--campaign", type=int, default=1,
                        help="Kanka campaign id (default: 1).")
    out = parser.add_mutually_exclusive_group(required=True)
    out.add_argument("--output", "-o", metavar="FILE",
                     help="Where to write world_state markdown. REQUIRED "
                          "(or --stdout). Never defaulted — point at a scratch "
                          "file and diff before promoting over a curated "
                          "world_state.md.")
    out.add_argument("--stdout", action="store_true",
                     help="Print to stdout instead of writing a file (preview).")
    parser.add_argument("--include-private", action="store_true",
                        help="Include is_private (GM-secret) entities. Off by "
                             "default; mark the output before sharing with players.")
    parser.add_argument("--base-url", default=None,
                        help="Kanka base URL (default: $KANKA_BASE_URL or "
                             "http://localhost:8081).")
    args = parser.parse_args()

    token = os.environ.get("KANKA_TOKEN")
    if not token:
        print("Error: set KANKA_TOKEN env var to your Kanka API token.", file=sys.stderr)
        sys.exit(1)

    base_url = args.base_url or os.environ.get("KANKA_BASE_URL", "http://localhost:8081")
    client = KankaClient(token, base_url=base_url)

    markdown, counts = build_world_state(client, args.campaign, args.include_private)

    summary = ", ".join(f"{counts[t]} {t}" for t, _ in SECTIONS)
    private_note = " (incl. private)" if args.include_private else ""
    print(f"[Kanka campaign {args.campaign}{private_note}] {summary}", file=sys.stderr)

    if args.stdout:
        print(markdown)
        return

    path = Path(args.output).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    print(f"Wrote world_state: {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
