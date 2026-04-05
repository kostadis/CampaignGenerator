#!/usr/bin/env python3
"""Push campaign docs to Scabard as structured pages.

Two passes:
  1. Extract — Claude parses world_state, campaign_state, and party docs and
     produces a JSON list of entities (character, group, location, event).
  2. Sync — creates or updates Scabard pages via the API.

A local manifest (scabard_manifest.json in the campaign dir) tracks
name → thing_id mappings so re-runs update rather than duplicate pages.

Usage:
  python scabard_sync.py \\
      --campaign-id 121 \\
      --username kostadis \\
      --access-key <key> \\
      --world-state docs/world_state.md \\
      --campaign-state docs/campaign_state.md \\
      --party docs/party.md

  # Save extracted entities without syncing (inspect before pushing):
  python scabard_sync.py ... --extract-only --extract-file entities.json

  # Sync from a previously saved extraction:
  python scabard_sync.py ... --from-extract entities.json

  # Dry run: show what would be created/updated without calling the API:
  python scabard_sync.py ... --dry-run
"""

import argparse
import json
import sys
import time
from pathlib import Path

from campaignlib import make_client, stream_api
from scabard_sdk import ScabardAuthError, ScabardClient, ScabardRateLimitError

EXTRACT_SYSTEM = """\
You are a structured data extractor for a D&D campaign world-building tool.
You will be given campaign documents: world state, campaign state, and party roster.
Extract every named entity into a JSON array.

Each entry must have these fields:
  "concept"      – one of: "character", "group", "location", "event"
  "name"         – the entity's canonical name
  "briefSummary" – 1-2 sentence player-facing summary (no GM secrets)
  "description"  – full player-facing markdown: current state, relationships, history
  "secrets"      – GM-only text: hidden motivations, true identity, secret plans, etc.
                   Empty string if none.

Concept rules:
  character – named NPCs and player characters
  group     – factions, guilds, cults, organisations, armies
  location  – named places: cities, dungeons, keeps, taverns, regions
  event     – completed or significant campaign events (battles, discoveries, deaths)

Rules:
  - Extract EVERY named entity. Be exhaustive.
  - description and briefSummary must be player-safe (no GM secrets).
  - secrets contains ONLY information hidden from players.
  - Do not invent anything not in the documents.
  - Output valid JSON only — a bare array, no markdown fences, no commentary.
"""

CONCEPTS = ["character", "group", "location", "event"]


# ── Extraction ────────────────────────────────────────────────────────────────

def extract_entities(client: object, docs_text: str, model: str) -> list[dict]:
    print(f"\n[Pass 1: Extract | {len(docs_text):,} chars | model: {model}]")
    print("=" * 60)
    response = stream_api(client, EXTRACT_SYSTEM, docs_text, model, max_tokens=8192)
    print("=" * 60)

    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()

    entities = json.loads(text)
    print(f"\nExtracted {len(entities)} entities.")
    by_concept: dict[str, int] = {}
    for e in entities:
        by_concept[e.get("concept", "unknown")] = (
            by_concept.get(e.get("concept", "unknown"), 0) + 1
        )
    for concept, count in sorted(by_concept.items()):
        print(f"  {concept}: {count}")
    return entities


# ── Manifest ──────────────────────────────────────────────────────────────────

def load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Sync ──────────────────────────────────────────────────────────────────────

