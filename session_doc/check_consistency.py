#!/usr/bin/env python3
"""Run a consistency check on any session document against campaign context.

Loads campaign_state and world_state from config automatically; pass additional
files (e.g. party.md) via --context.

Usage:
    check_consistency session-doc.md
    check_consistency enhanced_sections.md --context docs/party.md
    check_consistency session-doc.md --output consistency_report.md
"""

import argparse
import os
import sys
from pathlib import Path

from campaignlib import (
    CodexCliError,
    DEFAULT_MODEL,
    add_backend_args,
    assemble_docs,
    canonical_context_section,
    client_from_args,
    find_default_config,
    load_agent_prompt,
    load_config,
    run_single_batch,
    stream_api,
)
from campaignlib.api.client import resolve_cli_model

# This file lives at session_doc/check_consistency.py; find_default_config()'s
# script-dir fallback expects to sit next to config/ (the repo root), which
# is no longer this file's own directory since the move — anchor it at
# REPO_ROOT explicitly instead (same fix as pipelines/session_prep/prep.py,
# one .parent shorter since session_doc/ is only one level below repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_CONFIG_DOCS = ["campaign_state", "world_state"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consistency-check a session document against campaign context."
    )
    parser.add_argument("document", help="Path to the document to check")
    parser.add_argument(
        "--config",
        default=find_default_config(str(REPO_ROOT / "check_consistency.py")),
        help="Path to config.yaml (default: CWD or script-dir config/config.yaml)",
    )
    parser.add_argument(
        "--context",
        nargs="+",
        action="extend",
        metavar="FILE",
        help="Additional context files (e.g. docs/party.md docs/mechanics.md). "
             "Repeatable: flags accumulate rather than overwrite.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model to use (existing backends default to the CampaignGenerator "
             "Claude model; codex-cli uses CG_CODEX_MODEL or the Codex subscription default)",
    )
    add_backend_args(parser)
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Save report to this file (prints to stdout regardless)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    try:
        model_intent = resolve_cli_model(args, legacy_default=DEFAULT_MODEL)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    effective_model = model_intent.effective_model
    args.model = effective_model

    doc_path = Path(args.document).expanduser()
    if not doc_path.exists():
        print(f"Error: document not found: {doc_path}", file=sys.stderr)
        sys.exit(1)
    document = doc_path.read_text(encoding="utf-8").strip()

    config, base_dir = load_config(args.config)
    available_labels = {d["label"] for d in config.get("documents", []) if d.get("path")}

    context_parts: list[str] = []

    canon = canonical_context_section(base_dir)
    if canon:
        context_parts.append(canon)
    else:
        print(f"  Note: no entity_registry.yaml found under {base_dir}, "
              f"skipping canon section.", file=sys.stderr)

    for label in _DEFAULT_CONFIG_DOCS:
        if label in available_labels:
            text = assemble_docs(config, [label], base_dir)
            if text.strip():
                context_parts.append(text)
        else:
            print(f"  Note: '{label}' not in config, skipping.", file=sys.stderr)

    if args.context:
        for ctx in args.context:
            p = Path(ctx).expanduser()
            if p.exists():
                context_parts.append(f"## {p.name}\n\n{p.read_text(encoding='utf-8').strip()}")
            else:
                print(f"  Warning: context file not found: {p}", file=sys.stderr)

    if not context_parts:
        print("Error: no context documents found. Check config or pass --context files.", file=sys.stderr)
        sys.exit(1)

    print(f"Document : {doc_path.name} ({len(document):,} chars)")
    print(f"Context  : {len(context_parts)} document(s)")
    model_display = (
        args.model
        if args.model is not None
        else "Codex subscription default"
    )
    print(f"Model    : {model_display}")
    print("=" * 60)

    prompt = "\n\n---\n\n".join([
        f"## Document to Check\n\n{document}",
        "## Campaign Context\n\n" + "\n\n---\n\n".join(context_parts),
    ])

    try:
        client = client_from_args(args)
    except CodexCliError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    system = load_agent_prompt("session_doc/consistency")
    max_tokens = int(os.environ.get("CG_CONSISTENCY_MAX_TOKENS", "32000"))
    if args.batch:
        try:
            report = run_single_batch(client, system=system, user=prompt,
                                      model=args.model, max_tokens=max_tokens,
                                      cache_system=False)
        except RuntimeError as e:
            print(f"Error: batch item failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            report = stream_api(
                client, system, prompt, args.model,
                max_tokens=max_tokens,
                silent=True, verbose=args.verbose,
            )
        except CodexCliError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    issue_count = report.count("**Location**")
    if issue_count:
        print(f"Found {issue_count} potential issue(s):")
        for line in report.splitlines():
            if line.startswith("- **Issue**") or line.startswith("**Issue**"):
                print(f"  {line.strip()}")
    else:
        print("No issues found.")
    print("=" * 60)
    print(report)

    if args.output:
        out = Path(args.output).expanduser()
        out.write_text(report, encoding="utf-8")
        print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
