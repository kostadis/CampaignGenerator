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
import tempfile
from pathlib import Path

from campaignlib import (
    CodexCliError,
    DEFAULT_MODEL,
    add_backend_args,
    assemble_docs,
    canonical_context_section,
    ConfigLocationError,
    campaign_root_for_config,
    client_from_args,
    find_registry,
    find_default_config,
    load_agent_prompt,
    load_config,
    run_single_batch,
    stream_api,
)
from campaignlib.api.client import resolve_cli_model
from campaignlib.consistency import (
    ConsistencyDocument,
    GroupedConsistencyProtocolError,
    normalize_grouped_response,
    render_grouped_prompt_blocks,
)

_DEFAULT_CONFIG_DOCS = ["campaign_state", "world_state"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consistency-check a session document against campaign context."
    )
    parser.add_argument(
        "documents",
        nargs="+",
        metavar="DOCUMENT",
        help=(
            "Path(s) to the document(s) to check. Multiple explicit paths are "
            "audited together in one model call."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to <campaign>/config/config.yaml (default: <cwd>/config/config.yaml)",
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
        if args.config is None:
            args.config = find_default_config()
        campaign_root = campaign_root_for_config(args.config)
    except ConfigLocationError as e:
        parser.error(str(e))

    try:
        model_intent = resolve_cli_model(args, legacy_default=DEFAULT_MODEL)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    effective_model = model_intent.effective_model
    args.model = effective_model

    doc_paths = [Path(value).expanduser() for value in args.documents]
    resolved_paths: set[Path] = set()
    for doc_path in doc_paths:
        resolved = doc_path.resolve()
        if resolved in resolved_paths:
            print(f"Error: duplicate document: {doc_path}", file=sys.stderr)
            sys.exit(1)
        resolved_paths.add(resolved)
        if not doc_path.exists():
            print(f"Error: document not found: {doc_path}", file=sys.stderr)
            sys.exit(1)
        if not doc_path.is_file():
            print(f"Error: document is not a file: {doc_path}", file=sys.stderr)
            sys.exit(1)

    documents = [
        ConsistencyDocument(
            identifier=f"D{index:02d}",
            path=doc_path,
            text=doc_path.read_text(encoding="utf-8").strip(),
        )
        for index, doc_path in enumerate(doc_paths, start=1)
    ]
    grouped = len(documents) > 1

    config, base_dir = load_config(args.config)

    # Every input the check is meant to read must exist before the model call:
    # a skipped grounding doc or context file produces a report that looks
    # complete and is not. Collect every problem, then fail once.
    configured = {d["label"]: d.get("path") for d in config.get("documents", [])}
    problems: list[str] = []
    for label in _DEFAULT_CONFIG_DOCS:
        if label not in configured:
            problems.append(f"'{label}' is not in {args.config}")
        elif not configured[label]:
            problems.append(f"'{label}' has no path in {args.config}")
    for ctx in args.context or []:
        if not Path(ctx).expanduser().exists():
            problems.append(f"context file not found: {ctx}")
    if problems:
        for problem in problems:
            print(f"Error: {problem}", file=sys.stderr)
        sys.exit(1)

    context_parts: list[str] = []

    # The registry is campaign data under the campaign root, not beside the
    # config file (base_dir is <campaign>/config/). A check without canon looks
    # complete and is not, so a missing registry is an error, not a note.
    registry_path = find_registry(campaign_root)
    canon = canonical_context_section(campaign_root)
    if not canon or registry_path is None:
        print(f"Error: no entity registry at {campaign_root}/docs/entity_registry.yaml; "
              f"refusing to check without canon.", file=sys.stderr)
        sys.exit(1)
    canonical_registry_path = registry_path.resolve()
    context_parts.append(canon)

    for label in _DEFAULT_CONFIG_DOCS:
        text = assemble_docs(config, [label], base_dir)
        if text.strip():
            context_parts.append(text)

    if args.context:
        for ctx in args.context:
            p = Path(ctx).expanduser()
            if p.resolve() == canonical_registry_path:
                print(
                    f"  Note: skipping --context {p}; already included as "
                    "authoritative canon.",
                    file=sys.stderr,
                )
                continue
            context_parts.append(f"## {p.name}\n\n{p.read_text(encoding='utf-8').strip()}")

    system = load_agent_prompt(
        "session_doc/consistency_grouped" if grouped else "session_doc/consistency"
    )
    context_text = "## Campaign Context\n\n" + "\n\n---\n\n".join(context_parts)
    common_context_chars = len(system) + len(context_text)

    if grouped:
        target_chars = sum(len(document.text) for document in documents)
        avoided_chars = (len(documents) - 1) * common_context_chars
        print(f"Documents : {len(documents)} ({target_chars:,} target chars)")
        print(f"Context   : {len(context_parts)} document(s), {common_context_chars:,} shared chars")
        print("Model calls: 1 (grouped, fail-closed)")
        print(f"Avoided   : {avoided_chars:,} repeated common-context chars")
        print(
            "Telemetry : "
            f"model_calls=1 shared_context_chars={common_context_chars} "
            f"target_chars={target_chars} "
            f"repeated_context_chars_avoided={avoided_chars}"
        )
    else:
        document = documents[0]
        print(f"Document : {document.path.name} ({len(document.text):,} chars)")
        print(
            f"Context  : {len(context_parts)} document(s), "
            f"{common_context_chars:,} shared chars"
        )
        print(
            "Telemetry : "
            f"model_calls=1 shared_context_chars={common_context_chars} "
            f"target_chars={len(document.text)} "
            "repeated_context_chars_avoided=0"
        )
    model_display = (
        args.model
        if args.model is not None
        else "Codex subscription default"
    )
    print(f"Model    : {model_display}")
    print("=" * 60)

    if grouped:
        prompt = render_grouped_prompt_blocks(documents, context_parts)
    else:
        prompt = [
            {
                "type": "text",
                "text": context_text + "\n\n---\n\n",
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": f"## Document to Check\n\n{documents[0].text}",
            },
        ]

    try:
        client = client_from_args(args)
    except CodexCliError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
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

    if grouped:
        try:
            grouped_result = normalize_grouped_response(report, documents)
        except GroupedConsistencyProtocolError as e:
            print(f"Error: invalid grouped consistency response: {e}", file=sys.stderr)
            sys.exit(1)
        report = grouped_result.report
        issue_count = grouped_result.issue_count
    else:
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
        # Validate first, then replace atomically. A grouped protocol failure
        # must never overwrite a prior report with partial findings.
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=out.parent,
                prefix=f".{out.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(report)
                temp_path = Path(temp_file.name)
            temp_path.replace(out)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
