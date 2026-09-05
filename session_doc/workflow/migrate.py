"""Explicit inventory/import of historical session artifacts; never infer approval."""
import argparse
import json
from pathlib import Path
import sys

import yaml
from .models import Workflow
from .storage import Store, WorkflowError, now


def migrate(campaign_dir, session_dir, config, artifacts=None, dry_run=False, force=False):
    campaign = Path(campaign_dir).resolve(strict=True)
    session = (campaign / session_dir).resolve(strict=True)
    if not session.is_relative_to(campaign) or session == campaign:
        raise WorkflowError("session must be within campaign")
    store = Store(session)
    config_path = (campaign / config).resolve(strict=True)
    if not config_path.is_relative_to(campaign):
        raise WorkflowError("config must belong to campaign")
    raw = yaml.safe_load(store.path.read_text()) if store.path.exists() else None
    unknown = sorted(set(raw) - {"schema_version", "session_id", "artifacts"}) if isinstance(raw, dict) and raw.get("schema_version") != 1 else []
    files = sorted(p.relative_to(session).as_posix() for p in session.rglob("*") if p.is_file() and not any(part.startswith(".") for part in p.relative_to(session).parts) and p != store.path)
    report = {"schema_version": 1, "operation": "inventory", "files": files, "selected": artifacts or [], "legacy_version": raw.get("schema_version") if isinstance(raw, dict) else None, "unknown_fields": unknown, "approval_imported": False, "dry_run": dry_run}
    if dry_run:
        return report
    if raw is not None:
        if not isinstance(raw, dict) or raw.get("schema_version") != 0 or unknown:
            raise WorkflowError("unsupported legacy state; originals unchanged; inspect --dry-run inventory")
        if not force:
            raise WorkflowError("replacing schema-v0 state requires --force after reviewing --dry-run")
    if not artifacts:
        raise WorkflowError("select historical files explicitly with --artifact; empty selection never means all")
    if len(set(artifacts)) != len(artifacts) or any(p not in files for p in artifacts):
        raise WorkflowError("artifact selection contains duplicate or unknown paths")
    with store.lock():
        if store.path.exists() and yaml.safe_load(store.path.read_text()) != raw:
            raise WorkflowError("state changed since inventory")
        snapshots = [store.preserve(store.contained(p), label="source").model_dump() for p in artifacts]
        if store.path.exists():
            snapshots.append(store.preserve(store.path, label="source").model_dump())
        state = Workflow(session_id=session.name, config=str(config_path), revision=1, events=[{"operation": "migration", "at": now(), "historical_evidence": snapshots, "approval_imported": False}])
        from campaignlib.util import atomic_write_text
        atomic_write_text(store.path, yaml.safe_dump(state.model_dump(mode="json"), sort_keys=False))
    report["operation"] = "migrated"
    report["snapshots"] = snapshots
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", required=True)
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--artifact", action="append", dest="artifacts")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(migrate(**vars(args)), indent=2))
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
