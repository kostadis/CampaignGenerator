#!/usr/bin/env python3
"""Stage 1 — enhance a gm-assist recap with VTT detail.

Single LLM call. The full VTT transcript goes into a cached system prefix;
the gm-assist body goes into the user message with the enrichment prompt.
The model returns one enriched markdown document that preserves the
gm-assist's section structure (Summary, Memorable Moments, Scenes, NPCs,
Locations, Items, Spells, etc.) but fills in details and verbatim moments
the recap missed.

Output is human-reviewable. It is the input to Stage 2 (scene_extract.py).

Usage:
  python enhance_summary.py session.vtt \\
      --gmassist gm-assist.md \\
      --output session-summary.md

Batch mode (50% off list price, no live streaming, results in minutes
typically — 24h SLA worst case):

  python enhance_summary.py ... --batch                 # block + poll until done
  python enhance_summary.py ... --batch --submit-only   # detach: write sidecar, exit
  python enhance_summary.py ... --batch --collect       # retrieve from sidecar
"""

import argparse
import sys
from pathlib import Path

from campaignlib import (
    build_batch_request,
    collect_batch,
    format_batch_progress,
    make_client,
    poll_batch,
    read_batch_sidecar,
    save_log,
    stream_api,
    submit_batch,
    utc_now_iso,
    write_batch_sidecar,
)
from vtt_summary import parse_vtt


ENHANCE_SYSTEM_PREFIX = """\
You are reading a Zoom transcript from a D&D session, anchored to a
gm-assist recap that gives the canonical structure of the session.

Your job: produce an ENRICHED version of the gm-assist by filling in
details and verbatim moments from the transcript that the recap missed.
The recap's section structure is the contract — preserve every section
header it uses (Summary, Memorable Moments, Scenes, NPCs, Locations,
Items, Spells, etc.) and produce a richer version of each.

GROUND RULES:
- Use the recap as the structural spec. Do not invent new top-level
  sections, do not drop existing ones, do not reorder scenes.
- Within each section, ENRICH from the transcript: add bullets for
  details the recap missed, expand thin scenes with what actually
  happened, lift verbatim quotes for Memorable Moments.
- Do NOT invent anything. Every added detail must be supportable from
  the transcript. If a recap claim has no transcript evidence, leave
  the recap claim alone — do not contradict it, do not delete it.
- Quote dialogue VERBATIM when promoting a line to Memorable Moments
  or a scene bullet. If a line is cut off in the transcript, copy what
  is there and mark it (truncated). Mark (paraphrase) only when no
  direct quote exists at all.
- Speaker label normalisation: Zoom labels are unreliable. Use the
  recap's attributions as ground truth. Map by voice context — players
  to their characters, DM lines stay attributed to the DM or the NPC
  being voiced. Strip parentheticals like "(Player)" or "(GM)".

OUTPUT:
- One complete markdown document. No preamble, no commentary about
  your process — just the enriched recap.
"""


ENHANCE_USER_TEMPLATE = """\
The full VTT transcript is in the cached system prefix above.

Here is the gm-assist recap. Produce an enriched version following
the rules in the system prompt — same section structure, richer
content drawn from the transcript.

---

{gmassist_body}
"""


SIDECAR_KIND = "enhance_summary"
CUSTOM_ID = "enhance"


def _sidecar_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".batch.json")


def _build_prompts(vtt_path: Path, gm_path: Path) -> tuple[str, str, str, str]:
    """Read inputs, build (system, user, dialogue, gmassist_body)."""
    raw = vtt_path.read_text(encoding="utf-8")
    print(f"\n[Parsing VTT | {len(raw):,} raw chars | {vtt_path.name}]")
    dialogue = parse_vtt(raw)
    if not dialogue.strip():
        print(f"Error: no dialogue found in VTT file: {vtt_path.name}", file=sys.stderr)
        sys.exit(1)
    print(f"  → {len(dialogue):,} chars of dialogue")

    gmassist_body = gm_path.read_text(encoding="utf-8")
    print(f"\n[gm-assist | {gm_path.name} | {len(gmassist_body):,} chars]")

    system = ENHANCE_SYSTEM_PREFIX + "\n---\n\nFULL VTT TRANSCRIPT:\n\n" + dialogue
    user = ENHANCE_USER_TEMPLATE.format(gmassist_body=gmassist_body)
    return system, user, dialogue, gmassist_body


