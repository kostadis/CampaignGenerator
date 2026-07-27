#!/usr/bin/env python3
"""Second-pass mechanical-residue scrubber for session_doc narrations.

Reads a narration file (or directory of them), runs each through a strict
filter prompt, and writes the cleaned output alongside the original with a
`.scrubbed.md` suffix. The original file is never modified.

Uses the same client plumbing as the rest of CampaignGenerator: when
DGX_ENDPOINT is set the call routes to the local vLLM endpoint
(Qwen-on-Spark by default); otherwise it falls back to the Anthropic API.

Usage:
    DGX_ENDPOINT=http://localhost:8000 \\
        scrub_mechanics summaries/20250226/narration/session_doc_scene_03*.md

    # Whole directory:
    scrub_mechanics summaries/20250226/narration/

    # Override model (otherwise uses DGX_MODEL env or library default):
    DGX_MODEL=Qwen2.5-32B-AWQ scrub_mechanics path/to/scene.md

The default prompt lives in the repo's config/scrub_mechanics_prompt.md
(REPO_ROOT, not this script's own directory — see the REPO_ROOT comment
below). Per-campaign overrides are resolved against the campaign root (via
$CG_CAMPAIGN_DIR, forwarded by the server; falls back to cwd for standalone
runs) — see resolve_prompt_path() for the search order.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# This file lives at session_doc/scrub_mechanics.py — one directory below
# the repo root, unlike the pipelines/<cluster>/ scripts (two levels down)
# that established this REPO_ROOT pattern — so a single .parent.parent gets
# back to the repo root that holds config/scrub_mechanics_prompt.md.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT_PATH = REPO_ROOT / "config" / "scrub_mechanics_prompt.md"
PER_CAMPAIGN_PROMPT_NAME = "scrub_mechanics_prompt.md"

from campaignlib import (  # noqa: E402
    DEFAULT_MODEL,
    add_backend_args,
    build_batch_request,
    client_from_args,
    run_batch,
    stream_api,
)
from campaignlib.util import atomic_write_text  # noqa: E402


def resolve_prompt_path() -> Path:
    """Resolve the scrub prompt, most specific first.

    Overrides are discovered relative to the **campaign root**, not the process
    cwd — the server's subprocess cwd is the launch directory, which need not be
    the campaign. The server forwards the campaign root as ``$CG_CAMPAIGN_DIR``
    and its config subdir as ``$CG_CONFIG_DIR`` (default ``"config"``). A
    standalone CLI run falls back to the current directory, so run scrub from
    within the campaign workspace.

      1. ``<campaign>/<config_dir>/session_doc_editor/scrub_mechanics_prompt.md``
         — the per-service override the web UI's session-doc editor owns.
      2. ``<campaign>/scrub_mechanics_prompt.md`` — legacy per-campaign override.
      3. the bundled in-tree default.
    """
    base = Path(os.environ.get("CG_CAMPAIGN_DIR") or Path.cwd())
    config_dir = os.environ.get("CG_CONFIG_DIR", "config")
    candidates = [
        base / config_dir / "session_doc_editor" / PER_CAMPAIGN_PROMPT_NAME,
        base / PER_CAMPAIGN_PROMPT_NAME,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return DEFAULT_PROMPT_PATH


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block_including_delimiters, body). Empty frontmatter ok."""
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text
    return text[: end + 5], text[end + 5 :]


_PROSE_RE = re.compile(r"<prose>\s*(.*?)\s*</prose>", re.DOTALL | re.IGNORECASE)
_SCAN_RE = re.compile(r"<scan>\s*(.*?)\s*</scan>", re.DOTALL | re.IGNORECASE)


def extract_blocks(raw: str) -> tuple[str | None, str]:
    """Return (scan_block_or_None, prose_text).

    Prompt v2 expects the model to emit <scan>...</scan><prose>...</prose>.
    If <prose> is present, return its inner text. Otherwise fall back to the
    full output (with a warning emitted by the caller).
    """
    scan_match = _SCAN_RE.search(raw)
    scan = scan_match.group(1).strip() if scan_match else None
    prose_match = _PROSE_RE.search(raw)
    if prose_match:
        return scan, prose_match.group(1).strip()
    return scan, raw.strip()


def finalize_scrub_response(path: Path, frontmatter: str, response: str,
                            dry_run: bool, save_scan: bool) -> Path | None:
    """Turn a model response into the written `.scrubbed.md` (+ optional
    `.scan.md`). Shared by the serial (`stream_api`) and batch (`run_batch`)
    paths so a successful batch item lands byte-identical to what the serial
    loop would have written for the same response text. Writes go through
    `campaignlib.util.atomic_write_text` (tmp + os.replace) rather than
    a raw `Path.write_text` so a killed process never leaves a torn file —
    the written bytes are unchanged either way.
    """
    scan, prose = extract_blocks(response)
    if scan is None and "<prose>" not in response.lower():
        print(f"[warn]  {path.name}: model did not emit <scan>/<prose> tags; "
              f"using full response", file=sys.stderr)

    out = frontmatter + prose.rstrip() + "\n"
    out_path = path.with_suffix(".scrubbed.md")
    if dry_run:
        print(f"[dry-run] would write {out_path}", file=sys.stderr)
        return out_path
    atomic_write_text(out_path, out)
    print(f"[wrote]  {out_path}", file=sys.stderr)

    if save_scan and scan is not None:
        scan_path = path.with_suffix(".scan.md")
        atomic_write_text(scan_path, scan.rstrip() + "\n")
        print(f"[wrote]  {scan_path}", file=sys.stderr)

    return out_path


