"""One authoritative YAML record, immutable evidence, and recoverable publication."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import shlex

import yaml
from campaignlib.util import atomic_write_bytes, atomic_write_text
from .models import Evidence, Workflow


class WorkflowError(ValueError):
    """An actionable refusal, safe to show in CLI and editor."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


class Store:
    def __init__(self, session: Path | str):
        self.session = Path(session).resolve(strict=True)
        if not self.session.is_dir():
            raise WorkflowError("session directory is required")
        self.path = self.session / "session_workflow.yaml"
        self.archive = self.session / ".session-workflow"

    def contained(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise WorkflowError("artifact paths must be nonempty session-relative paths")
        target = self.session / path
        if not target.resolve().is_relative_to(self.session):
            raise WorkflowError("artifact path escapes the session")
        if any(p.is_symlink() for p in [target, *target.parents] if p != self.session.parent):
            raise WorkflowError("symlink artifacts are not supported")
        return target

    @contextmanager
    def lock(self):
        with self.contained(".session-workflow.lock").open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def migration_command(self) -> str:
        return f"python -m session_doc.workflow.migrate --campaign-dir {shlex.quote(str(self.session.parent))} --session-dir {shlex.quote(self.session.name)}"

    def load(self) -> Workflow:
        if not self.path.exists():
            raise WorkflowError("no workflow record; initialize this session explicitly")
        raw = yaml.safe_load(self.contained("session_workflow.yaml").read_text())
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise WorkflowError(f"unsupported workflow state; inventory with: {self.migration_command()} --dry-run")
        try:
            return Workflow.model_validate(raw)
        except ValueError as exc:
            raise WorkflowError(f"invalid workflow state (unknown fields are not discarded): {exc}") from exc

    def save(self, state: Workflow, *, expected_revision: int):
        if self.path.exists() and self.load().revision != expected_revision:
            raise WorkflowError("stale workspace revision; reload before submitting")
        if self.contained(".session-workflow/transaction.yaml").exists():
            raise WorkflowError("interrupted application; run session_workflow recover first")
        state.revision = expected_revision + 1
        atomic_write_text(self.path, yaml.safe_dump(state.model_dump(mode="json"), sort_keys=False))

    def preserve(self, path: Path | str, *, label: str) -> Evidence:
        path = Path(path)
        if not path.is_absolute():
            path = self.contained(str(path))
        data = path.read_bytes()
        return self.preserve_bytes(data, path=str(path.relative_to(self.session)) if path.is_relative_to(self.session) else str(path), label=label)

    def preserve_bytes(self, data: bytes, *, path: str, label: str) -> Evidence:
        sha = digest(data)
        relative = f".session-workflow/objects/{sha}"
        target = self.contained(relative)
        if target.exists():
            if digest(target.read_bytes()) != sha:
                raise WorkflowError("preserved evidence is corrupt")
        else:
            atomic_write_bytes(target, data)
        return Evidence(path=path, sha256=sha, snapshot=relative, label=label)

    def bytes(self, evidence: Evidence) -> bytes:
        data = self.contained(evidence.snapshot).read_bytes()
        if digest(data) != evidence.sha256:
            raise WorkflowError(f"preserved evidence hash mismatch: {evidence.path}")
        return data

    def fresh(self, evidence: Evidence) -> bool:
        path = Path(evidence.path)
        if not path.is_absolute():
            path = self.contained(evidence.path)
        return path.is_file() and digest(path.read_bytes()) == evidence.sha256

    def publish(self, state: Workflow, writes: dict[str, Evidence], *, expected_revision: int):
        """Journal before touching targets; retry completes only exact expected bytes.

        All originals survive in the content store. A failed or killed replacement
        cannot erase the last approved version, including binary transcript bytes.
        """
        if self.load().revision != expected_revision:
            raise WorkflowError("stale workspace revision; reload before applying")
        journal_path = self.contained(".session-workflow/transaction.yaml")
        if journal_path.exists():
            raise WorkflowError("interrupted application; run session_workflow recover first")
        before = {}
        for relative, evidence in writes.items():
            target = self.contained(relative)
            self.bytes(evidence)
            before[relative] = self.preserve(target, label="derived").model_dump() if target.exists() else None
        state.revision = expected_revision + 1
        journal = {"before": before, "after": {k: v.model_dump() for k, v in writes.items()}, "state": state.model_dump(mode="json"), "expected_revision": expected_revision}
        atomic_write_text(journal_path, yaml.safe_dump(journal, sort_keys=False))
        self.recover()

    def recover(self):
        journal_path = self.contained(".session-workflow/transaction.yaml")
        if not journal_path.exists():
            return {"recovered": False}
        journal = yaml.safe_load(journal_path.read_text())
        state = Workflow.model_validate(journal["state"])
        current = self.load()
        if current.revision not in {journal["expected_revision"], state.revision}:
            raise WorkflowError("transaction revision conflict; inspect preserved originals")
        if current.revision == state.revision and fingerprint(current) != fingerprint(state):
            raise WorkflowError("transaction state conflict; inspect preserved originals")
        # Validate every target before completing any remaining replacement.
        for relative, after in journal["after"].items():
            target = self.contained(relative)
            actual = digest(target.read_bytes()) if target.exists() else None
            before = journal["before"][relative]
            if actual not in {before["sha256"] if before else None, after["sha256"]}:
                raise WorkflowError(f"recovery source mismatch: {relative}; originals preserved")
            self.bytes(Evidence.model_validate(after))
        for relative, after in journal["after"].items():
            atomic_write_bytes(self.contained(relative), self.bytes(Evidence.model_validate(after)))
        atomic_write_text(self.path, yaml.safe_dump(state.model_dump(mode="json"), sort_keys=False))
        receipt = self.contained(f".session-workflow/transactions/{state.revision}.yaml")
        atomic_write_bytes(receipt, journal_path.read_bytes())
        journal_path.unlink()
        return {"recovered": True, "revision": state.revision}
