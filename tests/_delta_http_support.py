"""Helpers for the delta HTTP tests (not collected: no ``test_`` prefix)."""

from __future__ import annotations

import contextlib
import io
import json
import re
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from pipelines.summary_native import cli as sn_cli
from server.main import app
from server.platform_config_service import PlatformConfigService

BASE = "/api/summary-native/delta"
_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")
_TS_KEYS = {"created_at", "started_at", "finished_at", "timestamp", "decided_at", "written_at", "at",
            "created", "updated_at", "generated_at", "completed_at", "run_id"}


def init_identity(root: Path) -> str:
    ident = root / "docs" / "reviews" / "campaign.json"
    ident.parent.mkdir(parents=True, exist_ok=True)
    cid = str(uuid.uuid4())
    ident.write_text(json.dumps({"version": 1, "campaign_id": cid, "canonical_root": str(root.resolve())}),
                     encoding="utf-8")
    return cid


def client_for(root: Path, monkeypatch) -> TestClient:
    """A fresh client whose active campaign is ``root`` (a new call is a 'restarted server')."""
    monkeypatch.chdir(root)
    monkeypatch.setattr(app.state, "platform", PlatformConfigService(root), raising=False)
    return TestClient(app)


def cli_json(argv: list[str]) -> tuple[int, object]:
    """Run the real CLI in-process and parse its one JSON stdout object."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = sn_cli.main(argv)
    text = buf.getvalue().strip()
    return code, (json.loads(text) if text else None)


def normalise(value, roots: tuple[Path, ...] = ()):
    """Drop timestamps and rebase each campaign root so two copies compare equal (SC-008)."""
    if isinstance(value, dict):
        return {k: normalise(v, roots) for k, v in value.items() if k not in _TS_KEYS}
    if isinstance(value, list):
        return [normalise(v, roots) for v in value]
    if isinstance(value, str):
        for r in roots:
            value = value.replace(str(r.resolve()), "<ROOT>").replace(str(r), "<ROOT>")
        return _TS.sub("<TS>", value)
    return value