def scrub_one(path: Path, client, system_prompt: str, model: str,
              max_tokens: int, dry_run: bool, save_scan: bool) -> Path | None:
    raw = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(raw)

    if not body.strip():
        print(f"[skip] {path.name}: empty body", file=sys.stderr)
        return None

    print(f"\n=== {path.name} ===", file=sys.stderr)
    response = stream_api(client, system_prompt, body, model,
                          max_tokens=max_tokens, silent=False)

    return finalize_scrub_response(path, frontmatter, response, dry_run, save_scan)


def collect_scrub_inputs(targets: list[Path]) -> list[tuple[Path, str, str]]:
    """Read every target, split frontmatter/body, skip empty bodies.

    Mirrors `scrub_one`'s empty-body skip check, computed BEFORE any batch
    request is built — an all-empty target set submits nothing.
    """
    eligible: list[tuple[Path, str, str]] = []
    for path in targets:
        raw = path.read_text(encoding="utf-8")
        frontmatter, body = split_frontmatter(raw)
        if not body.strip():
            print(f"[skip] {path.name}: empty body", file=sys.stderr)
            continue
        eligible.append((path, frontmatter, body))
    return eligible


def scrub_batch(targets: list[Path], client, system_prompt: str, model: str,
                max_tokens: int, dry_run: bool, save_scan: bool) -> bool:
    """Batch MAP: one grouped `run_batch` call across all target files
    instead of the serial per-file `stream_api` loop.

    `custom_id` is each file's stem (`collect_targets` only ever gathers
    `session_doc_scene_*.md` from a single directory, so stems are unique
    within one run). Successes are written via `finalize_scrub_response`
    (byte-identical to the serial path); a failed item prints
    `FAILED <custom_id>: <status> <error>` to stderr and writes nothing for
    that file — successful files stay on disk regardless.

    Returns True if any item failed (the caller exits non-zero in that case).
    """
    eligible = collect_scrub_inputs(targets)
    if not eligible:
        print("error: no non-empty target files to scrub", file=sys.stderr)
        return True

    requests = [
        build_batch_request(
            custom_id=path.stem,
            system=system_prompt,
            user=body,
            model=model,
            max_tokens=max_tokens,
        )
        for path, _frontmatter, body in eligible
    ]
    print(f"Submitting {len(requests)} file(s) as one batch...", file=sys.stderr)
    results = run_batch(client, requests, label="scrub")

    any_failed = False
    for path, frontmatter, _body in eligible:
        custom_id = path.stem
        record = results.get(custom_id)
        if record is None or record["status"] != "succeeded":
            status = record["status"] if record else "missing"
            error = record.get("error") if record else "no result returned"
            print(f"FAILED {custom_id}: {status} {error}", file=sys.stderr)
            any_failed = True
            continue
        finalize_scrub_response(path, frontmatter, record["text"], dry_run, save_scan)

    return any_failed


def collect_targets(arg: Path) -> list[Path]:
    if arg.is_file():
        return [arg]
    if arg.is_dir():
        return sorted(
            p for p in arg.glob("session_doc_scene_*.md")
            if not p.name.endswith(".scrubbed.md")
        )
    print(f"error: not a file or directory: {arg}", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path, help="Narration file or directory")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Model name override (else DGX_MODEL env / library default)")
    add_backend_args(parser)
    parser.add_argument("--max-tokens", type=int, default=16000,
                        help="Generation cap per file (default: 16000)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the model but do not write output files")
    parser.add_argument("--save-scan", action="store_true",
                        help="Also write the model's <scan> block to <file>.scan.md "
                             "(useful for debugging what the model flagged)")
    args = parser.parse_args()

    prompt_path = resolve_prompt_path()
    if not prompt_path.exists():
        print(f"error: prompt file missing: {prompt_path}", file=sys.stderr)
        return 2
    system_prompt = prompt_path.read_text(encoding="utf-8")

    targets = collect_targets(args.path)
    if not targets:
        print(f"error: no narration files found under {args.path}", file=sys.stderr)
        return 2

    client = client_from_args(args)
    model = args.model or DEFAULT_MODEL

    print(f"prompt:   {prompt_path}", file=sys.stderr)
    print(f"backend:  {args.backend}"
          + (f" ({args.endpoint})" if args.endpoint else ""), file=sys.stderr)
    print(f"model:    {model}", file=sys.stderr)
    print(f"targets:  {len(targets)} file(s)", file=sys.stderr)

    if args.batch:
        any_failed = scrub_batch(targets, client, system_prompt, model,
                                  max_tokens=args.max_tokens, dry_run=args.dry_run,
                                  save_scan=args.save_scan)
        if any_failed:
            return 1
    else:
        for path in targets:
            scrub_one(path, client, system_prompt, model,
                      max_tokens=args.max_tokens, dry_run=args.dry_run,
                      save_scan=args.save_scan)

    return 0


if __name__ == "__main__":
    sys.exit(main())
