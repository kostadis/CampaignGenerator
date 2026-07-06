#!/usr/bin/env python3
"""registry.py — CLI for the campaign entity registry (docs/entity_registry.yaml).

This is the write side of ``campaignlib.registry`` (the loader/validator
library). It has three subcommands:

  init    <campaign_dir>                 create an empty registry
  add     <campaign_dir> --name ... --type ...   add one entity, with a
                                          fuzzy typo guard against existing
                                          names/aliases before it lands
  project <campaign_dir>                 write aliases.json and
                                          entity_inventory.md projections
                                          consumed by existing pipelines
                                          (synthesise_world_state.load_aliases,
                                          spell_canon.inventory_tokens, ...)

No API calls are made anywhere in this module.
"""

from __future__ import annotations

import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

from campaignlib.registry import (
    Entity,
    Registry,
    _validate,
    find_registry,
    load_registry,
    save_registry,
)
from campaignlib.textproc import norm_subject

NEAR_MISS_THRESHOLD = 0.85


def _registry_path(campaign_dir: Path) -> Path:
    return Path(campaign_dir) / "docs" / "entity_registry.yaml"


# ── init ─────────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = _registry_path(campaign_dir)
    if path.exists():
        print(f"Error: registry already exists at {path}", file=sys.stderr)
        return 1

    path.parent.mkdir(parents=True, exist_ok=True)
    campaign = args.campaign or campaign_dir.resolve().name
    reg = Registry(version=1, campaign=campaign, entities=[])
    save_registry(reg, path)
    print(f"Wrote {path}")
    return 0


# ── add ──────────────────────────────────────────────────────────────────────

def _near_misses(new_name: str, reg: Registry, threshold: float) -> list[tuple[Entity, str, float]]:
    """[(entity, matched_string, ratio)] for every existing name/alias that is
    close to (but not an exact normalized match of) ``new_name``."""
    new_key = norm_subject(new_name)
    matches: list[tuple[Entity, str, float]] = []
    for e in reg.entities:
        for candidate in [e.name, *e.aliases]:
            cand_key = norm_subject(candidate)
            if cand_key == new_key:
                continue  # exact collision — handled separately
            ratio = SequenceMatcher(None, new_key, cand_key).ratio()
            if ratio >= threshold:
                matches.append((e, candidate, ratio))
    return matches


def _has_exact_collision(new_name: str, reg: Registry) -> Entity | None:
    new_key = norm_subject(new_name)
    for e in reg.entities:
        for candidate in [e.name, *e.aliases]:
            if norm_subject(candidate) == new_key:
                return e
    return None


def cmd_add(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(
            f"Error: no registry at {_registry_path(campaign_dir)} — "
            f"run `registry.py init {campaign_dir}` first",
            file=sys.stderr,
        )
        return 1

    reg = load_registry(path)

    collision = _has_exact_collision(args.name, reg)
    if collision is not None:
        print(
            f"Error: {args.name!r} normalizes the same as existing entity "
            f"{collision.name!r} — this would be an identity collision",
            file=sys.stderr,
        )
        return 1

    new_entity = Entity(
        name=args.name,
        type=args.type,
        aliases=list(args.aliases or []),
        provenance=args.provenance,
        source=args.source,
        scope=args.scope or "persistent",
        note=args.note,
    )

    near = _near_misses(args.name, reg, NEAR_MISS_THRESHOLD)

    if near and not args.yes:
        print(f"'{args.name}' looks similar to existing name(s):")
        for e, matched, ratio in near:
            print(f"    {matched!r} (entity {e.name!r}, similarity {ratio:.2f})")
        print(f'  [1] same entity — add "{args.name}" as an alias of {near[0][0].name}')
        print(f'  [2] different entity — add "{args.name}" as new')
        print("  [3] abort (likely a typo)")
        choice = input("Choice [1/2/3]: ").strip()

        if choice == "1":
            target = near[0][0]
            target.aliases.append(args.name)
            try:
                _validate(reg)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            save_registry(reg, path)
            print(f"Added {args.name!r} as an alias of {target.name!r}")
            return 0
        elif choice == "3":
            print("Aborted — nothing written.")
            return 1
        elif choice != "2":
            print(f"Error: unrecognized choice {choice!r} — aborting, nothing written", file=sys.stderr)
            return 1
        # choice == "2" falls through to the plain-add path below

    reg.entities.append(new_entity)
    try:
        _validate(reg)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    save_registry(reg, path)
    print(f"Added {args.name!r} ({args.type}) to {path}")
    return 0


# ── project ──────────────────────────────────────────────────────────────────

def cmd_project(args: argparse.Namespace) -> int:
    campaign_dir = Path(args.campaign_dir)
    path = find_registry(campaign_dir)
    if path is None:
        print(f"Error: no registry at {_registry_path(campaign_dir)}", file=sys.stderr)
        return 1

    reg = load_registry(path)
    docs_dir = path.parent

    aliases_path = docs_dir / "aliases.json"
    aliases_path.write_text(
        json.dumps(reg.canonical_to_aliases(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    inventory_path = docs_dir / "entity_inventory.md"
    header = "<!-- GENERATED from docs/entity_registry.yaml — do not hand-edit. Regenerate with: registry.py project -->\n\n"
    inventory_path.write_text(header + reg.inventory_markdown(), encoding="utf-8")

    print(f"Wrote {aliases_path} (do not hand-edit — generated from entity_registry.yaml)")
    print(f"Wrote {inventory_path}")
    return 0


# ── CLI wiring ───────────────────────────────────────────────────────────────

def main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="create an empty entity registry")
    pi.add_argument("campaign_dir")
    pi.add_argument("--campaign", default=None, help="campaign name (default: campaign_dir basename)")
    pi.set_defaults(func=cmd_init)

    pa = sub.add_parser("add", help="add one entity to the registry")
    pa.add_argument("campaign_dir")
    pa.add_argument("--name", required=True)
    pa.add_argument("--type", required=True)
    pa.add_argument("--aliases", nargs="+", default=None)
    pa.add_argument("--provenance", default=None)
    pa.add_argument("--source", default=None)
    pa.add_argument("--scope", default=None)
    pa.add_argument("--note", default=None)
    pa.add_argument("--yes", action="store_true", help="skip the near-miss prompt; add as new")
    pa.set_defaults(func=cmd_add)

    pp = sub.add_parser("project", help="write aliases.json + entity_inventory.md projections")
    pp.add_argument("campaign_dir")
    pp.set_defaults(func=cmd_project)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