def sync_entities(entities: list[dict], campaign_id: int, username: str,
                  access_key: str, manifest: dict, manifest_path: Path,
                  dry_run: bool) -> dict:
    client = ScabardClient(username=username, access_key=access_key)

    by_concept: dict[str, list[dict]] = {}
    for e in entities:
        concept = e.get("concept", "").lower()
        if concept not in CONCEPTS:
            print(f"  Skipping unknown concept '{concept}' for: {e.get('name')}")
            continue
        by_concept.setdefault(concept, []).append(e)

    for concept in CONCEPTS:
        items = by_concept.get(concept, [])
        if not items:
            continue
        print(f"\n[{concept.upper()}] {len(items)} entities")
        print("=" * 60)

        manifest.setdefault(concept, {})

        if not dry_run:
            # Discover existing pages not yet in the manifest
            for name, thing_id in client.fetch_existing(campaign_id, concept).items():
                if name not in manifest[concept]:
                    manifest[concept][name] = thing_id

        for item in items:
            name = item.get("name", "").strip()
            if not name:
                continue

            kwargs = dict(
                campaign_id=campaign_id,
                concept=concept,
                name=name,
                brief_summary=item.get("briefSummary", ""),
                description=item.get("description", ""),
                secrets=item.get("secrets", ""),
            )

            if name in manifest[concept]:
                thing_id = manifest[concept][name]
                action = f"Update (id={thing_id})"
                if not dry_run:
                    ok = client.update_page(thing_id=thing_id, **kwargs)
                    action += " ✓" if ok else " FAILED"
            else:
                action = "Create"
                if not dry_run:
                    ok, thing_id = client.create_page(**kwargs)
                    if ok:
                        if thing_id:
                            manifest[concept][name] = thing_id
                            action += f" → id={thing_id} ✓"
                        else:
                            action += " ✓ (id unknown)"
                        save_manifest(manifest_path, manifest)
                    else:
                        action += " FAILED"

            print(f"  [{action}] {name}")
            if not dry_run:
                time.sleep(0.4)

    return manifest


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Push campaign docs to Scabard as pages."
    )

    # Scabard auth
    parser.add_argument("--campaign-id", type=int, required=True,
                        help="Scabard campaign ID (number in the campaign URL)")
    parser.add_argument("--username", required=True,
                        help="Scabard username")
    parser.add_argument("--access-key", required=True,
                        help="Scabard API access key (expires 24 hr after generation)")

    # Source docs
    parser.add_argument("--world-state", metavar="FILE",
                        help="world_state.md")
    parser.add_argument("--campaign-state", metavar="FILE",
                        help="campaign_state.md")
    parser.add_argument("--party", metavar="FILE",
                        help="party.md")

    # Extraction control
    parser.add_argument("--extract-file", metavar="FILE", default="scabard_entities.json",
                        help="Where to save/load extracted entities JSON "
                             "(default: scabard_entities.json)")
    parser.add_argument("--extract-only", action="store_true",
                        help="Run extraction and save JSON, then stop (don't sync)")
    parser.add_argument("--from-extract", metavar="FILE",
                        help="Skip extraction; load entities from this JSON file")

    # Manifest and sync control
    parser.add_argument("--manifest", metavar="FILE", default="scabard_manifest.json",
                        help="Local name→id manifest file (default: scabard_manifest.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be created/updated without calling the Scabard API")

    parser.add_argument("--model", default="claude-sonnet-4-6",
                        help="Claude model for extraction (default: claude-sonnet-4-6)")

    args = parser.parse_args()

    # ── Load entities ─────────────────────────────────────────────────────────
    if args.from_extract:
        extract_path = Path(args.from_extract).expanduser().resolve()
        if not extract_path.exists():
            print(f"Error: extract file not found: {extract_path}", file=sys.stderr)
            sys.exit(1)
        entities = json.loads(extract_path.read_text(encoding="utf-8"))
        print(f"Loaded {len(entities)} entities from {extract_path}")
    else:
        doc_parts = []
        for flag, label in [
            (args.world_state, "World State"),
            (args.campaign_state, "Campaign State"),
            (args.party, "Party"),
        ]:
            if flag:
                p = Path(flag).expanduser().resolve()
                if not p.exists():
                    print(f"Error: file not found: {p}", file=sys.stderr)
                    sys.exit(1)
                text = p.read_text(encoding="utf-8").strip()
                if text:
                    doc_parts.append(f"<!-- {label}: {p.name} -->\n\n{text}")

        if not doc_parts:
            print("Error: provide at least one of --world-state, --campaign-state, --party",
                  file=sys.stderr)
            sys.exit(1)

        docs_text = "\n\n---\n\n".join(doc_parts)
        claude_client = make_client()
        entities = extract_entities(claude_client, docs_text, args.model)

        extract_path = Path(args.extract_file).expanduser().resolve()
        extract_path.write_text(
            json.dumps(entities, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nEntities saved to: {extract_path}")

        if args.extract_only:
            print("(--extract-only: stopping before sync)")
            return

    # ── Sync ──────────────────────────────────────────────────────────────────
    if args.dry_run:
        print("\n[Dry run — no Scabard API calls will be made]")

    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = load_manifest(manifest_path)

    print(f"\n[Pass 2: Sync | campaign_id={args.campaign_id} | dry_run={args.dry_run}]")

    try:
        manifest = sync_entities(
            entities,
            campaign_id=args.campaign_id,
            username=args.username,
            access_key=args.access_key,
            manifest=manifest,
            manifest_path=manifest_path,
            dry_run=args.dry_run,
        )
    except ScabardAuthError:
        print(
            "\nError: invalid username or access key (key may have expired).\n"
            "Generate a new key at: https://www.scabard.com/pbs/<username>",
            file=sys.stderr,
        )
        sys.exit(1)
    except ScabardRateLimitError:
        print(
            "\nError: Scabard rate limit exhausted after 4 retries. "
            "Wait a few minutes and try again.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.dry_run:
        save_manifest(manifest_path, manifest)
        print(f"\nManifest saved to: {manifest_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
