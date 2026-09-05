"""The session_workflow command and JSON interchange boundary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from campaignlib import find_default_config
from .engine import Engine
from .models import Evidence
from .storage import WorkflowError

OPERATIONS = ("init", "status", "migrate", "start", "submit", "check", "decide", "approve", "apply", "select-version", "export", "import", "recover", "evidence")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--campaign-dir", default=".")
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--config", default=find_default_config(__file__))
    parser.add_argument("--expected-revision", type=int)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--request", type=Path, help="JSON request file shared with native agents")
    source.add_argument("--request-json", help="JSON object (editor interchange)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    return parser


def dispatch(args):
    campaign = Path(args.campaign_dir).resolve(strict=True)
    session = Path(args.session_dir)
    if not session.is_absolute():
        session = campaign / session
    engine = Engine(session, campaign)
    payload = json.loads(args.request.read_text() if args.request else args.request_json or "{}")
    if not isinstance(payload, dict):
        raise WorkflowError("request must be a JSON object")
    if args.operation == "migrate":
        from .migrate import migrate
        return migrate(str(campaign), str(session), **payload)
    if args.operation == "init":
        if payload:
            raise WorkflowError("init takes --config, not a request payload")
        return engine.initialize(args.config)
    if args.operation == "status":
        if payload:
            raise WorkflowError("status does not accept a payload")
        return engine.status()
    if args.operation == "export":
        return engine.export(**payload)
    if args.operation == "evidence":
        data = engine.store.bytes(Evidence.model_validate(payload))
        return {"text": data.decode("utf-8", errors="replace"), "bytes": len(data)}
    if args.operation == "recover":
        if payload:
            raise WorkflowError("recover does not accept a payload")
        with engine.store.lock():
            return engine.store.recover()
    if args.expected_revision is None:
        raise WorkflowError("--expected-revision is required for mutations; inspect status first")
    return engine.mutate(args.operation, payload, args.expected_revision)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = dispatch(args)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
