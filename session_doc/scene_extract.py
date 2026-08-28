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

  # 50% off via the Message Batches API (no live streaming). Metered
  # backend only — it buys a list-price discount on N per-scene requests,
  # and relies on the metered backend's prompt caching to make the N-times-
  # repeated transcript cheap.
  scene_extract ... --batch                # block + poll until done
  scene_extract ... --batch --submit-only  # detach: write sidecar, exit
  scene_extract ... --batch --collect      # retrieve from sidecar

  # Collapse all pending scenes into ONE exchange (or a few, grouped
  # against --batch-max-tokens) instead of one call per scene (013). This
  # is a DIFFERENT axis from --batch above: it buys no discount, and
  # exists for backends with no prompt caching at all (the claude-code
  # subscription backend), where sending the transcript N times is the
  # real cost --batch's caching would otherwise hide. --batch and
  # --batch-scenes cannot be combined (see the refusal in main()).
  scene_extract ... --batch-scenes [--batch-max-tokens 32000]

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
    format_batch_progress,
    format_npc_roster,
    format_scene_output,
    load_agent_prompt,
    find_alias_registry,
    load_alias_map,
    load_players_config_arg,
    normalize_vtt_speakers,
    parse_gmassist_scenes,
    plan_scene_extraction,
    poll_batch,
    read_batch_sidecar,
    run_batch,
    run_batched_scene_extraction,
    run_scene_extraction,
    save_log,
    submit_batch,
    utc_now_iso,
    write_batch_sidecar,
)
from campaignlib.api.client import resolve_cli_model
from campaignlib.party_config import load_party_config_arg, require_from_config
from campaignlib.players_config import speaker_map_from_configs
from .io import parse_vtt


SCENE_EXTRACT_SYSTEM_PREFIX = load_agent_prompt("scene_extract")


SCENE_EXTRACT_USER_TEMPLATE = load_agent_prompt("scene_extract_user")


# Batched-mode counterparts (013). Separate files, not variants of the
# per-scene pair: the batched prompts add the sentinel protocol and restate
# every verbatim ground rule as applying WITHIN each scene, and the
# per-scene prompts must keep working byte-identically (FR-009).
SCENE_EXTRACT_BATCHED_SYSTEM_PREFIX = load_agent_prompt("scene_extract_batched")


