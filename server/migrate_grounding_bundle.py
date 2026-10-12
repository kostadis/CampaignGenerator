"""Explicit, recoverable adoption of loose grounding output into generations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from pipelines.summary_native.authority_apply import (
    authority_lock,
    require_no_pending_transaction,
    validate_ledger_tip,
)
from pydantic import TypeAdapter, ValidationError
from pipelines.summary_native.promotion.models import (
    ActivationRecord, BaselineKind, ContentIdentity, GenerationKind,
    GenerationManifest, OpaqueId,
)
from pipelines.summary_native.review.store import load_campaign_identity
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest


MANAGED_FILES = (
    "world_state.md", "campaign_state.md", "party.md", "planning.md",
    "canon_events_timeline.md",
)
MANAGED_ALIASES = (*MANAGED_FILES, "reference")
GROUNDING_RELATIVE = Path("docs/grounding")
PENDING_RELATIVE = GROUNDING_RELATIVE / "migration-pending.json"
CONFIG_RELATIVE = Path("config/config.yaml")


def _campaign_root(value: Path) -> Path:
    raw = Path(value).expanduser().absolute()
    cursor = Path(raw.anchor)
    for part in raw.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise MigrationError(f"campaign path contains a symlink: {cursor}", "PROMOTION_PATH_CONFLICT")
    return raw


class MigrationError(ValueError):
    def __init__(self, message: str, code: str = "PROMOTION_MIGRATION_REQUIRED") -> None:
        super().__init__(message)
        self.code = code


def _default_mode() -> int:
    """The mode an ordinary ``open(..., "w")`` would give a new file."""
    current = os.umask(0)
    os.umask(current)
    return 0o666 & ~current


def atomic_write_bytes(path: Path | str, data: bytes, *, mode: int | None = None) -> None:
    """Migration-local durable replace; inability to sync is a hard failure.

    The replacement keeps the replaced file's permission bits (a campaign's
    0644 config must not become 0600), or takes ``mode`` when given (a copied
    member keeps its source's bits), or the ordinary umask default.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = (
            stat.S_IMODE(target.stat().st_mode)
            if target.is_file() and not target.is_symlink()
            else _default_mode()
        )
    temporary = target.with_name(f".{target.name}.migration-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return canonical_bytes(value) + b"\n"


def _identity(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    if path.is_symlink():
        return {"path": relative, "kind": "symlink", "target": os.readlink(path)}
    if not path.exists():
        return {"path": relative, "kind": "absent"}
    if path.is_file():
        data = path.read_bytes()
        return {"path": relative, "kind": "file", "sha256": _sha(data), "size": len(data)}
    if path.is_dir():
        members = []
        for item in sorted(path.rglob("*")):
            if item.is_symlink():
                raise MigrationError(f"legacy bundle contains unsupported symlink: {item}", "PROMOTION_PATH_CONFLICT")
            if item.is_file():
                data = item.read_bytes()
                members.append({"path": item.relative_to(path).as_posix(), "sha256": _sha(data), "size": len(data)})
            elif not item.is_dir():
                raise MigrationError(f"legacy bundle contains unsupported special file: {item}", "PROMOTION_PATH_CONFLICT")
        return {"path": relative, "kind": "directory", "sha256": canonical_digest(members), "members": members}
    raise MigrationError(f"unsupported filesystem object: {path}", "PROMOTION_PATH_CONFLICT")


def _same_identity(path: Path, expected: dict[str, Any], root: Path) -> bool:
    try:
        return _identity(path, root) == expected
    except MigrationError:
        return False


def _matches_identity(path: Path, expected: dict[str, Any], root: Path) -> bool:
    actual = _identity(path, root)
    return all(actual.get(key) == value for key, value in expected.items() if key != "path")


CONFIG_DESTINATIONS = {
    "world_state": "../docs/grounding/current/world_state.md",
    "campaign_state": "../docs/grounding/current/campaign_state.md",
    "party": "../docs/grounding/current/party.md",
    "planning": "../docs/grounding/current/planning.md",
}


def _jsonable(value: Any) -> Any:
    """Represent parsed YAML in the plan's JSON without losing it.

    YAML has types JSON lacks (a bare ``2024-05-01`` is a ``date``); the plan
    is printed and digested as JSON, so those become ISO strings here. The
    config file itself is never re-serialized from this value.
    """
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _config_after(raw: dict[str, Any]) -> dict[str, Any]:
    result = _jsonable(raw)
    destinations = CONFIG_DESTINATIONS
    documents = result.get("documents")
    if isinstance(documents, list):
        for entry in documents:
            if isinstance(entry, dict) and entry.get("label") in destinations:
                entry["path"] = destinations[entry["label"]]
    grounding = result.get("grounding")
    if isinstance(grounding, dict):
        for key, value in destinations.items():
            if key in grounding:
                grounding[key] = value
        if "distill" in grounding and isinstance(grounding["distill"], str):
            grounding["distill"] = destinations["world_state"]
    return result


def _config_edits(text: str) -> list[dict[str, Any]]:
    """Locate exactly the config values ``_config_after`` changes.

    The config is rewritten by splicing these spans, never by re-dumping a
    parsed mapping, so the GM's comments, key order, quoting and unrelated
    values survive byte-for-byte.
    """
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        raise MigrationError(f"unreadable config: {exc}", "PROMOTION_PATH_CONFLICT") from exc
    if not isinstance(root, yaml.MappingNode):
        raise MigrationError("config must be a mapping", "PROMOTION_PATH_CONFLICT")
    edits: list[dict[str, Any]] = []

    def scalar(node: yaml.Node) -> str | None:
        return node.value if isinstance(node, yaml.ScalarNode) else None

    def value_edit(where: str, node: yaml.Node, after: str) -> None:
        if not isinstance(node, yaml.ScalarNode) or node.style in {"|", ">"}:
            raise MigrationError(
                f"config value {where} is not a plain or quoted scalar; set it to {after!r} by hand "
                "and preview again", "PROMOTION_PATH_CONFLICT",
            )
        start, end = node.start_mark.index, node.end_mark.index
        quote = node.style if node.style in {"'", '"'} else ""
        replacement = f"{quote}{after}{quote}"
        if start == end and start > 0 and text[start - 1] == ":":
            replacement = " " + replacement
        edits.append({"where": where, "start": start, "end": end, "before": node.value,
                      "after": after, "text": replacement})

    for key_node, value_node in root.value:
        key = scalar(key_node)
        if key == "documents" and isinstance(value_node, yaml.SequenceNode):
            for index, entry in enumerate(value_node.value):
                if not isinstance(entry, yaml.MappingNode):
                    continue
                pairs = [(scalar(k), k, v) for k, v in entry.value]
                labels = [scalar(v) for name, _k, v in pairs if name == "label"]
                label = labels[-1] if labels else None
                if label not in CONFIG_DESTINATIONS:
                    continue
                after = CONFIG_DESTINATIONS[label]
                paths = [(k, v) for name, k, v in pairs if name == "path"]
                if paths:
                    for _k, v in paths:
                        value_edit(f"documents[{index}].path", v, after)
                    continue
                if entry.flow_style:
                    raise MigrationError(
                        f"config documents[{index}] ({label}) has no path; add `path: {after}` by hand "
                        "and preview again", "PROMOTION_PATH_CONFLICT",
                    )
                label_key = next(k for name, k, _v in pairs if name == "label")
                label_value = next(v for name, _k, v in reversed(pairs) if name == "label")
                position = label_value.end_mark.index
                indent = " " * label_key.start_mark.column
                edits.append({"where": f"documents[{index}].path", "start": position, "end": position,
                              "before": None, "after": after, "text": f"\n{indent}path: {after}"})
        elif key == "grounding" and isinstance(value_node, yaml.MappingNode):
            for g_key, g_value in value_node.value:
                name = scalar(g_key)
                if name in CONFIG_DESTINATIONS:
                    value_edit(f"grounding.{name}", g_value, CONFIG_DESTINATIONS[name])
                elif name == "distill" and isinstance(g_value, yaml.ScalarNode) and g_value.tag.endswith(":str"):
                    value_edit("grounding.distill", g_value, CONFIG_DESTINATIONS["world_state"])
    return sorted(edits, key=lambda item: item["start"])


def _config_after_bytes(data: bytes, expected_after: dict[str, Any]) -> bytes:
    """The config bytes with only the previewed values replaced, verified."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationError("config is not UTF-8", "PROMOTION_PATH_CONFLICT") from exc
    pieces: list[str] = []
    cursor = 0
    for edit in _config_edits(text):
        if edit["start"] < cursor:
            raise MigrationError("config values overlap; edit them by hand", "PROMOTION_PATH_CONFLICT")
        pieces.append(text[cursor:edit["start"]])
        pieces.append(edit["text"])
        cursor = edit["end"]
    pieces.append(text[cursor:])
    rendered = "".join(pieces)
    try:
        reparsed = yaml.safe_load(rendered) or {}
    except yaml.YAMLError as exc:
        raise MigrationError(f"rewritten config does not parse: {exc}", "PROMOTION_PATH_CONFLICT") from exc
    if _jsonable(reparsed) != expected_after:
        raise MigrationError(
            "config cannot be rewritten in place to exactly the previewed mapping; "
            "point the four grounding documents at docs/grounding/current/<name>.md by hand",
            "PROMOTION_PATH_CONFLICT",
        )
    return rendered.encode("utf-8")


def _completed_migration(root: Path) -> dict[str, Any] | None:
    """The committed migration this campaign already has, if any.

    A migrated campaign (active, or an absent baseline awaiting its first
    publication) must report that state on a repeated preview or apply instead
    of planning a second migration over its own aliases and rewritten config.
    """
    if (root / PENDING_RELATIVE).exists():
        return None
    layout_path = root / GROUNDING_RELATIVE / "layout.json"
    if layout_path.is_symlink() or not layout_path.is_file():
        return None
    try:
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(layout, dict) or layout.get("version") != 1 or layout.get("state") not in {"active", "absent"}:
        return None
    operation = layout.get("migration_operation_id")
    try:
        TypeAdapter(OpaqueId).validate_python(operation, strict=True)
    except ValidationError:
        return None
    receipt_path = root / GROUNDING_RELATIVE / "migrations" / operation / "receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        return None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(receipt, dict) or receipt.get("state") != "committed":
        return None
    return {
        "state": "migrated",
        "already_migrated": True,
        "layout_state": layout.get("state"),
        "baseline": receipt.get("baseline"),
        "operation_id": operation,
        "plan_sha256": receipt.get("plan_sha256"),
        "generation_id": layout.get("generation_id"),
        "receipt": receipt,
    }


def _members(root: Path) -> list[dict[str, Any]]:
    docs = root / "docs"
    values = []
    for name in MANAGED_FILES:
        path = docs / name
        if path.is_symlink() or not path.is_file():
            raise MigrationError(f"legacy grounding bundle is incomplete: missing regular file docs/{name}")
        data = path.read_bytes()
        values.append({"path": name, "sha256": _sha(data), "size": len(data)})
    reference = docs / "reference"
    if reference.is_symlink() or not reference.is_dir():
        raise MigrationError("legacy grounding bundle is incomplete: missing regular docs/reference directory")
    seen: set[str] = set()
    folded: set[str] = set()
    for item in sorted(reference.rglob("*")):
        if item.is_symlink():
            raise MigrationError(f"legacy reference contains unsupported symlink: {item}", "PROMOTION_PATH_CONFLICT")
        if item.is_file():
            rel = f"reference/{item.relative_to(reference).as_posix()}"
            if rel in seen or rel.casefold() in folded:
                raise MigrationError(f"legacy reference has colliding member: {rel}", "PROMOTION_PATH_CONFLICT")
            seen.add(rel); folded.add(rel.casefold())
            data = item.read_bytes()
            values.append({"path": rel, "sha256": _sha(data), "size": len(data)})
        elif not item.is_dir():
            raise MigrationError(f"legacy reference contains unsupported special file: {item}", "PROMOTION_PATH_CONFLICT")
    return values


def _baseline(root: Path) -> str:
    docs = root / "docs"
    present = [(docs / name).exists() or (docs / name).is_symlink() for name in MANAGED_ALIASES]
    if not any(present):
        return "absent"
    if not all(present):
        missing = [name for name, exists in zip(MANAGED_ALIASES, present) if not exists]
        raise MigrationError(f"legacy grounding bundle is incomplete; missing: {', '.join(missing)}")
    return "legacy_adoption"


def plan_migration(campaign_dir: Path) -> dict[str, Any]:
    root = _campaign_root(campaign_dir)
    completed = _completed_migration(root)
    if completed is not None:
        return completed
    config_path = root / CONFIG_RELATIVE
    if not config_path.is_file() or config_path.is_symlink():
        raise MigrationError(f"missing safe config: {config_path}", "PROMOTION_PATH_CONFLICT")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise MigrationError(f"unreadable config: {exc}", "PROMOTION_PATH_CONFLICT") from exc
    if not isinstance(config, dict):
        raise MigrationError("config must be a mapping", "PROMOTION_PATH_CONFLICT")
    baseline = _baseline(root)
    if baseline == "legacy_adoption":
        configured = {
            entry.get("label"): entry.get("path") for entry in config.get("documents", [])
            if isinstance(entry, dict)
        }
        expected = {name: f"../docs/{name}.md" for name in ("world_state", "campaign_state", "party", "planning")}
        if any(configured.get(label) != path for label, path in expected.items()):
            raise MigrationError("configured grounding documents do not identify the loose legacy bundle")
        from pipelines.summary_native.outline import load_outline
        for name in expected:
            text = (root / "docs" / f"{name}.md").read_text(encoding="utf-8")
            missing = [heading for heading in load_outline(name) if heading not in text]
            if missing:
                raise MigrationError(f"legacy {name} does not satisfy the generated outline")
    members = _members(root) if baseline == "legacy_adoption" else []
    aliases = []
    for name in MANAGED_ALIASES:
        path = root / "docs" / name
        aliases.append({
            "path": f"docs/{name}",
            "before": _identity(path, root),
            "after": {"kind": "symlink", "target": f"grounding/current/{name}"},
        })
    config_bytes = config_path.read_bytes()
    config_after = _config_after(config)
    config_after_bytes = _config_after_bytes(config_bytes, config_after)
    base = {
        "version": 1,
        "kind": "grounding_bundle_migration",
        "baseline": baseline,
        "config": {
            "path": CONFIG_RELATIVE.as_posix(),
            "before_sha256": _sha(config_bytes),
            "after": config_after,
            "after_sha256": _sha(config_after_bytes),
            "changes": [
                {"where": edit["where"], "before": edit["before"], "after": edit["after"]}
                for edit in _config_edits(config_bytes.decode("utf-8"))
            ],
        },
        "aliases": aliases,
        "members": members,
        "created_at": datetime.fromtimestamp(config_path.stat().st_mtime, timezone.utc).isoformat(),
    }
    digest = canonical_digest(base)
    base.update({
        "plan_sha256": digest,
        "operation_id": f"migration-{digest[:20]}",
        "generation_id": f"legacy-{digest[:20]}" if baseline == "legacy_adoption" else None,
    })
    return base


def _symlink_atomic(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.migration-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    os.symlink(target, temporary)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_tree_exact(source: Path, destination: Path) -> None:
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise MigrationError(f"conflicting retained tree: {destination}", "PROMOTION_PATH_CONFLICT")
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_symlink():
            raise MigrationError(f"retained tree contains unsupported symlink: {item}", "PROMOTION_PATH_CONFLICT")
        if item.is_dir():
            if target.is_symlink() or (target.exists() and not target.is_dir()):
                raise MigrationError(f"conflicting retained directory: {target}", "PROMOTION_PATH_CONFLICT")
            target.mkdir(exist_ok=True)
        elif item.is_file():
            _copy_file_exact(item, target)
        else:
            raise MigrationError(f"retained tree contains unsupported special file: {item}", "PROMOTION_PATH_CONFLICT")
    _fsync_directory(destination)


def _verify_tree_exact(source: Path, destination: Path) -> None:
    if _identity(source, source.parent) ["kind"] != "directory" or destination.is_symlink() or not destination.is_dir():
        raise MigrationError(f"retained tree is incomplete: {destination}", "PROMOTION_PATH_CONFLICT")
    source_members = {
        item.relative_to(source).as_posix(): _sha(item.read_bytes())
        for item in source.rglob("*") if item.is_file() and not item.is_symlink()
    }
    destination_members = {
        item.relative_to(destination).as_posix(): _sha(item.read_bytes())
        for item in destination.rglob("*") if item.is_file() and not item.is_symlink()
    }
    if source_members != destination_members:
        raise MigrationError(f"retained tree differs: {destination}", "PROMOTION_PATH_CONFLICT")


def _copy_file_exact(source: Path, destination: Path) -> None:
    if destination.exists():
        if destination.read_bytes() != source.read_bytes():
            raise MigrationError(f"conflicting retained copy: {destination}", "PROMOTION_PATH_CONFLICT")
        return
    atomic_write_bytes(destination, source.read_bytes(), mode=stat.S_IMODE(source.stat().st_mode))


def _intended_config(plan: dict[str, Any], original: bytes) -> bytes:
    """Recompute the planned config bytes from the retained original."""
    if "after_sha256" not in plan["config"]:
        # A plan journaled before in-place rewriting existed recovers with the
        # bytes it was written with.
        return yaml.safe_dump(plan["config"]["after"], sort_keys=True, allow_unicode=True).encode("utf-8")
    after = _config_after_bytes(original, plan["config"]["after"])
    expected = plan["config"].get("after_sha256")
    if expected is not None and _sha(after) != expected:
        raise MigrationError("config rewrite no longer matches the previewed bytes", "PROMOTION_STALE_PREVIEW")
    return after


def _alias_state_ok(root: Path, operation: Path, alias_plan: dict[str, Any]) -> bool:
    """Is a managed alias in a state this plan (or its recovery) can explain?

    Before, after, or absent with its exact original retained in
    ``originals/`` (the journaled gap between moving the loose file or tree
    aside and linking the alias). Anything else is someone else's bytes.
    """
    alias_path = root / alias_plan["path"]
    if (_matches_identity(alias_path, alias_plan["before"], root)
            or _matches_identity(alias_path, alias_plan["after"], root)):
        return True
    if os.path.lexists(alias_path) or alias_plan["before"].get("kind") not in {"file", "directory"}:
        return False
    retained = operation / "originals" / alias_plan["path"]
    try:
        return _matches_identity(retained, alias_plan["before"], root)
    except MigrationError:
        return False


def _write_phase(root: Path, pending: dict[str, Any], phase: str) -> None:
    pending = {**pending, "phase": phase}
    atomic_write_bytes(root / PENDING_RELATIVE, _json_bytes(pending))
    operation = root / GROUNDING_RELATIVE / "migrations" / pending["operation_id"]
    atomic_write_bytes(operation / "state.json", _json_bytes(pending))


def _failpoint(_phase: str) -> None:
    """Fault injection seam for process-boundary migration tests."""


def _manifest(root: Path, plan: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    generation_id = plan["generation_id"]
    values = dict(
        generation_id=generation_id, operation_id=plan["operation_id"],
        campaign_id=str(load_campaign_identity(root).campaign_id), selected_range=None,
        kind=GenerationKind.LEGACY_ADOPTION,
        members=tuple(ContentIdentity.model_validate(item) for item in plan["members"]),
        retained_records=(), external_dependencies=(),
        published_path=f"docs/grounding/generations/{generation_id}/published",
        live_path=f"docs/grounding/generations/{generation_id}/live",
        bundle_digest=None, analysis_digest=None, parent_activation_id=None,
        created_at=datetime.fromisoformat(plan["created_at"]), manifest_sha256="0" * 64,
    )
    provisional = GenerationManifest.model_validate(values)
    values["manifest_sha256"] = canonical_digest(provisional, exclude_fields=frozenset({"manifest_sha256"}))
    manifest = GenerationManifest.model_validate(values)
    data = canonical_bytes(manifest)
    return manifest.model_dump(mode="json"), data


def _apply_locked(root: Path, plan: dict[str, Any], *, recovering: bool = False) -> dict[str, Any]:
    grounding = root / GROUNDING_RELATIVE
    operation = grounding / "migrations" / plan["operation_id"]
    receipt_path = operation / "receipt.json"
    if receipt_path.is_file() and not (root / PENDING_RELATIVE).exists():
        return json.loads(receipt_path.read_text(encoding="utf-8"))
    pending = {
        "version": 1, "operation_id": plan["operation_id"],
        "plan_sha256": plan["plan_sha256"], "phase": "prepared",
    }
    operation.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(operation / "plan.json", _json_bytes(plan))
    _write_phase(root, pending, "prepared")
    _failpoint("prepared")

    for alias_plan in plan["aliases"]:
        if not _alias_state_ok(root, operation, alias_plan):
            raise MigrationError(f"managed path changed during migration: {alias_plan['path']}", "PROMOTION_STALE_PREVIEW")

    config_path = root / CONFIG_RELATIVE
    originals = operation / "originals"
    config_backup = originals / CONFIG_RELATIVE
    if config_backup.is_file():
        intended = _intended_config(plan, config_backup.read_bytes())
        if config_path.read_bytes() not in {config_backup.read_bytes(), intended}:
            raise MigrationError("config changed during migration", "PROMOTION_STALE_PREVIEW")
    else:
        _copy_file_exact(config_path, config_backup)
    if plan["baseline"] == "legacy_adoption":
        for name in MANAGED_FILES:
            source = root / "docs" / name
            backup = originals / "docs" / name
            if source.is_symlink() or not os.path.lexists(source):
                if not backup.is_file():
                    raise MigrationError(f"missing retained original for transitioned alias {name}")
            else:
                _copy_file_exact(source, backup)
        source_ref = root / "docs/reference"
        backup_ref = originals / "docs/reference"
        if source_ref.is_symlink() or not os.path.lexists(source_ref):
            if not backup_ref.is_dir():
                raise MigrationError("missing retained original reference tree")
        else:
            _copy_tree_exact(source_ref, backup_ref)
        _verify_tree_exact(
            source_ref if os.path.lexists(source_ref) and not source_ref.is_symlink() else backup_ref,
            backup_ref,
        )
    _write_phase(root, pending, "backed_up")
    _failpoint("backed_up")

    manifest_path: Path | None = None
    manifest_sha: str | None = None
    if plan["baseline"] == "legacy_adoption":
        generation = grounding / "generations" / plan["generation_id"]
        for tree_name in ("published", "live"):
            tree = generation / tree_name
            tree.mkdir(parents=True, exist_ok=True)
            for name in MANAGED_FILES:
                _copy_file_exact(originals / "docs" / name, tree / name)
            _copy_tree_exact(originals / "docs/reference", tree / "reference")
            _verify_tree_exact(originals / "docs/reference", tree / "reference")
        _manifest_value, manifest_bytes = _manifest(root, plan)
        manifest_path = generation / "manifest.json"
        atomic_write_bytes(manifest_path, manifest_bytes)
        manifest_sha = _sha(manifest_bytes)
        current = grounding / "current"
        if current.is_symlink():
            if os.readlink(current) != f"generations/{plan['generation_id']}/live":
                raise MigrationError("current pointer conflicts with migration plan", "PROMOTION_PATH_CONFLICT")
        elif current.exists():
            raise MigrationError("current pointer is not a symlink", "PROMOTION_PATH_CONFLICT")
        else:
            _symlink_atomic(current, f"generations/{plan['generation_id']}/live")
    atomic_write_bytes(grounding / "layout.json", _json_bytes({
        "version": 1, "state": "active" if plan["baseline"] == "legacy_adoption" else "absent",
        "generation_id": plan["generation_id"], "migration_operation_id": plan["operation_id"],
    }))
    _write_phase(root, pending, "generation_installed")
    _failpoint("generation_installed")

    if plan["baseline"] == "legacy_adoption":
        for name in MANAGED_ALIASES:
            alias = root / "docs" / name
            target = f"grounding/current/{name}"
            if alias.is_symlink():
                if os.readlink(alias) != target:
                    raise MigrationError(f"alias target conflict: {alias}", "PROMOTION_PATH_CONFLICT")
                continue
            if name == "reference" and os.path.lexists(alias):
                # A link cannot replace a non-empty directory in one rename,
                # so the tree is moved aside into the operation journal (never
                # deleted) and then linked. A crash in between leaves the
                # alias absent with the exact tree retained in originals/ and
                # displaced/, which recovery recognises and completes.
                displaced = operation / "displaced" / "docs" / name
                if os.path.lexists(displaced):
                    raise MigrationError(f"displaced reference tree already exists: {displaced}", "PROMOTION_PATH_CONFLICT")
                displaced.parent.mkdir(parents=True, exist_ok=True)
                os.rename(alias, displaced)
                _fsync_directory(alias.parent)
                _fsync_directory(displaced.parent)
                _failpoint("reference_displaced")
            # For a file alias this is one atomic rename of a link over the
            # loose file: there is no moment with neither present.
            _symlink_atomic(alias, target)
    _write_phase(root, pending, "aliases_installed")
    _failpoint("aliases_installed")

    after_config = _intended_config(plan, (originals / CONFIG_RELATIVE).read_bytes())
    if config_path.read_bytes() != after_config:
        # Recovery permits exactly the retained-before or intended-after bytes.
        if config_path.read_bytes() != (originals / CONFIG_RELATIVE).read_bytes():
            raise MigrationError("config changed during migration", "PROMOTION_STALE_PREVIEW")
        atomic_write_bytes(config_path, after_config)
    _write_phase(root, pending, "config_installed")
    _failpoint("config_installed")

    if plan["baseline"] == "legacy_adoption":
        for alias_plan in plan["aliases"]:
            if not _matches_identity(root / alias_plan["path"], alias_plan["after"], root):
                raise MigrationError(f"alias verification failed: {alias_plan['path']}", "PROMOTION_PATH_CONFLICT")
        if config_path.read_bytes() != after_config:
            raise MigrationError("config verification failed", "PROMOTION_PATH_CONFLICT")
        expected_members = {item["path"]: item for item in plan["members"]}
        for tree_name in ("published", "live"):
            tree = grounding / "generations" / plan["generation_id"] / tree_name
            actual_members = {
                item.relative_to(tree).as_posix(): {
                    "sha256": _sha(item.read_bytes()), "size": item.stat().st_size,
                }
                for item in tree.rglob("*") if item.is_file() and not item.is_symlink()
            }
            if set(actual_members) != set(expected_members) or any(
                actual_members[path] != {"sha256": expected["sha256"], "size": expected["size"]}
                for path, expected in expected_members.items()
            ):
                raise MigrationError(f"{tree_name} generation verification failed", "PROMOTION_PATH_CONFLICT")

    activation_id = f"baseline-{plan['plan_sha256'][:20]}" if plan["baseline"] == "legacy_adoption" else None
    activation_path = grounding / "activations" / f"{activation_id}.json" if activation_id else None
    receipt_base = {
        "version": 1, "state": "committed", "operation_id": plan["operation_id"],
        "plan_sha256": plan["plan_sha256"], "baseline": plan["baseline"],
        "generation_id": plan["generation_id"],
        "manifest_path": manifest_path.relative_to(root).as_posix() if manifest_path else None,
        "activation_path": activation_path.relative_to(root).as_posix() if activation_path else None,
    }
    receipt_sha = canonical_digest(receipt_base)
    receipt = {**receipt_base, "receipt_sha256": receipt_sha}
    atomic_write_bytes(receipt_path, _json_bytes(receipt))
    _failpoint("receipt_installed")
    if plan["baseline"] == "legacy_adoption":
        assert activation_id is not None and activation_path is not None
        if activation_path.is_file():
            existing = ActivationRecord.model_validate_json(activation_path.read_bytes())
            if existing.migration_receipt_sha256 != receipt_sha or existing.manifest_sha256 != manifest_sha:
                raise MigrationError("legacy baseline activation conflicts with migration", "PROMOTION_PATH_CONFLICT")
        else:
            activation = ActivationRecord(
                activation_id=activation_id, operation_id=plan["operation_id"],
                generation_id=plan["generation_id"], manifest_sha256=manifest_sha,
                migration_receipt_sha256=receipt_sha, parent_activation_id=None,
                parent_activation_sha256=None, baseline_kind=BaselineKind.LEGACY_BASELINE,
                previous_snapshot_sha256=None, actor="grounding-bundle-migrator",
                completed_at=datetime.now(timezone.utc),
            )
            atomic_write_bytes(activation_path, _json_bytes(activation.model_dump(mode="json")))
    _failpoint("activation_installed")
    _fsync_directory(receipt_path.parent)
    if activation_path is not None:
        _fsync_directory(activation_path.parent)
    (root / PENDING_RELATIVE).unlink()
    _fsync_directory((root / PENDING_RELATIVE).parent)
    atomic_write_bytes(operation / "state.json", _json_bytes({**pending, "phase": "committed", "state": "committed"}))
    return receipt


def apply_migration(campaign_dir: Path, plan_sha256: str) -> dict[str, Any]:
    root = _campaign_root(campaign_dir)
    with authority_lock(root, exclusive=True, create=False):
        require_no_pending_transaction(root)
        validate_ledger_tip(root)
        migrations = root / GROUNDING_RELATIVE / "migrations"
        for candidate in sorted(migrations.glob("*/receipt.json")) if migrations.is_dir() else ():
            try:
                receipt = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if receipt.get("state") == "committed" and receipt.get("plan_sha256") == plan_sha256:
                return receipt
        completed = _completed_migration(root)
        if completed is not None:
            return completed
        try:
            plan = plan_migration(root)
        except MigrationError as exc:
            raise MigrationError("migration inputs changed after preview", "PROMOTION_STALE_PREVIEW") from exc
        if plan["plan_sha256"] != plan_sha256:
            raise MigrationError("migration inputs changed after preview", "PROMOTION_STALE_PREVIEW")
        return _apply_locked(root, plan)


def recover_migration(campaign_dir: Path, operation_id: str) -> dict[str, Any]:
    root = _campaign_root(campaign_dir)
    try:
        TypeAdapter(OpaqueId).validate_python(operation_id, strict=True)
    except ValidationError as exc:
        raise MigrationError("invalid migration operation id", "PROMOTION_PATH_CONFLICT") from exc
    with authority_lock(root, exclusive=True, create=False):
        pending_path = root / PENDING_RELATIVE
        if not pending_path.is_file():
            receipt = root / GROUNDING_RELATIVE / "migrations" / operation_id / "receipt.json"
            if receipt.is_file():
                return json.loads(receipt.read_text(encoding="utf-8"))
            raise MigrationError("no pending migration operation", "PROMOTION_PATH_CONFLICT")
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        if pending.get("operation_id") != operation_id:
            raise MigrationError("pending migration operation does not match", "PROMOTION_PATH_CONFLICT")
        plan_path = root / GROUNDING_RELATIVE / "migrations" / operation_id / "plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if canonical_digest({k: v for k, v in plan.items() if k not in {"plan_sha256", "operation_id", "generation_id"}}) != plan["plan_sha256"]:
            raise MigrationError("saved migration plan is corrupt", "PROMOTION_PATH_CONFLICT")
        return _apply_locked(root, plan, recovering=True)


def status(campaign_dir: Path) -> dict[str, Any]:
    root = _campaign_root(campaign_dir)
    pending = root / PENDING_RELATIVE
    if pending.is_file():
        try:
            value = json.loads(pending.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        return {"state": "recovery_required", "operation_id": value.get("operation_id"), "phase": value.get("phase")}
    layout = root / GROUNDING_RELATIVE / "layout.json"
    if not layout.is_file():
        return {"state": "migration_required"}
    try:
        value = json.loads(layout.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "invalid", "code": "PROMOTION_PATH_CONFLICT"}
    return {"state": value.get("state", "invalid"), "generation_id": value.get("generation_id"), "operation_id": value.get("migration_operation_id")}


def verify_migration(campaign_dir: Path) -> dict[str, Any]:
    root = _campaign_root(campaign_dir)
    state = status(root)
    if state["state"] not in {"active", "absent"}:
        return {"valid": False, **state}
    if state["state"] == "absent":
        clean = not any((root / "docs" / name).exists() or (root / "docs" / name).is_symlink() for name in MANAGED_ALIASES)
        receipt = root / GROUNDING_RELATIVE / "migrations" / str(state.get("operation_id")) / "receipt.json"
        return {"valid": clean and receipt.is_file(), **state}
    grounding = root / GROUNDING_RELATIVE
    current = grounding / "current"
    expected_current = f"generations/{state['generation_id']}/live"
    problems = []
    if not current.is_symlink() or os.readlink(current) != expected_current:
        problems.append("current pointer mismatch")
    for name in MANAGED_ALIASES:
        alias = root / "docs" / name
        if not alias.is_symlink() or os.readlink(alias) != f"grounding/current/{name}":
            problems.append(f"alias mismatch: docs/{name}")
    current_live = grounding / expected_current
    for name in MANAGED_FILES:
        if not (current_live / name).is_file():
            problems.append(f"missing member: {name}")
    if not (current_live / "reference").is_dir():
        problems.append("missing reference tree")
    operation = state.get("operation_id")
    receipt = grounding / "migrations" / str(operation) / "receipt.json"
    receipt_value_full = None
    if receipt.is_file():
        try:
            receipt_value_full = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if receipt_value_full and receipt_value_full.get("baseline") == "absent":
        try:
            receipt_check = dict(receipt_value_full)
            claimed = receipt_check.pop("receipt_sha256")
            if canonical_digest(receipt_check) != claimed:
                problems.append("migration receipt digest mismatch")
        except (KeyError, TypeError):
            problems.append("invalid migration receipt")
        return {"valid": not problems, **state, "problems": problems}
    activation_path = root / receipt_value_full["activation_path"] if receipt_value_full and receipt_value_full.get("activation_path") else None
    if not receipt.is_file() or activation_path is None or not activation_path.is_file():
        problems.append("missing receipt or legacy baseline activation")
    baseline_generation = receipt_value_full.get("generation_id") if receipt_value_full else state["generation_id"]
    live = grounding / "generations" / str(baseline_generation) / "live"
    published = live.parent / "published"
    manifest_path = live.parent / "manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        for member in manifest.get("members", []):
            relative = PurePosixPath(member["path"])
            for tree in (live, published):
                path = tree.joinpath(*relative.parts)
                if not path.is_file() or _sha(path.read_bytes()) != member["sha256"]:
                    problems.append(f"member hash mismatch: {tree.name}/{relative.as_posix()}")
    except (OSError, ValueError, KeyError, TypeError):
        problems.append("invalid generation manifest")
        manifest_bytes = b""
    if receipt.is_file() and activation_path is not None and activation_path.is_file():
        try:
            receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
            claimed = receipt_value.pop("receipt_sha256")
            if canonical_digest(receipt_value) != claimed:
                problems.append("migration receipt digest mismatch")
            record = ActivationRecord.model_validate_json(activation_path.read_bytes())
            if record.migration_receipt_sha256 != claimed or record.manifest_sha256 != _sha(manifest_bytes):
                problems.append("legacy baseline activation binding mismatch")
        except (OSError, ValueError, KeyError, TypeError):
            problems.append("invalid receipt or legacy baseline activation")
    return {"valid": not problems, **state, "problems": problems}


def _envelope(ok: bool, code: str, message: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": ok, "code": code, "message": message, "artifacts": [], "data": data}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="migrate_grounding_bundle")
    parser.add_argument("--campaign-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--plan-sha256")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--recover", action="store_true")
    parser.add_argument("--operation")
    parser.add_argument("--json", action="store_true")
    return parser


def _prerequisite_guidance(root: Path, code: str) -> str:
    """Name the exact commands a refused prerequisite needs, in order."""
    if code not in {"AUTH_LOCK_MISSING", "REVIEW_NOT_INITIALIZED", "REVIEW_AUTHORITY_REQUIRED"}:
        return ""
    steps = []
    if not (root / "docs" / "authority.yaml").is_file():
        steps.append(f"summary_native authority init --campaign-dir {root} --json")
    # review init is idempotent once storage exists, and it is the command that
    # creates docs/authority/.lock, so a missing lock always names it.
    if code == "AUTH_LOCK_MISSING" or not (root / "docs" / "reviews" / "campaign.json").is_file():
        steps.append(f"summary_native review init --campaign-dir {root} --json")
    if not steps:
        return ""
    return (
        "; initialize the campaign's authority and review storage first: "
        + " then ".join(f"`{step}`" for step in steps)
        + f", then preview again with `migrate_grounding_bundle --campaign-dir {root} --dry-run --json`"
    )


def main(argv: list[str] | None = None) -> int:
    from pipelines.summary_native.authority import AuthorityError
    from pipelines.summary_native.promotion.errors import PromotionError
    from pipelines.summary_native.review.store import ReviewStoreError

    args = _parser().parse_args(argv)
    try:
        if args.dry_run:
            data = plan_migration(args.campaign_dir)
        elif args.plan_sha256:
            data = apply_migration(args.campaign_dir, args.plan_sha256)
        elif args.status:
            data = status(args.campaign_dir)
        elif args.verify:
            data = verify_migration(args.campaign_dir)
        else:
            if not args.operation:
                raise MigrationError("--recover requires --operation", "PROMOTION_PATH_CONFLICT")
            data = recover_migration(args.campaign_dir, args.operation)
        if isinstance(data, dict) and data.get("already_migrated"):
            message = (
                "migration already complete; nothing to apply"
                + (" (no published generation yet: run `summary_native promote`)"
                   if data.get("layout_state") == "absent" else "")
            )
            print(json.dumps(_envelope(True, "PROMOTION_MIGRATION_COMPLETE", message, data), sort_keys=True))
            return 0
        print(json.dumps(_envelope(True, "OK", "migration inspection complete", data), sort_keys=True))
        return 0
    except (MigrationError, AuthorityError, ReviewStoreError, PromotionError) as exc:
        code = getattr(exc, "code", None) or "PROMOTION_MIGRATION_REQUIRED"
        try:
            guidance = _prerequisite_guidance(Path(args.campaign_dir).expanduser().absolute(), code)
        except OSError:
            guidance = ""
        print(json.dumps(_envelope(False, code, f"{exc}{guidance}", {}), sort_keys=True))
        return 2 if code == "PROMOTION_PATH_CONFLICT" else 3


if __name__ == "__main__":
    sys.exit(main())
