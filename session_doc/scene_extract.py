#!/usr/bin/env python3
"""Stage 2 — scene-anchored VTT extraction.

Takes a Zoom .vtt transcript and an enriched session summary (Stage 1 output
from enhance_summary, post-human-review) and produces one rich
extraction file per scene named in the summary. The summary is the
human-verified scene structure — feeding it into extraction directly avoids
re-deriving structure from arbitrary chunk windows.

Each per-scene call sends the full VTT in the system prompt (cached as a
prefix) and a short user message naming one scene + its bullets. The model
returns the verbatim transcript moments belonging to that scene.

Usage:
  scene_extract session.vtt \\
      --summary session-summary.md \\
      --output-dir scene_extractions/ \\
      [--dossier-dir docs/npcs/]

  # 50% off via the Message Batches API (no live streaming)
  scene_extract ... --batch                # block + poll until done
  scene_extract ... --batch --submit-only  # detach: write sidecar, exit
  scene_extract ... --batch --collect      # retrieve from sidecar

Output:
  scene_extractions/01_<scene_slug>.md  ... 09_<scene_slug>.md
  Each file contains the scene summary verbatim + a verbatim-moments
  section sourced from the VTT.
"""

import argparse
import sys
from pathlib import Path

from campaignlib import (
    DEFAULT_MODEL,
    add_backend_args,
    build_batch_request,
    build_scene_extraction_system_prompt,
    client_from_args,
    collect_batch,
    extract_player_character_map,
    format_batch_progress,
    format_npc_roster,
    format_scene_output,
    load_agent_prompt,
    find_alias_registry,
    load_alias_map,
    normalize_vtt_speakers,
    parse_gmassist_scenes,
    plan_scene_extraction,
    poll_batch,
    read_batch_sidecar,
    run_batch,
    run_scene_extraction,
    save_log,
    submit_batch,
    utc_now_iso,
    write_batch_sidecar,
)
from .io import parse_vtt


SCENE_EXTRACT_SYSTEM_PREFIX = load_agent_prompt("scene_extract")


SCENE_EXTRACT_USER_TEMPLATE = load_agent_prompt("scene_extract_user")


SIDECAR_KIND = "scene_extract"
SIDECAR_NAME = ".batch.json"


def _sidecar_path(out_dir: Path) -> Path:
    return out_dir / SIDECAR_NAME


def _build_pending_requests(args, *, scenes, vtt_text, out_dir, alias_map):
    """Build per-scene Requests for not-yet-extracted scenes.

    Shared by the detached submit path (`_submit_pending`, sidecar-based) and
    the blocking `--batch` path (main(), one `run_batch` call) — the only
    thing that differs between them is what happens to the requests once
    built, not how they're built.

    With `args.force`, every scene is treated as pending (the on-disk file
    is overwritten on collect, with the prior version snapshotted to .prev).

    Returns `(requests, plan, system_prompt)`; `requests` is `[]` if every
    scene already exists on disk (nothing pending) and `--force` was not given.
    """
    # No input_normalizer: scene extraction emits VERBATIM quotes, so the VTT
    # must reach the model exactly as transcribed. The registry's aliases are
    # identity assertions ("these forms denote one entity"), not rewrite rules;
    # they reach the model as knowledge via the roster in `system_suffix`.
    system_suffix = format_npc_roster(alias_map)
    system_prompt = build_scene_extraction_system_prompt(
        vtt_text=vtt_text,
        system_prefix=SCENE_EXTRACT_SYSTEM_PREFIX,
        system_suffix=system_suffix,
    )

    plan = plan_scene_extraction(scenes=scenes, extract_dir=out_dir)
    pending = plan if args.force else [p for p in plan if not p["exists"]]

    requests = []
    for entry in pending:
        user_prompt = SCENE_EXTRACT_USER_TEMPLATE.format(
            name=entry["name"], body=entry["body"]
        )
        requests.append(build_batch_request(
            custom_id=entry["custom_id"],
            system=system_prompt,
            user=user_prompt,
            model=args.model,
            max_tokens=args.max_tokens,
            cache_system=not args.no_cache,
        ))
    return requests, plan, system_prompt


