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
        python scrub_mechanics.py summaries/20250226/narration/session_doc_scene_03*.md

    # Whole directory:
    python scrub_mechanics.py summaries/20250226/narration/

    # Override model (otherwise uses DGX_MODEL env or library default):
    DGX_MODEL=Qwen2.5-32B-AWQ python scrub_mechanics.py path/to/scene.md

The default prompt lives in config/scrub_mechanics_prompt.md next to this
script. A per-campaign override at <cwd>/scrub_mechanics_prompt.md takes
precedence when present.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

DEFAULT_PROMPT_PATH = Path(__file__).resolve().parent / "config" / "scrub_mechanics_prompt.md"
PER_CAMPAIGN_PROMPT_NAME = "scrub_mechanics_prompt.md"

from campaignlib import make_client, stream_api  # noqa: E402


def resolve_prompt_path() -> Path:
    """Per-campaign override beats the in-tree default.

    The subprocess runs with cwd set to the campaign directory, so a
    `scrub_mechanics_prompt.md` in the workspace root overrides the default
    without any flag. Falls back to the bundled prompt when none is present.
    """
    cwd_override = Path.cwd() / PER_CAMPAIGN_PROMPT_NAME
    if cwd_override.is_file():
        return cwd_override
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

    scan, prose = extract_blocks(response)
    if scan is None and "<prose>" not in response.lower():
        print(f"[warn]  {path.name}: model did not emit <scan>/<prose> tags; "
              f"using full response", file=sys.stderr)

    out = frontmatter + prose.rstrip() + "\n"
    out_path = path.with_suffix(".scrubbed.md")
    if dry_run:
        print(f"[dry-run] would write {out_path}", file=sys.stderr)
        return out_path
    out_path.write_text(out, encoding="utf-8")
    print(f"[wrote]  {out_path}", file=sys.stderr)

    if save_scan and scan is not None:
        scan_path = path.with_suffix(".scan.md")
        scan_path.write_text(scan.rstrip() + "\n", encoding="utf-8")
        print(f"[wrote]  {scan_path}", file=sys.stderr)

    return out_path


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
    parser.add_argument("--model", default=None,
                        help="Model name override (else DGX_MODEL env / library default)")
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

    endpoint = os.environ.get("DGX_ENDPOINT")
    client = make_client(endpoint=endpoint, model_override=args.model)
    model = args.model or os.environ.get("DGX_MODEL") or "claude-sonnet-4-6"

    print(f"prompt:   {prompt_path}", file=sys.stderr)
    print(f"endpoint: {endpoint or 'anthropic-api'}", file=sys.stderr)
    print(f"model:    {model}", file=sys.stderr)
    print(f"targets:  {len(targets)} file(s)", file=sys.stderr)

    for path in targets:
        scrub_one(path, client, system_prompt, model,
                  max_tokens=args.max_tokens, dry_run=args.dry_run,
                  save_scan=args.save_scan)

    return 0


if __name__ == "__main__":
    sys.exit(main())
