"""Digest-bound authority-ledger migration for the shared review foundation."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
import re

from pipelines.summary_native import corpus, resolve, schema

from pipelines.summary_native.authority import (
    AuthorityError,
    AuthorityLedger,
    LEGACY_SCHEMA_VERSION,
    RulingRecord,
    SCHEMA_VERSION,
    _NoDuplicatesLoader,
    canonical_bytes,
    ledger_bytes,
    ledger_path,
    now_utc,
    sha256_bytes,
)
from pipelines.summary_native.authority_apply import (
    TransactionTarget,
    _prepare_transaction_locked,
    _json_bytes,
    _tip_bytes,
    authority_dir,
    authority_lock,
    ledger_tip_path,
    pending_transaction,
    recover_transaction,
    validate_ledger_tip,
)


def _dependency_subject(path: Path) -> str | None:
    try:
        text=path.read_text(encoding="utf-8")
    except (OSError,UnicodeError): return None
    match=re.search(r"^subject:\s*(.+?)\s*$",text,re.MULTILINE)
    kind=re.search(r"^type:\s*(.+?)\s*$",text,re.MULTILINE)
    if not match or not kind: return None
    slug=re.sub(r"[^a-z0-9]+","-",match.group(1).casefold()).strip("-")
    category = kind.group(1).strip()
    return f"{schema.CATEGORY_REGISTRY_TYPE.get(category, category)}:{slug}"


def _dependency_locations(root: Path) -> tuple[Path, Path | None]:
    """Resolve the same persisted output/registry configuration as the CLI."""
    config_path = root / "config" / "grounding.yaml"
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise AuthorityError(f"DEPENDENCY_MIGRATION_INVALID: cannot read {config_path}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise AuthorityError("DEPENDENCY_MIGRATION_INVALID: grounding.yaml must be a mapping")
    configured = raw.get("summary_native") or {}
    if not isinstance(configured, dict):
        raise AuthorityError(
            "DEPENDENCY_MIGRATION_INVALID: grounding.yaml summary_native must be a mapping"
        )
    out_value = configured.get("out_root") or schema.DEFAULT_OUT_ROOT
    if not isinstance(out_value, str):
        raise AuthorityError(
            "DEPENDENCY_MIGRATION_INVALID: summary_native.out_root must be a path string"
        )
    try:
        out_root = schema.resolve_under(root, out_value)
        registry_path = resolve.resolve_registry_path(root, None, configured)
    except ValueError as exc:
        raise AuthorityError(f"DEPENDENCY_MIGRATION_INVALID: {exc}") from exc
    return out_root, registry_path


def _dependency_rebuild(relative: str, reason: str) -> dict:
    return {
        "path": relative,
        "command": "summary_native build --force",
        "reason": reason,
    }


def _adoptable_dependency_manifest(
    root: Path,
    path: Path,
    raw: dict,
    registry_path: Path | None,
) -> dict:
    files = raw.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("legacy dependencies cannot be reconstructed from pinned inputs")

    registry_sha256 = sha256_bytes(registry_path.read_bytes()) if registry_path else None
    if (raw.get("canon") or {}).get("registry_sha256") != registry_sha256:
        raise ValueError("legacy registry bytes no longer match the built corpus")
    if registry_path is None:
        registry = {}
    else:
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        if not isinstance(registry, dict):
            raise ValueError("entity registry is not a mapping")

    artifacts: list[dict] = []
    for source in files:
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            raise ValueError("legacy dependencies cannot be reconstructed from pinned inputs")
        source_path = schema.resolve_under(root, source["path"])
        if (
            not source_path.is_file()
            or source_path.is_symlink()
            or sha256_bytes(source_path.read_bytes()) != source.get("sha256")
        ):
            raise ValueError("legacy source bytes no longer match the built corpus")
        artifacts.append(
            {
                "consumer": "summary_native.build",
                "path": source["path"],
                "sha256": source["sha256"],
                "subject_ids": [],
                "ownership": "source",
            }
        )

    range_dir = path.parent
    subjects: list[str] = []
    dossiers = sorted((range_dir / "dossiers").glob("*.md")) if (range_dir / "dossiers").is_dir() else []
    for dossier in dossiers:
        if dossier.is_symlink():
            raise ValueError("legacy dossier inventory contains a symlink")
        subject = _dependency_subject(dossier)
        if subject is None:
            raise ValueError("legacy dossier subject metadata is incomplete")
        subjects.append(subject)
        artifacts.append(
            {
                "consumer": "summary_native.build",
                "path": dossier.relative_to(root).as_posix(),
                "sha256": sha256_bytes(dossier.read_bytes()),
                "subject_ids": [subject],
                "ownership": "generated",
            }
        )

    for name in ("chronology.md", "memorable_moments.md", "other_sections.md"):
        artifact = range_dir / name
        if artifact.is_file() and not artifact.is_symlink():
            artifacts.append(
                {
                    "consumer": "summary_native.build",
                    "path": artifact.relative_to(root).as_posix(),
                    "sha256": sha256_bytes(artifact.read_bytes()),
                    "subject_ids": [],
                    "ownership": "generated",
                }
            )
    for name in corpus.REPORT_FILES:
        artifact = range_dir / name
        if artifact.is_file() and not artifact.is_symlink():
            artifacts.append(
                {
                    "consumer": "summary_native.validation",
                    "path": artifact.relative_to(root).as_posix(),
                    "sha256": sha256_bytes(artifact.read_bytes()),
                    "subject_ids": sorted(set(subjects)),
                    "ownership": "generated",
                }
            )
    return corpus.build_dependency_manifest(
        registry=registry,
        registry_sha256=registry_sha256,
        artifacts=artifacts,
        precision="subject",
    )


def _plan_dependency_adoption(campaign_dir: Path) -> tuple[dict, list[tuple[Path, bytes, bytes]]]:
    root=Path(campaign_dir).resolve(); changed=[]; rebuild=[]; targets=[]
    out_root, registry_path = _dependency_locations(root)
    manifests = set(out_root.glob("*/manifest.json")) if out_root.is_dir() else set()
    for path in sorted(manifests):
        relative=path.relative_to(root).as_posix(); before=path.read_bytes()
        try: raw=json.loads(before)
        except (UnicodeError,json.JSONDecodeError):
            rebuild.append({"path":relative,"command":"summary_native build --force","reason":"legacy dependencies cannot be reconstructed from pinned inputs"}); continue
        if not isinstance(raw, dict):
            rebuild.append(_dependency_rebuild(
                relative, "legacy dependencies cannot be reconstructed from pinned inputs"
            ))
            continue
        dependencies = raw.get("identity_dependencies")
        if (
            isinstance(dependencies,dict)
            and dependencies.get("version")==2
            and dependencies.get("precision")=="subject"
            and dependencies.get("inventory_complete") is True
        ):
            try:
                corpus.validate_dependency_manifest(dependencies)
            except corpus.CorpusError as exc:
                rebuild.append(_dependency_rebuild(relative, str(exc)))
            else:
                continue
            continue
        try:
            raw["identity_dependencies"] = _adoptable_dependency_manifest(
                root, path, raw, registry_path
            )
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            rebuild.append(_dependency_rebuild(relative, str(exc)))
            continue
        after=(json.dumps(raw,sort_keys=True,separators=(",",":"))+"\n").encode(); changed.append(relative); targets.append((path,before,after))
    public={"kind":"identity_dependency_adoption","no_op":not changed and not rebuild,"changed_paths":changed,"rebuild_required":rebuild}
    public["plan_sha256"]=sha256_bytes(canonical_bytes({**public,"targets":[{"path":path.relative_to(root).as_posix(),"before_sha256":sha256_bytes(before),"after_sha256":sha256_bytes(after)} for path,before,after in targets]}))
    return public, targets


def plan_dependency_adoption(campaign_dir: Path) -> dict:
    root=Path(campaign_dir).resolve()
    with authority_lock(root,exclusive=False):
        _ensure_no_pending(root)
        return _plan_dependency_adoption(root)[0]


def apply_dependency_adoption(campaign_dir: Path, *, plan_sha256: str) -> dict:
    root=Path(campaign_dir).resolve()
    with authority_lock(root,exclusive=True):
        _ensure_no_pending(root); current, raw_targets=_plan_dependency_adoption(root)
        if current["plan_sha256"]!=plan_sha256: raise AuthorityError("DEPENDENCY_MIGRATION_STALE: reviewed plan no longer matches")
        if current["rebuild_required"]: raise AuthorityError("DEPENDENCY_MIGRATION_REBUILD_REQUIRED: rebuild legacy inputs")
        if raw_targets:
            targets=[TransactionTarget.replace(path,before,after) for path,before,after in raw_targets]
            journal=_prepare_transaction_locked(root,proposal_id=f"dependency-adoption-{plan_sha256[:20]}",proposal_sha256=plan_sha256,targets=targets)
            recover_transaction(root,journal["id"],_already_locked=True)
    return {"plan_sha256":plan_sha256,"changed_paths":current["changed_paths"]}


def _raw_ledger(root: Path) -> tuple[dict, bytes]:
    path = ledger_path(root)
    try:
        data = path.read_bytes()
        raw = yaml.load(data.decode("utf-8"), Loader=_NoDuplicatesLoader)
    except AuthorityError:
        raise
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise AuthorityError(f"AUTH_MIGRATION_INVALID: cannot read authority ledger: {exc}") from exc
    if not isinstance(raw, dict):
        raise AuthorityError("AUTH_MIGRATION_INVALID: authority ledger must be one mapping")
    return raw, data


def _ensure_no_pending(root: Path) -> None:
    pending = pending_transaction(root)
    if pending is None:
        return
    identifier = pending.get("id", "unknown")
    version = pending.get("version", 1)
    detail = "preexisting v1 " if version == 1 else ""
    raise AuthorityError(
        f"AUTH_MIGRATION_PENDING: recover the {detail}transaction first with "
        f"`summary_native authority recover {identifier} --campaign-dir {root}`",
        "AUTH_RECOVERY",
    )


def _plan_digest(plan: dict) -> str:
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    return sha256_bytes(canonical_bytes(unsigned))


def _decode(raw: dict, *, expected_version: int) -> AuthorityLedger:
    if raw.get("version") != expected_version:
        raise AuthorityError(
            f"AUTH_MIGRATION_INVALID: expected authority version {expected_version}, got {raw.get('version')!r}"
        )
    try:
        return AuthorityLedger.model_validate(raw)
    except Exception as exc:
        raise AuthorityError(
            f"AUTH_MIGRATION_INVALID: unknown or invalid authority ledger fields: {exc}"
        ) from exc


def _plan_locked(root: Path) -> dict:
    _ensure_no_pending(root)
    validate_ledger_tip(root)
    raw, before = _raw_ledger(root)
    version = raw.get("version")
    if version == SCHEMA_VERSION:
        ledger = _decode(raw, expected_version=SCHEMA_VERSION)
        plan = {
            "kind": "authority_v1_to_v2",
            "from_version": SCHEMA_VERSION,
            "to_version": SCHEMA_VERSION,
            "campaign": ledger.campaign,
            "no_op": True,
            "before_sha256": sha256_bytes(before),
            "after_sha256": sha256_bytes(before),
            "before_revision": ledger.revision,
            "after_revision": ledger.revision,
            "record_count": len(ledger.records),
            "conflict_count": len(ledger.conflicts),
            "stale_source_proposals": [],
            "changed_paths": [],
        }
        plan["plan_sha256"] = _plan_digest(plan)
        return plan
    if version != LEGACY_SCHEMA_VERSION:
        raise AuthorityError(
            f"AUTH_MIGRATION_INVALID: unsupported authority ledger version {version!r}"
        )

    legacy = _decode(raw, expected_version=LEGACY_SCHEMA_VERSION)
    migrated = AuthorityLedger.model_validate({
        **legacy.model_dump(mode="json", exclude_none=True),
        "version": SCHEMA_VERSION,
        "revision": legacy.revision + 1,
    })
    after = ledger_bytes(migrated)
    before_sha = sha256_bytes(before)
    archive_path = Path("docs") / "authority" / "migrations" / f"authority-v1-{before_sha}.yaml"
    event_id = f"event-migrate-authority-v1-v2-{before_sha[:16]}"
    stale = sorted(
        record.proposal_id
        for record in legacy.records
        if isinstance(record, RulingRecord)
        and record.status in {"proposed", "reversal_proposed"}
        and record.proposal_id
    )
    registry_path = root / "docs" / "entity_registry.yaml"
    plan = {
        "kind": "authority_v1_to_v2",
        "from_version": LEGACY_SCHEMA_VERSION,
        "to_version": SCHEMA_VERSION,
        "campaign": legacy.campaign,
        "no_op": False,
        "before_sha256": before_sha,
        "after_sha256": sha256_bytes(after),
        "before_revision": legacy.revision,
        "after_revision": migrated.revision,
        "record_count": len(legacy.records),
        "conflict_count": len(legacy.conflicts),
        "stale_source_proposals": stale,
        "archive_path": str(archive_path),
        "event_id": event_id,
        "entity_registry_sha256": sha256_bytes(registry_path.read_bytes()) if registry_path.is_file() else None,
        "changed_paths": [
            str(ledger_path(root).relative_to(root)),
            str(archive_path),
            str((authority_dir(root) / "events" / f"{event_id}.json").relative_to(root)),
            str(ledger_tip_path(root).relative_to(root)),
        ],
    }
    plan["plan_sha256"] = _plan_digest(plan)
    return plan


def plan_authority_migration(campaign_dir: Path) -> dict:
    """Return the exact, side-effect-free authority v1-to-v2 migration plan."""
    root = Path(campaign_dir).resolve()
    with authority_lock(root, exclusive=False):
        return _plan_locked(root)


def _completed_event(root: Path, plan_sha256: str) -> dict | None:
    for path in sorted((authority_dir(root) / "events").glob("event-migrate-authority-v1-v2-*.json")):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(event, dict) and event.get("plan_sha256") == plan_sha256:
            if event.get("after_sha256") != sha256_bytes(ledger_path(root).read_bytes()):
                raise AuthorityError("AUTH_MIGRATION_STALE: migrated ledger differs from its migration event", "AUTH_STALE")
            try:
                tip = json.loads(ledger_tip_path(root).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise AuthorityError("AUTH_MIGRATION_STALE: migrated ledger has no valid tip", "AUTH_STALE") from exc
            if tip.get("event_id") != event.get("id"):
                raise AuthorityError("AUTH_MIGRATION_STALE: migration event is not the live ledger tip", "AUTH_STALE")
            archive = root / str(event.get("archive_path", ""))
            if not archive.is_file() or sha256_bytes(archive.read_bytes()) != event.get("before_sha256"):
                raise AuthorityError("AUTH_MIGRATION_STALE: archived v1 ledger bytes are missing or changed", "AUTH_STALE")
            return event
    return None


def apply_authority_migration(campaign_dir: Path, *, plan_sha256: str) -> dict:
    """Apply exactly the reviewed plan through the shared recoverable journal."""
    root = Path(campaign_dir).resolve()
    with authority_lock(root, exclusive=True):
        _ensure_no_pending(root)
        validate_ledger_tip(root)
        raw, before = _raw_ledger(root)
        if raw.get("version") == SCHEMA_VERSION:
            completed = _completed_event(root, plan_sha256)
            if completed is not None:
                return completed
            current = _plan_locked(root)
            if current["plan_sha256"] != plan_sha256:
                raise AuthorityError(
                    "AUTH_MIGRATION_STALE: migration plan does not match current authority bytes",
                    "AUTH_STALE",
                )
            return current

        plan = _plan_locked(root)
        if plan["plan_sha256"] != plan_sha256:
            raise AuthorityError(
                "AUTH_MIGRATION_STALE: migration plan does not match current authority bytes",
                "AUTH_STALE",
            )
        legacy = _decode(raw, expected_version=LEGACY_SCHEMA_VERSION)
        migrated = AuthorityLedger.model_validate({
            **legacy.model_dump(mode="json", exclude_none=True),
            "version": SCHEMA_VERSION,
            "revision": legacy.revision + 1,
        })
        after = ledger_bytes(migrated)
        archive = root / plan["archive_path"]
        event_path = authority_dir(root) / "events" / f"{plan['event_id']}.json"
        event = {
            "id": plan["event_id"],
            "reason": "authority-v1-to-v2-migration",
            "actor": "migration",
            "recorded_at": now_utc(),
            "campaign": plan["campaign"],
            "plan_sha256": plan["plan_sha256"],
            "before_sha256": plan["before_sha256"],
            "after_sha256": plan["after_sha256"],
            "before_revision": plan["before_revision"],
            "after_revision": plan["after_revision"],
            "record_count": plan["record_count"],
            "conflict_count": plan["conflict_count"],
            "stale_source_proposals": plan["stale_source_proposals"],
            "archive_path": plan["archive_path"],
            "event_id": plan["event_id"],
        }
        tip = ledger_tip_path(root)
        targets: list[TransactionTarget] = [
            TransactionTarget.create(archive, before),
            TransactionTarget.replace(ledger_path(root), before, after),
            TransactionTarget.create(event_path, _json_bytes(event)),
            (
                TransactionTarget.replace(tip, tip.read_bytes(), _tip_bytes(plan["event_id"], after))
                if tip.exists()
                else TransactionTarget.create(tip, _tip_bytes(plan["event_id"], after))
            ),
        ]
        journal = _prepare_transaction_locked(
            root,
            proposal_id=plan["event_id"],
            proposal_sha256=plan["plan_sha256"],
            targets=targets,
        )
        recover_transaction(root, journal["id"], _already_locked=True)
        return {**event, "transaction_id": journal["id"]}
