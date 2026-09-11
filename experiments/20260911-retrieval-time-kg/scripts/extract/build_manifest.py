#!/usr/bin/env python3
"""Classify the obelisk corpus into provenance tiers for a tagged re-ingest."""
import json
from pathlib import Path

OB = Path("/home/kostadis/obelisk/obelisk")
SCENES = Path("/home/kostadis/cognee-local/scene_docs")
FACTIONS = Path("/mnt/g/My Drive/DriveThru/Dungeon Masters Guild/Factions of Phandalin/"
                "3627966-Factions_of_Phandalin_4.5.1.json")
EXCLUDE = {OB / "docs" / "background" / "obelisk.md"}   # dropped by request

tiers = {t: [] for t in
         ("play_record", "module_canon", "curated_state", "prep_plan", "superseded")}

# what happened at the table
for pat in ("session_summary.md", "session-summary.md"):
    tiers["play_record"] += [str(p) for p in (OB / "summaries").rglob(pat)]
tiers["play_record"] += [str(p) for p in SCENES.glob("*.md")]
tiers["play_record"] += [str(p) for p in (OB / "docs" / "chapters").glob("*.md")]

# the published adventure -- includes events not yet reached
tiers["module_canon"] += [str(p) for p in (OB / "docs" / "background").glob("*.md")
                          if p not in EXCLUDE]
tiers["module_canon"].append(str(OB / "docs" / "entity_inventory.md"))
if FACTIONS.exists():
    tiers["module_canon"].append(str(FACTIONS))

# reviewed current-state judgments
tiers["curated_state"] += [str(p) for p in (OB / "docs").glob("*.md")
                           if p.name != "entity_inventory.md"]
tiers["curated_state"] += [str(p) for p in (OB / "docs/ensemble/merged_dossiers").glob("*.md")]
tiers["curated_state"] += [str(OB / "docs/ensemble" / n) for n in ("known_names.md", "threads.md")
                           if (OB / "docs/ensemble" / n).exists()]

# GM intentions -- plans, not events
tiers["prep_plan"] += [str(p) for p in (OB / "notes/session_prep").glob("*.md")]
tiers["curated_state"] += [str(p) for p in (OB / "notes").glob("*.md")]
tiers["curated_state"] += [str(p) for p in (OB / "notes/handouts").glob("*.md")]

# older generations kept but tagged, so they can be filtered out of default queries
tiers["superseded"] += [str(p) for p in (OB / "docs/ensemble").glob("*draft*.md")]
tiers["superseded"] += [str(p) for p in (OB / "docs/ensemble/state_dossiers").glob("*.md")]

# dedupe, keeping the first tier a file lands in
seen, clean = set(), {}
for t in ("play_record", "module_canon", "curated_state", "prep_plan", "superseded"):
    clean[t] = sorted({f for f in tiers[t] if f not in seen and not seen.add(f)})

out = Path("/home/kostadis/cognee-local/tier_manifest.json")
out.write_text(json.dumps(clean, indent=2))
tot = 0
for t, fs in clean.items():
    kb = sum(Path(f).stat().st_size for f in fs) / 1024
    tot += len(fs)
    print(f"  {t:<15} {len(fs):>4} files  {kb:>9.1f} KB")
print(f"  {'TOTAL':<15} {tot:>4} files  -> {out}")
