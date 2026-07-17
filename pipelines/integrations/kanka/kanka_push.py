#!/usr/bin/env python3
"""Push a `world_state.md` grounding doc back into Kanka CE.

The inverse of `kanka_sync.py`.

Direction: world_state.md  →  Kanka CE  (create or update, never delete).

`kanka_sync.py` renders Kanka → a ``## NPCs / ## Factions / ## Locations /
## World Events / ## Threads`` profile doc. CampaignGenerator's post-session
pipeline (``distill.py`` / ``synthesise_world_state.py``) emits that same
profile shape. This script parses that shape back into entities and reconciles
them with the live campaign:

  - match each entity by name (exact, case-insensitive) against what Kanka
    already holds for that type;
  - matched + content changed  → PATCH (update) that record;
  - matched + content equal     → skip (no write);
  - unmatched                   → POST (create) a new record.

Idempotent: re-running converges (a second run updates what the first created).
Kanka's own entity ids are the dedup key — there is no local manifest to drift.

One-way by design (the doc sets values, it does not unset them):
  - Removing a keyword flag (``deceased`` / ``destroyed`` / ``GM-private``) from
    a doc entity does NOT clear the corresponding field in Kanka — an absent
    flag means "no change", not "set False". To unset one, edit Kanka directly.
  - Name matching is case-insensitive, so a casing-only edit to a name in the
    doc is treated as "already matches" and never rewrites the canonical name.

Safety:
  - DRY RUN BY DEFAULT. It prints the create/update/skip plan and writes
    nothing. Pass --apply to commit.
  - Never deletes. Entities absent from the doc are left untouched in Kanka.
  - Skip-if-unchanged compares the doc body against the existing Kanka entry
    *normalized through the same `html_to_text`*, so a plain-text round-trip of
    a pull does not clobber richer HTML stored in Kanka.
  - Continue-on-error: one entity failing (e.g. a 422) does not abort the rest;
    failures are counted and reported. A re-run retries them.

Usage:
    export KANKA_TOKEN=<your-api-token>
    kanka_push --campaign 1 --input docs/world_state.md            # dry run
    kanka_push --campaign 1 --input docs/world_state.md --apply    # commit
"""

import argparse
import os
import re
import sys
from pathlib import Path

from . import kanka_sync
from .kanka_client import KankaClient

# Doc heading → Kanka entity type. Built from kanka_sync's forward mapping so
# the two stay in lock-step, plus the bare "Threads" heading some docs use.
HEADING_TO_TYPE = {heading: etype for etype, heading in kanka_sync.SECTIONS}
HEADING_TO_TYPE["Threads"] = "notes"

# Italic flags that carry boolean state rather than a free-text subtype.
KEYWORD_FLAGS = {
    "deceased": "is_dead",
    "destroyed": "is_destroyed",
    "GM-private": "is_private",
}
BOOL_FIELDS = set(KEYWORD_FLAGS.values())

# Fields Kanka accepts per entity type. Anything else parsed out of the doc is
# dropped before the write so a stray `date:` under NPCs can't 422 the request.
_COMMON = {"name", "entry", "type", "is_private"}
ALLOWED_FIELDS = {
    "characters": _COMMON | {"title", "is_dead"},
    "organisations": _COMMON,
    "locations": _COMMON | {"is_destroyed"},
    "events": _COMMON | {"date"},
    "notes": _COMMON,
}

# **Name**  optionally followed by  — _flag, flag_
_HEADER_RE = re.compile(r"\*\*(.+?)\*\*(?:\s*[—\-]\s*_(.+?)_)?\s*$")


# ── Parsing (pure; the inverse of kanka_sync.entity_block) ─────────────────────

def parse_entity_block(block: str) -> dict:
    """Parse one ``**Name** … prose`` profile back into an entity dict."""
    lines = block.lstrip("\n").splitlines()
    if not lines:
        return {}

    header = _HEADER_RE.match(lines[0].strip())
    ent: dict = {"name": header.group(1).strip() if header else lines[0].strip()}

    subtypes: list[str] = []
    if header and header.group(2):
        for flag in (f.strip() for f in header.group(2).split(",")):
            if flag in KEYWORD_FLAGS:
                ent[KEYWORD_FLAGS[flag]] = True
            elif flag:
                subtypes.append(flag)
    if subtypes:
        ent["type"] = ", ".join(subtypes)

    rest = lines[1:]
    meta: list[str] = []
    body_start = len(rest)
    for i, line in enumerate(rest):
        if line.strip() == "":
            body_start = i + 1
            break
        meta.append(line)

    for line in meta:
        s = line.strip()
        s = s[1:].strip() if s.startswith("-") else s
        if s.lower().startswith("in-world date:"):
            ent["date"] = s.split(":", 1)[1].strip()
        else:
            ent["title"] = s

    ent["entry"] = "\n".join(rest[body_start:]).strip()
    return ent