SCENE_EXTRACT_BATCHED_USER_TEMPLATE = load_agent_prompt("scene_extract_batched_user")


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
                        help="party.md path. When set, VTT speaker labels are "
                             "rewritten to character names before the LLM sees "
                             "them. The map itself comes from --party-config "
                             "(#265), not from this file, so the two must be "
                             "passed together; --party alone is an error. "
                             "Omitting both skips speaker normalisation.")
    parser.add_argument("--party-config", metavar="FILE", default=None,
                        help="party.yaml (conventionally <campaign>/config/party.yaml). "
                             "REQUIRED: the player -> character map comes from each "
                             "character's D&D Beyond sheet frontmatter (issue #265) and "
                             "there is no party.md fallback — a sheet without frontmatter "
                             "is a hard error. Run sheet_frontmatter --apply to add it.")
    parser.add_argument("--players-config", metavar="FILE", default=None,
                        help="players.yaml (conventionally "
                             "<campaign>/config/players.yaml). REQUIRED with "
                             "--party: it is where every display name a "
                             "recording has used for a player is recorded, "
                             "including the game master's. Replaces the old "
                             "--gm-player, which could hold only one of a "
                             "person's several labels.")
    parser.add_argument("--model", default=None)
    add_backend_args(parser)
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku instead of Sonnet (~4x cheaper, faster)")
    parser.add_argument("--max-tokens", type=int, default=8192,
                        help="Max output tokens per scene (default: 8192)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable prompt caching of the VTT prefix")
    # ── Batched scene extraction (013) — a DIFFERENT axis from --batch ──
    # below (Message Batches, the 50%-discount metered-backend path). This
    # pair collapses the per-scene loop into one exchange (or a few, sized
    # against --batch-max-tokens) so the transcript is sent once instead
    # of once per scene — the saving --batch can't offer a backend with no
    # prompt caching (the claude-code subscription backend). Shared dest so
    # the editor can always pass an explicit flag either way (DM-19) and so
    # an unadorned CLI run is unaffected (default off, FR-009). Combining
    # this with --batch is refused below, before any input is read — see
    # the comment at that check for why silently ignoring it would be
    # worse than refusing it.
    parser.add_argument("--batch-scenes", dest="batch_scenes",
                        action="store_true", default=False,
                        help="Send all pending scenes in one exchange "
                             "(grouped against --batch-max-tokens if the "
                             "projected output would exceed it) instead of "
                             "one call per scene. NOT the same thing as "
                             "--batch: this buys no discount and targets "
                             "backends with no prompt caching, where the "
                             "repeated transcript — not the per-request "
                             "overhead --batch discounts — is the cost. "
                             "Cannot be combined with --batch. Default off.")
    parser.add_argument("--no-batch-scenes", dest="batch_scenes",
                        action="store_false",
                        help="Explicitly force the per-scene loop, "
                             "overriding a caller-supplied default. Exists "
                             "so a caller (the Session Doc Editor) can "
                             "always render one of --batch-scenes / "
                             "--no-batch-scenes explicitly rather than "
                             "relying on this CLI's own default.")
    parser.add_argument("--batch-max-tokens", type=int, default=32000,
                        help="Output ceiling for a --batch-scenes run "
                             "(default: 32000). This is a per-GROUP "
                             "ceiling that group sizing packs against, not "
                             "a per-scene budget — it does not touch "
                             "--max-tokens (default 8192), which keeps "
                             "governing the per-scene loop only, with or "
                             "without --batch-scenes (FR-017b). Accepted "
                             "but inert without --batch-scenes.")
    parser.add_argument("--force", action="store_true",
                        help="Re-extract even if per-scene files already exist. "
                             "Prior content is snapshotted to <file>.prev "
                             "(only when content differs) and any <file>.reviewed "
                             "marker is cleared. Default behavior skips existing "
                             "files so partial runs can be resumed.")
    parser.add_argument("--allow-speaker-mismatch", action="store_true",
                        help="Skip the pre-flight check that aborts when --party "
                             "is provided but no VTT lines match any recorded "
                             "display name. The check exists to "
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

    try:
        model_intent = resolve_cli_model(args, legacy_default=DEFAULT_MODEL)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    effective_model = model_intent.effective_model
    args.model = effective_model

    if (args.submit_only or args.collect) and not args.batch:
        parser.error("--submit-only and --collect require --batch")
    if args.submit_only and args.collect:
        parser.error("--submit-only and --collect are mutually exclusive")

    # ── Refuse --batch + --batch-scenes together (contracts/cli-surface.md
    # §2) BEFORE any work — before out_dir is even resolved, let alone the
    # VTT or summary read. This has to happen this early because `if not
    # args.batch:` (below) is the sole gate that reaches the batched-scenes
    # branch: without this refusal a combined run would silently take the
    # `--batch` (Message Batches) fork and --batch-scenes would just be
    # ignored — the GM would pay for the transcript once per scene, N
    # times, while believing they'd batched. A composed implementation was
    # considered and rejected (contracts/cli-surface.md §1): --batch only
    # runs on the metered backend, where cache_system already makes the
    # repeated transcript cheap, so there is nothing left for
    # --batch-scenes to save on that path.
    if args.batch and args.batch_scenes:
        print(
            "Error: --batch-scenes cannot be combined with --batch.\n"
            "  --batch submits per-scene requests to the Message Batches API (metered\n"
            "  backend only), where the repeated transcript is already cached.\n"
            "  --batch-scenes removes the repetition for backends that have no cache.\n"
            "  Pick one.",
            file=sys.stderr,
        )
        sys.exit(1)

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
        # Display name → label comes from the player entity (feature 009).
        # Every label a recording has used for a person is recorded there, the
        # game master's included, so there is no separate --gm-player to keep
        # in step and no per-invocation string that can hold only one of them.
        resolved_party_config = load_party_config_arg(args.party_config)
        players_config = load_players_config_arg(args.players_config)
        player_map = require_from_config(
            speaker_map_from_configs(players_config, resolved_party_config)
            if resolved_party_config else None,
            what="speaker map",
            party_config_arg=args.party_config,
        )
        if player_map:
            mapping_str = ", ".join(f"{p}→{c}" for p, c in sorted(player_map.items()))
            print(f"  Speaker map ({len(player_map)}): {mapping_str}")
        else:
            # Legitimate: every player is recorded but none carries a display
            # name, so no speaker can be attributed — Hillsfar's state. Distinct
            # from an unusable config, which require_from_config already exited
            # on because a character had nobody bound to it at all.
            print("  Warning: no player has a recorded display name, so no "
                  "speaker attribution is possible.", file=sys.stderr)
    if player_map:
        before = len(dialogue)
        dialogue = normalize_vtt_speakers(dialogue, player_map)
        # Quick visibility — count how many lines changed by re-running
        # the prefix check; cheaper than diffing.
        changed = sum(
            1 for line in dialogue.splitlines()
            if any(line.startswith(f"{c}:") for c in set(player_map.values()))
        )
        print(f"  Speaker labels rewritten: {changed} line(s); dialogue {before:,} → {len(dialogue):,} chars")
        if changed == 0 and not args.allow_speaker_mismatch:
            expected = sorted(player_map)
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
        npc_roster = format_npc_roster(alias_map)
        client = client_from_args(args)

        if args.batch_scenes:
            # ── Batched scene extraction (013): N scenes per exchange
            # instead of N calls. Same live (non-Message-Batches) branch as
            # the per-scene loop below — --batch was already refused above
            # — but a sibling engine call (`run_batched_scene_extraction`,
            # not `run_scene_extraction`) with the BATCHED prompt pair and
            # `--batch-max-tokens` (not `--max-tokens`, which stays the
            # per-scene loop's knob per FR-017b).
            print(f"\n[Batched scene extraction | {len(scenes)} scene(s) | "
                  f"model: {args.model} | ceiling: {args.batch_max_tokens:,} tok]")
            print("=" * 60)
            report = run_batched_scene_extraction(
                client,
                vtt_text=dialogue,
                scenes=scenes,
                extract_dir=out_dir,
                model=args.model,
                user_template=SCENE_EXTRACT_BATCHED_USER_TEMPLATE,
                system_prefix=SCENE_EXTRACT_BATCHED_SYSTEM_PREFIX,
                system_suffix=npc_roster,
                cache_vtt=not args.no_cache,
                max_tokens=args.batch_max_tokens,
                force=args.force,
            )
            print("=" * 60)

            # FR-018 / contracts/cli-surface.md §3 — the run-report tally.
            # `run_batched_scene_extraction` already narrated each group as
            # it ran (which scenes, saved/empty/missing, any group
            # failure); this is the summary the GM reads once at the end.
            print(f"\n  Scenes in summary:  {report['scenes_total']}")
            skip_note = ("  (skipped — pass --force to redo)"
                         if report["scenes_skipped"] else "")
            print(f"  Already extracted:  {report['scenes_skipped']}{skip_note}")
            print(f"  Requested:          {report['scenes_requested']}")
            if report["scenes_requested"]:
                groups_used = report["groups_used"]
                group_word = "group" if groups_used == 1 else "groups"
                # T052 / FR-006d — the split-forcing note rides on the
                # projection line itself, not a separate "Note:" tacked on
                # after Transcript sent — that's where the GM's eye already
                # is when they read the group count, and it names the lever
                # (--batch-max-tokens) right next to the number that would
                # change if they pulled it. FR-006d ties the note to "used
                # more than one" group; `report["ceiling_exceeded"]` is
                # ALSO true in group_scenes' singleton-overflow edge case
                # (one scene alone projects past the ceiling and still gets
                # its own group rather than being refused — DM-9), where
                # "for one call" would be nonsensical since it's already
                # one call, so that case gets its own wording.
                if groups_used > 1:
                    ceiling_note = ("  (projection exceeds ceiling; raise "
                                     "--batch-max-tokens for one call)")
                elif report["ceiling_exceeded"]:
                    ceiling_note = ("  (this scene's own projection exceeds "
                                     "the ceiling; raise --batch-max-tokens "
                                     "to give it room)")
                else:
                    ceiling_note = ""
                print(f"  Projected output:   {report['projected_tokens_total']:,.0f} tok"
                      f"  -> {groups_used} {group_word}{ceiling_note}")
                print(f"  Transcript sent:    {report['transcript_transmissions']}x  "
                      f"(per-scene mode would have sent "
                      f"{report['scenes_requested']}x)")
            if report["scenes_empty"]:
                print(f"  Empty (no moments): {len(report['scenes_empty'])}  "
                      f"({', '.join(report['scenes_empty'])})")

            # contracts/cli-surface.md §3: a complete run says where the
            # files landed; a partial run says how many of how many, since
            # "to <dir>" would bury the shortfall the missing-scenes block
            # below is about to name.
            if report["scenes_missing"]:
                print(f"\nWrote {report['scenes_written']} of "
                      f"{report['scenes_requested']} scene file(s).")
            else:
                print(f"\nWrote {report['scenes_written']} scene file(s) to {out_dir}")

            # The run log, same as the per-scene path below. Written BEFORE
            # the exit-code block: a partial run (exit 3/4) is exactly when
            # the GM wants a record of which scenes were requested, which
            # landed and which group failed, so `sys.exit` must not jump
            # over it. The batched extras (groups, transmissions, empties,
            # failures) are the whole reason this path exists and none of
            # them appear anywhere else after the terminal scrolls.
            if not args.no_log:
                log_sections = [
                    ("VTT", f"{vtt_path.name} — {len(dialogue):,} chars"),
                    ("Summary", summary_text),
                    ("Scenes", "\n".join(f"{i}. {s['name']}"
                                         for i, s in enumerate(scenes, 1))),
                    ("Batching", "\n".join([
                        f"ceiling: {args.batch_max_tokens:,} tok",
                        f"requested: {report['scenes_requested']}"
                        f"  skipped: {report['scenes_skipped']}"
                        f"  written: {report['scenes_written']}",
                        f"groups: {report['groups_used']}"
                        f"  transcript transmissions: "
                        f"{report['transcript_transmissions']}",
                        f"projected output: "
                        f"{report['projected_tokens_total']:,.0f} tok",
                    ])),
                    ("Empty (no moments)",
                     "\n".join(report["scenes_empty"]) or "(none)"),
                    ("Not extracted",
                     "\n".join(report["scenes_missing"]) or "(none)"),
                    ("Group failures", "\n".join(
                        f"group {f['group']}: {f['reason']} — {f['detail']}"
                        for f in report["group_failures"]) or "(none)"),
                    ("Output files", "\n".join(str(p) for p in report["saved"])),
                ]
                log_file = save_log(str(out_dir / "logs"), log_sections,
                                    stem="scene_extract_batched")
                print(f"Log saved to: {log_file}")

            # ── Exit codes (contracts/cli-surface.md §4) ──
            # `4` outranks `3`: a group failure means reconciliation itself
            # broke (duplicate/unknown/nested section indices in the
            # model's response — wire-protocol.md §4), and NOTHING from
            # that group was written, which is a different failure mode
            # from a scene that came back individually incomplete inside
            # an otherwise-successful group. Both leave whatever DID
            # succeed on disk, so neither is a `1`-style input refusal —
            # both are resumable: re-run without --force to request only
            # what's still missing.
            if report["group_failures"]:
                n = len(report["group_failures"])
                print(f"\n{n} group{'s' if n != 1 else ''} failed reconciliation "
                      f"— nothing from {'them' if n != 1 else 'it'} was written:",
                      file=sys.stderr)
                for f in report["group_failures"]:
                    print(f"  group {f['group']}: {f['reason']} — {f['detail']}",
                          file=sys.stderr)
                if report["scenes_missing"]:
                    print(f"\nNOT extracted: {', '.join(report['scenes_missing'])}",
                          file=sys.stderr)
                print("\nRe-run without --force to request only those.",
                      file=sys.stderr)
                sys.exit(4)

            if report["scenes_missing"]:
                print(f"\nNOT extracted: {', '.join(report['scenes_missing'])}",
                      file=sys.stderr)
                print("Re-run without --force to request only those.",
                      file=sys.stderr)
                sys.exit(3)

            return

        # ── Live streaming path, per-scene (unchanged behaviour) ──
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