def _write_output(out_path: Path, enriched: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(enriched.rstrip() + "\n", encoding="utf-8")
    print(f"\nWrote enriched summary to {out_path} ({len(enriched):,} chars)")


def _save_log(out_path: Path, vtt_path: Path, dialogue_len: int,
              gmassist_body: str, enriched: str, batch_id: str | None) -> None:
    log_dir = out_path.parent / "logs"
    sections = [
        ("VTT", f"{vtt_path.name} — {dialogue_len:,} chars dialogue"),
        ("gm-assist", gmassist_body),
        ("Enriched summary", enriched),
    ]
    if batch_id:
        sections.insert(0, ("Batch", f"id: {batch_id}"))
    log_file = save_log(str(log_dir), sections, stem="enhance_summary")
    print(f"Log saved to: {log_file}")


def _run_streaming(args, system: str, user: str, vtt_path: Path,
                   dialogue_len: int, gmassist_body: str, out_path: Path) -> None:
    client = make_client()
    print(f"\n[Enhancing summary | model: {args.model} | "
          f"system: {len(system):,} chars | user: {len(user):,} chars]")
    print("=" * 60)
    enriched = stream_api(
        client,
        system=system,
        user=user,
        model=args.model,
        max_tokens=args.max_tokens,
        cache_system=not args.no_cache,
        verbose=args.verbose,
    )
    print("=" * 60)
    _write_output(out_path, enriched)
    if not args.no_log:
        _save_log(out_path, vtt_path, dialogue_len, gmassist_body, enriched, None)


def _submit(args, system: str, user: str, out_path: Path) -> str:
    client = make_client()
    request = build_batch_request(
        custom_id=CUSTOM_ID,
        system=system,
        user=user,
        model=args.model,
        max_tokens=args.max_tokens,
        cache_system=not args.no_cache,
    )
    print(f"\n[Submitting batch | model: {args.model} | 1 request | "
          f"system: {len(system):,} chars | user: {len(user):,} chars]")
    batch_id = submit_batch(client, [request])
    sidecar = _sidecar_path(out_path)
    write_batch_sidecar(sidecar, {
        "kind": SIDECAR_KIND,
        "batch_id": batch_id,
        "model": args.model,
        "custom_ids": [CUSTOM_ID],
        "output": str(out_path),
        "submitted_at": utc_now_iso(),
    })
    print(f"  Batch ID: {batch_id}")
    print(f"  Sidecar:  {sidecar}")
    return batch_id


def _collect_and_write(args, batch_id: str, out_path: Path,
                       vtt_path: Path | None = None,
                       dialogue_len: int | None = None,
                       gmassist_body: str | None = None,
                       sidecar: Path | None = None) -> None:
    client = make_client()
    print(f"\n[Collecting batch {batch_id}...]")
    results = collect_batch(client, batch_id)
    record = results.get(CUSTOM_ID)
    if record is None:
        print(f"Error: batch {batch_id} returned no result for custom_id={CUSTOM_ID!r}",
              file=sys.stderr)
        sys.exit(1)
    if record["status"] != "succeeded":
        print(f"Error: batch request {CUSTOM_ID!r} did not succeed: "
              f"{record['status']} — {record.get('error')}", file=sys.stderr)
        sys.exit(1)
    enriched = record["text"] or ""
    _write_output(out_path, enriched)
    if record.get("usage"):
        print(f"  Usage: {record['usage']}")
    if sidecar and sidecar.exists():
        sidecar.unlink()
        print(f"  Removed sidecar: {sidecar}")
    if not args.no_log and vtt_path is not None and gmassist_body is not None:
        _save_log(out_path, vtt_path, dialogue_len or 0, gmassist_body, enriched, batch_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 1 — enrich a gm-assist recap with VTT detail (single cached call)."
    )
    parser.add_argument("input", metavar="FILE", nargs="?",
                        help="Zoom .vtt transcript file (optional with --batch --collect)")
    parser.add_argument("--gmassist", "-g", metavar="FILE",
                        help="gm-assist recap (the structural spec). "
                             "Optional with --batch --collect.")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to write the enriched session-summary.md "
                             "(typically alongside the gm-assist)")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku instead of Sonnet (~4x cheaper, faster)")
    parser.add_argument("--max-tokens", type=int, default=16384,
                        help="Max output tokens (default: 16384 — enriched recaps "
                             "can be large)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable prompt caching of the VTT prefix")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--verbose", action="store_true",
                        help="Print system + user prompts before the API call")
    parser.add_argument("--batch", action="store_true",
                        help="Use Anthropic's Message Batches API (50%% off list price). "
                             "Default mode submits, polls, retrieves, exits.")
    parser.add_argument("--submit-only", action="store_true",
                        help="With --batch: submit the batch, write a sidecar, exit. "
                             "Use --collect later to retrieve.")
    parser.add_argument("--collect", action="store_true",
                        help="With --batch: read the sidecar next to --output and "
                             "retrieve results.")
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

    out_path = Path(args.output).expanduser()

    # ── --batch --collect: no inputs needed, just read the sidecar ──
    if args.batch and args.collect:
        sidecar = _sidecar_path(out_path)
        payload = read_batch_sidecar(sidecar)
        if payload.get("kind") != SIDECAR_KIND:
            print(f"Error: sidecar at {sidecar} is for kind={payload.get('kind')!r}, "
                  f"expected {SIDECAR_KIND!r}", file=sys.stderr)
            sys.exit(1)
        client = make_client()
        batch_id = payload["batch_id"]
        print(f"[Polling batch {batch_id} (submitted {payload.get('submitted_at')})...]")
        poll_batch(client, batch_id, interval=args.poll_interval,
                   on_tick=lambda b: print("  " + format_batch_progress(b), flush=True))
        _collect_and_write(args, batch_id, out_path, sidecar=sidecar)
        return

    # ── Everything else: need VTT + gm-assist ──
    if not args.input:
        parser.error("input VTT file is required (omit only with --batch --collect)")
    if not args.gmassist:
        parser.error("--gmassist is required (omit only with --batch --collect)")

    vtt_path = Path(args.input).expanduser()
    if not vtt_path.exists():
        print(f"Error: VTT file not found: {vtt_path}", file=sys.stderr)
        sys.exit(1)
    gm_path = Path(args.gmassist).expanduser()
    if not gm_path.exists():
        print(f"Error: gm-assist file not found: {gm_path}", file=sys.stderr)
        sys.exit(1)

    system, user, dialogue, gmassist_body = _build_prompts(vtt_path, gm_path)

    if not args.batch:
        _run_streaming(args, system, user, vtt_path, len(dialogue), gmassist_body, out_path)
        return

    # ── --batch (block-and-poll) or --batch --submit-only ──
    batch_id = _submit(args, system, user, out_path)
    if args.submit_only:
        print("\nSubmit-only: exiting. Run with --batch --collect to retrieve later.")
        return

    client = make_client()
    print(f"\n[Polling batch {batch_id} every {args.poll_interval}s...]")
    poll_batch(client, batch_id, interval=args.poll_interval,
               on_tick=lambda b: print("  " + format_batch_progress(b), flush=True))
    sidecar = _sidecar_path(out_path)
    _collect_and_write(args, batch_id, out_path,
                       vtt_path=vtt_path, dialogue_len=len(dialogue),
                       gmassist_body=gmassist_body, sidecar=sidecar)


if __name__ == "__main__":
    main()
