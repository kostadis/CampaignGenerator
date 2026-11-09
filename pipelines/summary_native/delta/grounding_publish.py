"""Digest-bound grounding preview and apply (spec 039 FR-016/020/021).

``preview`` hashes the exact bytes of every candidate document, the delta lineage record and the plan
digest. ``apply`` re-reads them from disk, recomputes the hash and refuses with exit 3 if it differs
from the one the GM confirmed. The actual publication is delegated to the existing promotion path
(``promotion.cli`` -> ``publish_bundle`` and whole-generation activation); nothing here reimplements
activation, and no synthetic full-corpus ``synth`` record is ever written (FR-021). No model call.

On-disk inputs, under ``<campaign>/docs/summaries/delta/grounding/<plan_id>/`` (the same plan-scoped
directory ``grounding_edits`` keeps ``proposals-rN`` / ``decisions-rN`` / ``check-rN`` in):

* ``candidates/<doc>.md``   one file per candidate grounding document
* ``lineage.json``          the :class:`DeltaLineageRecord`
* ``publish_request.json``  optional arguments for the delegated promotion run
                            (``config``, ``out_root``, ``since``, ``until``, ``review``,
                            ``check_report``, ``request_id``); it is part of the preview hash
* ``preview.json``          written by ``preview``
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict

from .errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .lineage import DeltaLineageRecord, delta_record_problems, load_lineage
from .grounding_candidates import CANDIDATES_DIR, LINEAGE_FILE, _range_name, require_check_binding
from .grounding_edits import edits_dir
from .plan import DeltaPlan, plan_digest

PUBLISH_REQUEST_FILE = "publish_request.json"
PREVIEW_FILE = "preview.json"

Publisher = Callable[[Path, DeltaPlan, dict[str, Any]], dict[str, Any]]


class PreviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    plan_sha256: str
    candidates: dict[str, str]  # name -> sha256 of exact bytes
    lineage_sha256: str
    request_sha256: str
    staged_sha256: str = "unstaged"
    complete: bool
    problems: list[str]
    preview_sha256: str


def grounding_dir(campaign_dir: Path | str, plan_id: str) -> Path:
    return edits_dir(campaign_dir, plan_id)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lineage_bytes(lineage: DeltaLineageRecord) -> bytes:
    return json.dumps(lineage.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_inputs(campaign_dir: Path | str, plan_id: str) -> tuple[dict[str, bytes], DeltaLineageRecord, bytes]:
    base = grounding_dir(campaign_dir, plan_id)
    cand_dir = base / CANDIDATES_DIR
    candidates = {p.name: p.read_bytes() for p in sorted(cand_dir.glob("*.md"))} if cand_dir.is_dir() else {}
    if not candidates:
        raise DeltaRefusal(f"no candidate documents under {cand_dir}", EXIT_USAGE)
    lineage_path = base / LINEAGE_FILE
    if not lineage_path.is_file():
        raise DeltaRefusal(f"no lineage record at {lineage_path}", EXIT_USAGE)
    request = base / PUBLISH_REQUEST_FILE
    return candidates, load_lineage(lineage_path), request.read_bytes() if request.is_file() else b""


def staged_tree_sha(campaign_dir: Path | str | None, request_bytes: bytes) -> str:
    """Digest of the staged promotion tree the publisher will actually read: the range directory's
    manifest, staged drafts, copied ``reference/**``, run-record pointers and staging marker.

    ``unstaged`` when the request names no range (nothing was staged); ``absent`` when it names one that is
    not on disk.  Hashing the tree, not only ``candidates/``, is what makes a hand-edit of a staged draft
    after the preview a stale-preview refusal (exit 3) instead of publishing bytes the GM never confirmed.
    """
    try:
        request = json.loads(request_bytes) if request_bytes else {}
    except ValueError:
        return "unstaged"
    out_root, since, until = request.get("out_root"), request.get("since"), request.get("until")
    if campaign_dir is None or not out_root or since is None or until is None:
        return "unstaged"
    range_dir = Path(campaign_dir).absolute() / out_root / _range_name(int(since), int(until))
    if not range_dir.is_dir():
        return "absent"
    entries = {p.relative_to(range_dir).as_posix(): _sha(p.read_bytes())
               for p in sorted(range_dir.rglob("*")) if p.is_file() and not p.name.endswith(".tmp")}
    return _sha(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _combine(plan_sha: str, candidates: dict[str, bytes], lineage_sha: str, request_sha: str,
             staged_sha: str = "unstaged") -> tuple[dict[str, str], str]:
    digests = {name: _sha(data) for name, data in sorted(candidates.items())}
    body = json.dumps(
        {"plan": plan_sha, "candidates": digests, "lineage": lineage_sha, "request": request_sha,
         "staged": staged_sha},
        sort_keys=True, separators=(",", ":"),
    )
    return digests, _sha(body.encode("utf-8"))


def preview(plan: DeltaPlan, candidates: dict[str, bytes], lineage: DeltaLineageRecord,
            request: bytes = b"", *, campaign_dir: Path | str | None = None) -> PreviewRecord:
    plan_sha = plan_digest(plan)
    lineage_sha = _sha(lineage_bytes(lineage))
    request_sha = _sha(request)
    staged_sha = staged_tree_sha(campaign_dir, request)
    digests, total = _combine(plan_sha, candidates, lineage_sha, request_sha, staged_sha)
    problems = delta_record_problems(lineage, Path(campaign_dir) if campaign_dir else None)
    return PreviewRecord(
        plan_id=plan.plan_id, plan_sha256=plan_sha, candidates=digests, lineage_sha256=lineage_sha,
        request_sha256=request_sha, staged_sha256=staged_sha, complete=not problems, problems=problems, preview_sha256=total,
    )


def default_publisher(campaign_dir: Path, plan: DeltaPlan, request: dict[str, Any]) -> dict[str, Any]:
    """Delegate to ``promotion.cli.run``: dry-run for its own preview digest, then commit it."""
    from pipelines.summary_native.promotion import cli as promotion_cli

    missing = [k for k in ("since", "until", "review", "check_report") if k not in request]
    if missing:
        raise DeltaRefusal(f"{PUBLISH_REQUEST_FILE} lacks {', '.join(missing)}", EXIT_USAGE)
    from pipelines.summary_native.promotion.publish import committed_replay, joined_receipt

    replayed = committed_replay(campaign_dir, request.get("request_id") or f"delta-{plan.plan_id}")
    if replayed is not None:  # FR-017: an identical repeat is a no-op that returns the original receipt, no write
        joined = joined_receipt(campaign_dir, replayed[1].activation_id)
        return {"receipt": joined.get("receipt", joined.get("publication")), "activation": joined["activation"]}
    base = dict(config=request.get("config"), since=request["since"], until=request["until"],
                out_root=request.get("out_root"), review=request["review"],
                check_report=request["check_report"], json=True)

    def run(**extra: Any) -> tuple[int, dict[str, Any]]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = promotion_cli.run(argparse.Namespace(**base, **extra))
        try:
            return code, json.loads(buf.getvalue() or "{}")
        except ValueError:
            return code, {}

    code, dry = run(dry_run=True, preview_sha256=None, request_id=None)
    if code != 0:
        raise DeltaRefusal(f"promotion preview refused: {dry.get('message', 'blocked')}", EXIT_REFUSAL)
    sha = dry["data"]["preview"]["preview_sha256"]
    request_id = request.get("request_id") or f"delta-{plan.plan_id}"
    code, done = run(dry_run=False, preview_sha256=sha, request_id=request_id)
    if code != 0:
        raise DeltaRefusal(f"promotion refused: {done.get('message', 'failed')}", EXIT_STALE if code == 3 else EXIT_REFUSAL)
    return done.get("data", {})


def apply(plan: DeltaPlan, preview_sha: str, *, campaign_dir: Path | str,
          publisher: Publisher | None = None) -> dict[str, Any]:
    campaign = Path(campaign_dir)
    candidates, lineage, request_bytes = load_inputs(campaign, plan.plan_id)
    from .review_binding import require_fresh

    require_fresh(campaign, plan, "grounding", required=True)  # exit 1 with no review binding; exit 3 naming a bound hash that changed since review (FR-020)
    current = preview(plan, candidates, lineage, request_bytes, campaign_dir=campaign)
    if current.preview_sha256 != preview_sha:
        raise DeltaRefusal(
            "preview is stale: candidates, lineage or plan changed since the preview was confirmed; "
            "preview again and confirm the new hash",
            EXIT_STALE,
        )
    if not current.complete:
        raise DeltaRefusal("lineage is incomplete: " + "; ".join(current.problems), EXIT_REFUSAL)
    require_check_binding(campaign, candidates, lineage)
    request = json.loads(request_bytes) if request_bytes else {}
    return (publisher or default_publisher)(campaign, plan, request)
