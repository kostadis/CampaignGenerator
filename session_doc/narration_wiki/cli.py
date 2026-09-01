"""Command-line owner for the deterministic narration-wiki workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .collect import collect
from .indexes import index_check, load_companion_capability
from .measure import measure
from .models import NarrationWikiError, UsageError, canonical_json
from .paths import resolve_scope
from .proposals import apply_proposal, stage_proposal
from .storage import (
    finalize_proposal,
    read_json,
    record_conflict_ruling,
    record_pattern_ruling,
)


PUBLIC_COMMANDS = (
    "status", "collect", "measure", "index-check", "conflict-rule",
    "pattern-rule", "proposal-stage", "proposal-apply", "proposal-rule",
)


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def _scope_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--campaign-dir", required=True)
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--iteration-id", required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def build_parser() -> Parser:
    parser = Parser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    common = _scope_parser()
    for name in ("status", "collect", "index-check"):
        commands.add_parser(name, parents=[common], allow_abbrev=False)
    command = commands.add_parser("measure", parents=[common], allow_abbrev=False)
    command.add_argument("--phase", required=True, choices=("before", "after"))
    command.add_argument("--proposal-id")
    command = commands.add_parser("conflict-rule", parents=[common], allow_abbrev=False)
    command.add_argument("--conflict-id", required=True)
    command.add_argument("--resolution", required=True)
    command.add_argument("--rationale", required=True)
    command = commands.add_parser("pattern-rule", parents=[common], allow_abbrev=False)
    command.add_argument("--pattern-slug", required=True)
    command.add_argument("--decision", required=True, choices=("accept", "reject"))
    command.add_argument("--tier", choices=("campaign", "portable"))
    command.add_argument("--named-portable-override", action="store_true")
    command.add_argument("--rationale")
    command = commands.add_parser("proposal-stage", parents=[common], allow_abbrev=False)
    command.add_argument("--proposal-id", required=True)
    command.add_argument("--draft", required=True)
    command.add_argument("--evidence-binding-json", action="append", default=[])
    command.add_argument("--override-rationale")
    command = commands.add_parser("proposal-apply", parents=[common], allow_abbrev=False)
    command.add_argument("--proposal-id", required=True)
    command = commands.add_parser("proposal-rule", parents=[common], allow_abbrev=False)
    command.add_argument("--proposal-id", required=True)
    command.add_argument("--decision", required=True, choices=("accept", "reject"))
    return parser


def _status(scope: Any) -> dict[str, Any]:
    iteration = read_json(scope.iteration_root / "iteration.json")
    gate1_path = scope.iteration_root / "gate1.json"
    rulings = read_json(gate1_path).get("rulings", []) if gate1_path.is_file() else []
    counts = {"pending": 0, "accepted": 0, "rejected": 0, "pending_portable_sync": 0}
    drafts = scope.iteration_root / "drafts"
    draft_slugs = {path.stem for path in drafts.glob("*.md")} if drafts.is_dir() else set()
    ruled_slugs = {str(row.get("subject_id")) for row in rulings}
    counts["pending"] = len(draft_slugs - ruled_slugs)
    for row in rulings:
        if row.get("ruling") == "rejected":
            counts["rejected"] += 1
        elif row.get("tier") == "portable":
            promotion = scope.iteration_root / "portable-promotions" / f"{row.get('subject_id')}.md"
            portable = scope.portable_root / "patterns" / f"{row.get('subject_id')}.md"
            counts["pending_portable_sync" if promotion.exists() and not portable.exists() else "accepted"] += 1
        else:
            counts["accepted"] += 1
    conflict_drafts = scope.iteration_root / "conflict-drafts"
    conflicts = {path.stem for path in conflict_drafts.glob("*.json")} if conflict_drafts.is_dir() else set()
    conflict_refs = scope.iteration_root / "conflict-rulings.json"
    ruled_conflicts = {
        str(row.get("conflict_id")) for row in read_json(conflict_refs).get("rulings", [])
    } if conflict_refs.is_file() else set()
    recovery = None
    transactions = scope.iteration_root / "transactions"
    if transactions.is_dir():
        for path in sorted(transactions.glob("*.json"), key=lambda item: item.name):
            journal = read_json(path)
            if journal.get("state") not in {"committed", "rolled_back"}:
                recovery = {
                    "transaction_id": journal.get("transaction_id"),
                    "operation": journal.get("operation"),
                    "state": journal.get("state"),
                    "next_action": journal.get("next_action"),
                }
                break
    active = iteration.get("active_proposal_id")
    state = str(iteration.get("state", "new"))
    if recovery:
        state = "needs_attention" if recovery["state"] == "needs_attention" else state
    return {
        "iteration_id": scope.iteration_id,
        "state": state,
        "corpus_id": iteration.get("corpus_id"),
        "pattern_counts": counts,
        "unresolved_conflict_ids": sorted(conflicts - ruled_conflicts),
        "active_proposal_id": active,
        "dependency": load_companion_capability(scope.portable_root),
        "recovery": recovery,
    }


def _binding_values(raw: Sequence[str]) -> list[dict[str, Any]]:
    result = []
    for value in raw:
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise UsageError(f"--evidence-binding-json is invalid JSON: {exc.msg}") from exc
        if not isinstance(loaded, dict):
            raise UsageError("--evidence-binding-json must contain one object")
        result.append(loaded)
    return result


def _dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    scope = resolve_scope(args.campaign_dir, args.session_dir, args.iteration_id)
    command = args.command
    if command == "status":
        result = _status(scope)
    elif command == "collect":
        result = collect(scope)
    elif command == "measure":
        result = measure(scope, args.phase, args.proposal_id)
    elif command == "index-check":
        result = index_check(scope)
        return result, 0 if result["valid"] else 5
    elif command == "conflict-rule":
        result = record_conflict_ruling(scope, args.conflict_id, args.resolution, args.rationale)
    elif command == "pattern-rule":
        result = record_pattern_ruling(
            scope,
            args.pattern_slug,
            args.decision,
            tier=args.tier,
            named_portable_override=args.named_portable_override,
            rationale=args.rationale,
        )
    elif command == "proposal-stage":
        result = stage_proposal(
            scope,
            args.proposal_id,
            args.draft,
            evidence_bindings=_binding_values(args.evidence_binding_json),
            override_rationale=args.override_rationale,
        )
    elif command == "proposal-apply":
        result = apply_proposal(scope, args.proposal_id)
    elif command == "proposal-rule":
        result = finalize_proposal(scope, args.proposal_id, args.decision)
    else:
        raise UsageError(f"unknown command: {command}")
    return result, 0


def _safe_message(message: str, args: argparse.Namespace | None) -> str:
    if args is None:
        return message
    for attribute, label in (("campaign_dir", "<campaign>"), ("session_dir", "<session>")):
        value = str(getattr(args, attribute, "") or "")
        if value:
            message = message.replace(str(Path(value).expanduser()), label).replace(value, label)
    return message


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args: argparse.Namespace | None = None
    try:
        args = parser.parse_args(argv)
        result, code = _dispatch(args)
        envelope = {"ok": code == 0, "command": args.command, **result}
        if args.as_json:
            print(canonical_json(envelope, compact=True))
        else:
            print(f"{args.command}: {'ok' if code == 0 else 'validation failed'}")
            for key, value in result.items():
                print(f"{key}: {value}")
        return code
    except NarrationWikiError as exc:
        message = _safe_message(str(exc), args)
        if args is not None and getattr(args, "as_json", False):
            print(canonical_json({
                "ok": False,
                "command": getattr(args, "command", None),
                "error": message,
                "exit_code": exc.exit_code,
            }, compact=True))
        else:
            print(f"error: {message}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # pragma: no cover - defensive public boundary
        message = _safe_message(str(exc) or type(exc).__name__, args)
        if args is not None and getattr(args, "as_json", False):
            print(canonical_json({"ok": False, "command": args.command, "error": message, "exit_code": 70}, compact=True))
        else:
            print(f"error: {message}", file=sys.stderr)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