def parse_world_state(markdown: str) -> dict[str, list[dict]]:
    """Parse a world_state.md into ``{entity_type: [entity dict, ...]}``.

    Only recognised ``## Heading`` sections are captured; unknown headings (and
    everything before the first known one) are ignored.
    """
    result: dict[str, list[dict]] = {etype: [] for etype, _ in kanka_sync.SECTIONS}
    lines = markdown.splitlines()
    current_type: str | None = None

    def is_header(text: str) -> bool:
        # A new entity starts only on a full ``**Name**`` / ``**Name** — _flags_``
        # line — NOT on any line that merely opens with bold, so inline/leading
        # markdown bold inside a body paragraph never splits an entity.
        return bool(_HEADER_RE.match(text.strip()))

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("## "):
            current_type = HEADING_TO_TYPE.get(line[3:].strip())
            i += 1
            continue
        if current_type and is_header(line):
            block = [line]
            i += 1
            while i < n and not lines[i].startswith("## ") \
                    and not is_header(lines[i]):
                block.append(lines[i])
                i += 1
            result[current_type].append(parse_entity_block("\n".join(block)))
            continue
        i += 1

    return result


# ── Reconciliation ─────────────────────────────────────────────────────────────

def _unchanged(existing: dict, fields: dict) -> bool:
    """True when every doc field already matches the live Kanka record.

    `entry` is compared after running the stored HTML through `html_to_text`,
    so equivalent plain-text round-trips do not count as a change.
    """
    for key, value in fields.items():
        if key == "name":
            continue  # matched case-insensitively; case alone is not a change
        if key == "entry":
            if kanka_sync.html_to_text(existing.get("entry")).strip() != (value or "").strip():
                return False
        elif key in BOOL_FIELDS:
            if bool(existing.get(key)) != bool(value):
                return False
        else:
            cur = existing.get(key)
            if (cur or "").strip() != ("" if value is None else str(value)).strip():
                return False
    return True


def plan_changes(client, campaign_id: int,
                 parsed: dict[str, list[dict]]) -> list[dict]:
    """Diff parsed entities against live Kanka. Returns change list; no writes."""
    changes: list[dict] = []
    for entity_type, entities in parsed.items():
        if not entities:
            continue
        allowed = ALLOWED_FIELDS.get(entity_type, {"name", "entry"})
        index = {
            (e.get("name") or "").strip().casefold(): e
            for e in client.list_all(campaign_id, entity_type)
        }
        for ent in entities:
            fields = {k: v for k, v in ent.items() if k in allowed}
            match = index.get(ent["name"].strip().casefold())
            if match is None:
                changes.append({"action": "create", "entity_type": entity_type,
                                "name": ent["name"], "fields": fields})
            elif _unchanged(match, fields):
                changes.append({"action": "skip", "entity_type": entity_type,
                                "name": ent["name"], "record_id": match.get("id"),
                                "fields": fields})
            else:
                changes.append({"action": "update", "entity_type": entity_type,
                                "name": ent["name"], "record_id": match.get("id"),
                                "fields": fields})
    return changes


def apply_changes(client, campaign_id: int, changes: list[dict],
                  dry_run: bool = True) -> dict[str, int]:
    """Execute (or, when dry_run, just tally) the planned changes.

    Continue-on-error: a single failing entity is counted and reported; the
    rest of the batch still runs.
    """
    counts = {"create": 0, "update": 0, "skip": 0, "failed": 0}
    for ch in changes:
        action = ch["action"]
        if action == "skip":
            counts["skip"] += 1
            continue
        if dry_run:
            counts[action] += 1
            continue
        try:
            if action == "create":
                client.create(campaign_id, ch["entity_type"], **ch["fields"])
            else:
                client.update(campaign_id, ch["entity_type"],
                              ch["record_id"], **ch["fields"])
            counts[action] += 1
        except Exception as exc:  # noqa: BLE001
            counts["failed"] += 1
            print(f"  FAILED {action} {ch['entity_type']}/{ch['name']}: {exc}",
                  file=sys.stderr)
    return counts


# ── CLI ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Push a world_state.md grounding doc back into Kanka CE "
                    "(create or update; never delete). Dry run unless --apply."
    )
    parser.add_argument("--campaign", type=int, default=1,
                        help="Kanka campaign id (default: 1).")
    parser.add_argument("--input", "-i", required=True, metavar="FILE",
                        help="world_state.md to read (section-profile format).")
    parser.add_argument("--apply", action="store_true",
                        help="Commit changes. Without this flag the run is a "
                             "dry run and writes nothing.")
    parser.add_argument("--base-url", default=None,
                        help="Kanka base URL (default: $KANKA_BASE_URL or "
                             "http://localhost:8081).")
    args = parser.parse_args()

    token = os.environ.get("KANKA_TOKEN")
    if not token:
        print("Error: set KANKA_TOKEN env var to your Kanka API token.", file=sys.stderr)
        sys.exit(1)

    path = Path(args.input).expanduser().resolve()
    if not path.exists():
        print(f"Error: input not found: {path}", file=sys.stderr)
        sys.exit(1)

    base_url = args.base_url or os.environ.get("KANKA_BASE_URL", "http://localhost:8081")
    client = KankaClient(token, base_url=base_url)

    parsed = parse_world_state(path.read_text(encoding="utf-8"))
    changes = plan_changes(client, args.campaign, parsed)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[Kanka campaign {args.campaign}] {mode} — {path.name}", file=sys.stderr)
    for ch in changes:
        if ch["action"] == "skip":
            continue
        print(f"  {ch['action'].upper():6} {ch['entity_type']}/{ch['name']}", file=sys.stderr)

    counts = apply_changes(client, args.campaign, changes, dry_run=not args.apply)

    print(f"[{mode}] create={counts['create']} update={counts['update']} "
          f"skip={counts['skip']} failed={counts['failed']}", file=sys.stderr)
    if not args.apply:
        print("(dry run — pass --apply to commit)", file=sys.stderr)
    if counts["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
