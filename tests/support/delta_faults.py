"""Fault injection for spec 039 resume tests (T065).

``inject(boundary)`` makes the real seam function at that boundary raise ``InjectedFault`` -- a
``BaseException``, so nothing in the code under test can catch it as an ordinary error; it behaves like
the process dying at that point.  Boundaries (in the order a delta run meets them):

``evidence_write``     the evidence pack for a member is about to be written
``model_output``       the model answered; the answer is lost
``verify``             sparse verification of the drafts
``review_creation``    the review that carries the sign-offs is being created
``sign_off``           the sign-off decision is being recorded
``first_publish``      the first member is rendered, nothing written yet
``target_before_log``  the dossier target is written, the publish log is not
``log_before_receipt`` target and log are written, the member receipt is not
``receipt_creation``   the run's completion receipt is being created
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from pathlib import Path
from unittest import mock

BOUNDARIES = ("evidence_write", "model_output", "verify", "review_creation", "sign_off", "first_publish",
              "target_before_log", "log_before_receipt", "receipt_creation")


class InjectedFault(BaseException):
    """A simulated crash.  Not an ``Exception``: ``except Exception`` handlers must not swallow it."""


def _raiser(boundary: str):
    def boom(*args, **kwargs):
        raise InjectedFault(boundary)
    return boom


@contextlib.contextmanager
def inject(boundary: str):
    if boundary not in BOUNDARIES:
        raise ValueError(f"unknown boundary {boundary!r}; one of {BOUNDARIES}")
    from pipelines.summary_native import npc_draft, npc_publish
    from pipelines.summary_native.delta import npc_update, receipt
    from pipelines.summary_native.review import cli as review_cli

    with contextlib.ExitStack() as stack:
        patch = lambda obj, name, new: stack.enter_context(mock.patch.object(obj, name, new))  # noqa: E731
        if boundary == "evidence_write":
            patch(npc_update, "render_pack", _raiser(boundary))
        elif boundary == "model_output":
            inner = npc_draft.stream_api

            def answered_then_lost(*a, **k):
                inner(*a, **k)
                raise InjectedFault(boundary)
            patch(npc_draft, "stream_api", answered_then_lost)
        elif boundary == "verify":
            patch(npc_update, "verify", _raiser(boundary))
        elif boundary == "review_creation":
            patch(review_cli, "create_review", _raiser(boundary))
        elif boundary == "sign_off":
            patch(review_cli, "save_decisions", _raiser(boundary))
        elif boundary == "first_publish":
            patch(npc_publish, "render_published", _raiser(boundary))
        elif boundary == "target_before_log":
            patch(npc_publish, "write_publish_log", _raiser(boundary))
        elif boundary == "log_before_receipt":
            real_put = npc_publish._put

            def put(path, text):
                p = Path(path)
                if p.parent.name == "receipts" and not p.name.endswith(".intent.json"):
                    try:
                        published = json.loads(text).get("outcome") == "published"
                    except ValueError:
                        published = False
                    if published:
                        raise InjectedFault(boundary)
                return real_put(path, text)
            patch(npc_publish, "_put", put)
        elif boundary == "receipt_creation":
            patch(receipt, "save_receipt", _raiser(boundary))
        yield


def authority_fingerprint(root: Path) -> dict[str, str]:
    """Every file under the authority ledger and the review store, by digest (locks excluded).

    Equal before and after means no approval, decision or review was created or changed.
    """
    out: dict[str, str] = {}
    for sub in ("docs/authority", "docs/reviews"):
        base = Path(root) / sub
        for p in sorted(base.rglob("*")) if base.is_dir() else []:
            if p.is_file() and "lock" not in p.name:
                out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def tree_snapshot(root: Path, *subdirs: str) -> dict[str, tuple[int, str]]:
    """``{path: (mtime_ns, sha256)}`` for every file under ``subdirs``: proves "no content write"."""
    snap: dict[str, tuple[int, str]] = {}
    for sub in subdirs:
        for p in sorted((Path(root) / sub).rglob("*")):
            if p.is_file():
                snap[p.relative_to(root).as_posix()] = (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return snap