def _submit_pending(args, *, scenes, vtt_text, out_dir, alias_map):
    """Build per-scene Requests for not-yet-extracted scenes and submit one batch
    (detached mode: writes a sidecar in --output-dir/.batch.json for a later
    --collect). Unchanged behavior — grandfathered per FR-012.
    """
    requests, plan, system_prompt = _build_pending_requests(
        args, scenes=scenes, vtt_text=vtt_text, out_dir=out_dir, alias_map=alias_map,
    )
    if not requests:
        print("\nAll scenes already extracted on disk — nothing to submit.")
        return None, plan, system_prompt

    print(f"\n[Submitting batch | model: {args.model} | "
          f"{len(requests)} of {len(plan)} scene(s) | "
          f"system: {len(system_prompt):,} chars per request]")
    client = client_from_args(args)
    batch_id = submit_batch(client, requests)
    sidecar = _sidecar_path(out_dir)
    write_batch_sidecar(sidecar, {
        "kind": SIDECAR_KIND,
        "batch_id": batch_id,
        "model": args.model,
        "submitted_at": utc_now_iso(),
        "scenes": [
            {"i": p["i"], "name": p["name"], "slug": p["slug"],
             "custom_id": p["custom_id"], "path": str(p["path"])}
            for p in plan
        ],
        "pending_custom_ids": [r["custom_id"] for r in requests],
    })
    print(f"  Batch ID: {batch_id}")
    print(f"  Sidecar:  {sidecar}")
    return batch_id, plan, system_prompt


def _write_results(results: dict, *, out_dir: Path, plan_entries: list[dict],
                   sidecar: Path | None = None,
                   force: bool = False) -> tuple[list[Path], list[str]]:
    """Write per-scene files from an already-collected results dict via
    format_scene_output — the single formatter shared by every entry point
    (live streaming, detached --collect, blocking --batch) so output files
    stay byte-identical regardless of path.

    `plan_entries` is the full plan list (from plan_scene_extraction or the
    sidecar) so we can map custom_id back to the on-disk path and the
    verbatim scene body. Already-existing files are left alone unless
    `force=True`, in which case prior content is snapshotted to .prev (only
    when content differs) and any .reviewed sidecar is cleared.

    Returns `(saved, errors)` — `errors` is one `FAILED <custom_id>: ...` line
    per non-succeeded item (empty on full success). `sidecar`, if given, is
    removed only when there are zero errors (detached --collect's existing
    retry-on-sidecar contract).
    """
    from campaignlib import snapshot_scene_for_rerun

    saved: list[Path] = []
    errors: list[str] = []

    by_id = {p["custom_id"]: p for p in plan_entries}
    for custom_id, record in results.items():
        entry = by_id.get(custom_id)
        if entry is None:
            print(f"  Warning: result for unknown custom_id {custom_id!r} — ignoring",
                  file=sys.stderr)
            continue
        path = Path(entry["path"])
        if path.exists() and not force:
            print(f"  [{entry['i']}] {path.name}: already on disk — leaving untouched")
            saved.append(path)
            continue
        if record["status"] != "succeeded":
            errors.append(f"FAILED {custom_id}: {record['status']} {record.get('error')}")
            continue
        text = record["text"] or ""
        body_text = format_scene_output(entry["name"], entry.get("body", ""), text)
        path.parent.mkdir(parents=True, exist_ok=True)
        if snapshot_scene_for_rerun(path, body_text):
            path.write_text(body_text, encoding="utf-8")
            saved.append(path)
            usage = record.get("usage") or {}
            cache_read = usage.get("cache_read_input_tokens")
            suffix = f" | cache_read={cache_read}" if cache_read else ""
            print(f"  [{entry['i']}] Saved: {path.name}{suffix}")
        else:
            saved.append(path)
            print(f"  [{entry['i']}] Unchanged (no overwrite): {path.name}")

    if errors:
        print("\nErrors:", file=sys.stderr)
        for line in errors:
            print(f"  {line}", file=sys.stderr)
        if sidecar:
            print("\nRe-run with --batch --collect (sidecar preserved) to resubmit failures.",
                  file=sys.stderr)
        else:
            print("\nRe-run with --batch to retry the missing scene(s) "
                  "(existing files are left untouched).", file=sys.stderr)

    if not errors and sidecar and sidecar.exists():
        sidecar.unlink()
        print(f"  Removed sidecar: {sidecar}")

    return saved, errors


def _collect_and_write(client, *, batch_id: str, out_dir: Path,
                       plan_entries: list[dict],
                       sidecar: Path | None = None,
                       force: bool = False) -> list[Path]:
    """Retrieve batch results (collect_batch against `batch_id`) and write
    per-scene files. Detached --collect's entry point — grandfathered per
    FR-012, except the exit code: a collect with any failed scene now exits
    non-zero (FR-008/T027) so a wrapping script can't mistake a partial
    collect for a complete one. Successes are written first; the sidecar
    stays on disk so a re-run --collect can retry the failures.
    """
    print(f"\n[Collecting batch {batch_id}...]")
    results = collect_batch(client, batch_id)
    saved, errors = _write_results(
        results, out_dir=out_dir, plan_entries=plan_entries,
        sidecar=sidecar, force=force,
    )
    if errors:
        print(f"{len(errors)} scene(s) failed; successes are on disk and the "
              f"sidecar is kept for a retry.", file=sys.stderr)
        sys.exit(1)
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scene-anchored VTT extraction (replaces blind chunked extraction)."
    )
    parser.add_argument("input", metavar="FILE", nargs="?",
                        help="Zoom .vtt transcript file (optional with --batch --collect)")
    parser.add_argument("--summary", "-s", metavar="FILE",
                        dest="summary",
                        help="Enriched session summary from Stage 1 / "
                             "enhance_summary (must contain a ## Scenes section). "
                             "Optional with --batch --collect.")
    parser.add_argument("--output-dir", "-o", required=True, metavar="DIR",
                        help="Where to write per-scene extraction files")
    parser.add_argument("--dossier-dir", metavar="DIR", default=None,
                        help="Directory of per-NPC dossier files (built by "
                             "planning --build-dossiers). The canonical NPC "
                             "roster is appended to the system prompt so the "
                             "model knows which names denote the same entity. "
                             "The VTT itself is never rewritten — scene "
                             "extraction emits verbatim quotes.")
    parser.add_argument("--party", metavar="FILE", default=None,
                        help="party.md path. When set, player → character "
                             "mappings are parsed from the `**Class, Player: "
                             "Name**` lines and used to rewrite speaker "
                             "labels in the VTT before the LLM sees it.")
    parser.add_argument("--gm-player", metavar="NAME", default=None,
                        help="Display name the GM appears under in the VTT "
                             "(e.g. 'Kostadis'). Rewritten to 'GM:' before "
                             "extraction. Without this flag the GM's lines "
                             "stay under their player name.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    add_backend_args(parser)
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku instead of Sonnet (~4x cheaper, faster)")
    parser.add_argument("--max-tokens", type=int, default=8192,
                        help="Max output tokens per scene (default: 8192)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable prompt caching of the VTT prefix")
    parser.add_argument("--force", action="store_true",
                        help="Re-extract even if per-scene files already exist. "
                             "Prior content is snapshotted to <file>.prev "
                             "(only when content differs) and any <file>.reviewed "
                             "marker is cleared. Default behavior skips existing "
                             "files so partial runs can be resumed.")
    parser.add_argument("--allow-speaker-mismatch", action="store_true",
                        help="Skip the pre-flight check that aborts when --party "
                             "or --gm-player is provided but no VTT lines match "
                             "any of those display names. The check exists to "
                             "catch wrong-VTT mistakes before spending money on "
                             "extraction; only override if you know the VTT uses "
                             "unrecognised display names.")
    parser.add_argument("--no-log", action="store_true")
    # --batch itself now comes from add_backend_args (spec 004); per-scene
    # calls are submitted as one batch and share the cached VTT prefix.
    parser.add_argument("--submit-only", action="store_true",
                        help="With --batch: submit the batch, write a sidecar in "
                             "--output-dir/.batch.json, exit.")
    parser.add_argument("--collect", action="store_true",
                        help="With --batch: read the sidecar in --output-dir/.batch.json "
                             "and retrieve results.")
    parser.add_argument("--poll-interval", type=int, default=10,
                        help="Seconds between batch poll requests (default: 10)")
    args = parser.parse_args()

    if args.fast:
        args.model = "claude-haiku-4-5-20251001"
        print("  [fast mode: claude-haiku-4-5-20251001]")

    if (args.submit_only or args.collect) and not args.batch:
        parser.error("--submit-only and --collect require --batch")
    if args.submit_only and args.collect:
        parser.error("--submit-only and --collect are mutually exclusive")

    out_dir = Path(args.output_dir).expanduser()

    # ── --batch --collect: read sidecar, no inputs needed ──
    if args.batch and args.collect:
        sidecar = _sidecar_path(out_dir)
        payload = read_batch_sidecar(sidecar)
        if payload.get("kind") != SIDECAR_KIND:
            print(f"Error: sidecar at {sidecar} is for kind={payload.get('kind')!r}, "
                  f"expected {SIDECAR_KIND!r}", file=sys.stderr)
            sys.exit(1)
        client = client_from_args(args)
        batch_id = payload["batch_id"]
        plan_entries = payload.get("scenes", [])
        # plan_scene_extraction returned dicts with body — sidecar entries
        # don't include body, so re-load it from the summary if available.
        if args.summary:
            summary_path = Path(args.summary).expanduser()
            if summary_path.exists():
                scenes_now = parse_gmassist_scenes(
                    summary_path.read_text(encoding="utf-8"))
                body_by_name = {s["name"]: s.get("body", "").strip() for s in scenes_now}
                for e in plan_entries:
                    e["body"] = body_by_name.get(e["name"], "")
        else:
            for e in plan_entries:
                e.setdefault("body", "")
        print(f"[Polling batch {batch_id} (submitted {payload.get('submitted_at')})...]")
        poll_batch(client, batch_id, interval=args.poll_interval,
                   on_tick=lambda b: print("  " + format_batch_progress(b), flush=True))
        saved = _collect_and_write(client, batch_id=batch_id, out_dir=out_dir,
                                   plan_entries=plan_entries, sidecar=sidecar,
                                   force=args.force)
        print(f"\nWrote {len(saved)} scene file(s) to {out_dir}")
        return

    # ── Everything else: need VTT + summary ──
    if not args.input:
        parser.error("input VTT file is required (omit only with --batch --collect)")
    if not args.summary:
        parser.error("--summary is required (omit only with --batch --collect)")

    vtt_path = Path(args.input).expanduser()
    if not vtt_path.exists():
        print(f"Error: VTT file not found: {vtt_path}", file=sys.stderr)
        sys.exit(1)
    raw = vtt_path.read_text(encoding="utf-8")
    print(f"\n[Parsing VTT | {len(raw):,} raw chars | {vtt_path.name}]")
    dialogue = parse_vtt(raw)
    if not dialogue.strip():
        print(f"Error: no dialogue found in VTT file: {vtt_path.name}", file=sys.stderr)
        sys.exit(1)
    print(f"  → {len(dialogue):,} chars of dialogue")

    # ── Player → character speaker normalisation ────────────────────────────
    # The LLM's existing "Character (Player) → strip the parenthetical"
    # rule only fires when the VTT actually carries the parenthetical
    # disambiguation. Zoom captions emit raw display names. Rewrite them
    # deterministically here so who-said-what is locked in by the
    # human-curated party.md, not inferred from the transcript.
    player_map: dict[str, str] = {}
    if args.party:
        party_path = Path(args.party).expanduser()
        if not party_path.exists():
            print(f"Error: party file not found: {party_path}", file=sys.stderr)
            sys.exit(1)
        player_map = extract_player_character_map(party_path.read_text(encoding="utf-8"))
        if player_map:
            mapping_str = ", ".join(f"{p}→{c}" for p, c in sorted(player_map.items()))
            print(f"  Player → character map ({len(player_map)}): {mapping_str}")
        else:
            print(f"  Warning: --party {party_path.name} produced an empty player map "
                  f"(no `**..., Player: ...**` lines found)", file=sys.stderr)
    if args.gm_player:
        print(f"  GM player → GM: {args.gm_player}")
    if player_map or args.gm_player:
        before = len(dialogue)
        dialogue = normalize_vtt_speakers(dialogue, player_map, args.gm_player)
        # Quick visibility — count how many lines changed by re-running
        # the prefix check; cheaper than diffing.
        changed = sum(
            1 for line in dialogue.splitlines()
            if any(line.startswith(f"{c}:") for c in set(player_map.values()) | {"GM"})
        )
        print(f"  Speaker labels rewritten: {changed} line(s); dialogue {before:,} → {len(dialogue):,} chars")
        if changed == 0 and not args.allow_speaker_mismatch:
            expected = sorted(set(player_map.keys()) | (
                {args.gm_player} if args.gm_player else set()
            ))
            print(
                f"\nError: speaker-mismatch pre-flight failed.\n"
                f"  VTT:           {vtt_path}\n"
                f"  Expected one or more of these display names to appear as a "
                f"speaker:\n    {', '.join(expected)}\n"
                f"  Found:         0 matching lines.\n"
                f"\n"
                f"This almost always means the wrong VTT is in this directory "
                f"(a non-D&D recording, a different session, or a stale file). "
                f"Aborting before submitting a batch — that would burn API tokens "
                f"producing 'no matching moments' for every scene.\n"
                f"\n"
                f"Fix: replace the VTT with the correct recording and re-run. "
                f"To bypass this check (rare — only if the VTT genuinely uses "
                f"different display names), pass --allow-speaker-mismatch.",
                file=sys.stderr,
            )
            sys.exit(2)

    summary_path = Path(args.summary).expanduser()
    if not summary_path.exists():
        print(f"Error: summary file not found: {summary_path}", file=sys.stderr)
        sys.exit(1)
    summary_text = summary_path.read_text(encoding="utf-8")

    scenes = parse_gmassist_scenes(summary_text)
    if not scenes:
        print(f"Error: no '## Scenes' section (with ### scene headings) found in {summary_path}.\n"
              f"Scene-anchored extraction requires human-verified scene structure — "
              f"run Stage 1 (enhance_summary) to produce it, then review the scene "
              f"headings before re-running.",
              file=sys.stderr)
        sys.exit(1)
    print(f"\n[summary | {summary_path.name}: {len(scenes)} scene(s)]")
    for i, s in enumerate(scenes, 1):
        print(f"  {i}. {s['name']}")

    alias_map = load_alias_map(args.dossier_dir, registry_path=find_alias_registry(Path.cwd()))
    if alias_map:
        print(f"  Alias map: {len(alias_map)} NPC(s) from {args.dossier_dir}")

    if not args.batch:
        # ── Live streaming path (unchanged behaviour) ──
        npc_roster = format_npc_roster(alias_map)
        client = client_from_args(args)
        print(f"\n[Scene extraction | {len(scenes)} scene(s) | model: {args.model}]")
        print("=" * 60)
        saved = run_scene_extraction(
            client,
            vtt_text=dialogue,
            scenes=scenes,
            extract_dir=out_dir,
            model=args.model,
            extraction_instruction=SCENE_EXTRACT_USER_TEMPLATE,
            system_prefix=SCENE_EXTRACT_SYSTEM_PREFIX,
            system_suffix=npc_roster,
            cache_vtt=not args.no_cache,
            max_tokens=args.max_tokens,
            force=args.force,
        )
        print("=" * 60)
        print(f"\nWrote {len(saved)} scene file(s) to {out_dir}")

        if not args.no_log:
            log_sections = [
                ("VTT", f"{vtt_path.name} — {len(dialogue):,} chars"),
                ("Summary", summary_text),
                ("Scenes", "\n".join(f"{i}. {s['name']}" for i, s in enumerate(scenes, 1))),
                ("Output files", "\n".join(str(p) for p in saved)),
            ]
            log_file = save_log(str(out_dir / "logs"), log_sections, stem="scene_extract")
            print(f"Log saved to: {log_file}")
        return

    # ── --batch --submit-only: detached, sidecar-based (unchanged; FR-012) ──
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.submit_only:
        batch_id, _plan_entries, _system_prompt = _submit_pending(
            args, scenes=scenes, vtt_text=dialogue, out_dir=out_dir, alias_map=alias_map,
        )
        if batch_id is None:
            # Nothing to do — every scene already on disk.
            return
        print("\nSubmit-only: exiting. Run with --batch --collect to retrieve later.")
        return

    # ── Plain --batch: submit + poll + collect in one run_batch call ──
    requests, plan_entries, _system_prompt = _build_pending_requests(
        args, scenes=scenes, vtt_text=dialogue, out_dir=out_dir, alias_map=alias_map,
    )
    if not requests:
        print("\nAll scenes already extracted on disk — nothing to submit.")
        return

    client = client_from_args(args)
    print(f"\n[Batch | model: {args.model} | {len(requests)} of {len(plan_entries)} scene(s)]")
    results = run_batch(client, requests, label="scene", poll_interval=args.poll_interval)
    saved, errors = _write_results(
        results, out_dir=out_dir, plan_entries=plan_entries, force=args.force,
    )
    print(f"\nWrote {len(saved)} scene file(s) to {out_dir}")

    if not args.no_log:
        log_sections = [
            ("Batch", "submit-and-collect (blocking)"),
            ("VTT", f"{vtt_path.name} — {len(dialogue):,} chars"),
            ("Summary", summary_text),
            ("Scenes", "\n".join(f"{i}. {s['name']}" for i, s in enumerate(scenes, 1))),
            ("Output files", "\n".join(str(p) for p in saved)),
        ]
        log_file = save_log(str(out_dir / "logs"), log_sections, stem="scene_extract")
        print(f"Log saved to: {log_file}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
