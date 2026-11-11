"""Verified canonical -> worktree/artifact transfer (T080, FR-022).

The review store refuses a campaign whose ``docs/reviews/campaign.json`` names another root
(``REVIEW_CAMPAIGN_MOVED``). A transfer is made usable by a
*separate* binding record, written in the worktree, that says "this copy was verified to carry the
canonical campaign's identity". Review storage revalidates this proof before accepting
a moved root. Nothing here writes ``campaign.json``; identity bytes are read only. No model call.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .errors import EXIT_REFUSAL, EXIT_STALE, DeltaRefusal
from .plan import DELTA_ROOT_REL
from .records_io import read_json, write_json

TRANSFER_REL = f"{DELTA_ROOT_REL}/transfer"
IDENTITY_REL = "docs/reviews/campaign.json"
BINDING_VERSION = 1
_BINDING_RE = re.compile(r"^binding-(\d+)\.json$")


@dataclass(frozen=True)
class TransferVerification:
    campaign_id: str
    canonical_root: str
    worktree_root: str
    identity_sha256: str
    plans_checked: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"campaign_id": self.campaign_id, "canonical_root": self.canonical_root,
                "worktree_root": self.worktree_root, "identity_sha256": self.identity_sha256,
                "plans_checked": list(self.plans_checked)}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_identity(root: Path, label: str) -> tuple[str, str, str]:
    """(campaign_id, canonical_root, sha256-of-bytes) read directly; the moved-guard is not consulted."""
    path = Path(root) / IDENTITY_REL
    if path.is_symlink() or not path.is_file():
        raise DeltaRefusal(f"the {label} has no campaign identity ({IDENTITY_REL}); initialise it with "
                           "`summary_native review init` in the canonical campaign", EXIT_REFUSAL)
    raw_bytes = path.read_bytes()
    try:
        raw = json.loads(raw_bytes)
        if not isinstance(raw, dict) or set(raw) != {"version", "campaign_id", "canonical_root"} or raw["version"] != 1:
            raise ValueError("unsupported identity fields")
        cid = str(uuid.UUID(raw["campaign_id"]))
        croot = raw["canonical_root"]
        if not isinstance(croot, str):
            raise ValueError("canonical_root")
    except (ValueError, TypeError, KeyError) as exc:
        raise DeltaRefusal(f"the {label}'s campaign identity is unreadable ({exc})", EXIT_REFUSAL) from exc
    return cid, croot, _sha(raw_bytes)


def _canonical_identity(canonical_dir: Path) -> tuple[str, str, str]:
    cid, croot, digest = _read_identity(canonical_dir, "canonical campaign")
    if croot != str(Path(canonical_dir).resolve()):
        raise DeltaRefusal(f"{canonical_dir} is not the canonical campaign: its identity names {croot}", EXIT_REFUSAL)
    return cid, croot, digest


def _plan_identities(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    pdir = Path(root) / DELTA_ROOT_REL / "plans"
    for p in sorted(pdir.glob("*.json")) if pdir.is_dir() else []:
        try:
            out[p.stem] = str(read_json(p).get("campaign_identity", ""))
        except (OSError, ValueError):
            raise DeltaRefusal(f"plan record {p} is unreadable; cannot verify the transfer", EXIT_REFUSAL)
    return out


def verify(canonical_dir: Path | str, worktree_dir: Path | str) -> TransferVerification:
    canonical, worktree = Path(canonical_dir).resolve(), Path(worktree_dir).resolve()
    if canonical == worktree:
        raise DeltaRefusal("the worktree is the canonical campaign; there is nothing to transfer", EXIT_REFUSAL)
    cid, croot, digest = _canonical_identity(canonical)
    wid, wroot, wdigest = _read_identity(worktree, "worktree")
    if wid != cid or wroot != croot or wdigest != digest:
        raise DeltaRefusal(
            f"unverified transfer: the worktree's campaign identity ({wid}, root {wroot}) is not the canonical "
            f"campaign's ({cid}, root {croot})", EXIT_REFUSAL)
    plans = _plan_identities(worktree)
    bad = sorted(pid for pid, ident in plans.items() if ident != cid)
    if bad:
        raise DeltaRefusal(f"unverified transfer: plan(s) {', '.join(bad)} carry a different campaign identity "
                           f"than the canonical campaign {cid}", EXIT_REFUSAL)
    return TransferVerification(cid, croot, str(worktree), digest, tuple(sorted(plans)))


def transfer_dir(worktree_dir: Path | str) -> Path:
    return Path(worktree_dir).resolve() / TRANSFER_REL


def _record_digest(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    return _sha(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def _binding_files(worktree: Path) -> list[tuple[int, Path]]:
    d = transfer_dir(worktree)
    found = [(int(m.group(1)), p) for p in d.glob("binding-*.json") if (m := _BINDING_RE.match(p.name))] if d.is_dir() else []
    return sorted(found)


def bind(canonical_dir: Path | str, worktree_dir: Path | str) -> Path:
    """Verify, then write ``binding-<n>.json`` in the worktree.  Never writes ``campaign.json``."""
    v = verify(canonical_dir, worktree_dir)
    worktree = Path(worktree_dir).resolve()
    existing = _binding_files(worktree)
    for _, p in existing:
        try:
            rec = read_json(p)
        except (OSError, ValueError):
            continue
        if (rec.get("campaign_id"), rec.get("canonical_root"), rec.get("worktree_root"), rec.get("identity_sha256")) == \
                (v.campaign_id, v.canonical_root, v.worktree_root, v.identity_sha256) and rec.get("record_sha256") == _record_digest(rec):
            return p
    n = (existing[-1][0] + 1) if existing else 1
    rec = {"version": BINDING_VERSION, "campaign_id": v.campaign_id, "canonical_root": v.canonical_root,
           "worktree_root": v.worktree_root, "identity_sha256": v.identity_sha256}
    rec["record_sha256"] = _record_digest(rec)
    return write_json(transfer_dir(worktree) / f"binding-{n}.json", rec)


def bound_identity(worktree_dir: Path | str) -> str:
    """The canonical campaign id a worktree is verifiably bound to; refuses when unbound or tampered.

    Tampered or foreign binding: exit 1.  The identity file changed since binding: exit 3 (stale).
    """
    worktree = Path(worktree_dir).resolve()
    files = _binding_files(worktree)
    if not files:
        raise DeltaRefusal(f"{worktree} is not bound to a canonical campaign; run `summary_native delta transfer bind "
                           "--canonical DIR`", EXIT_REFUSAL)
    try:
        rec = read_json(files[-1][1])
    except (OSError, ValueError) as exc:
        raise DeltaRefusal(f"binding record is unreadable ({exc})", EXIT_REFUSAL) from exc
    if rec.get("record_sha256") != _record_digest(rec) or rec.get("version") != BINDING_VERSION:
        raise DeltaRefusal("the transfer binding record was altered after it was written; re-run `delta transfer bind`",
                           EXIT_REFUSAL)
    if rec.get("worktree_root") != str(worktree):
        raise DeltaRefusal(f"the binding was made for {rec.get('worktree_root')}, not {worktree}", EXIT_REFUSAL)
    cid, croot, digest = _read_identity(worktree, "worktree")
    if digest != rec["identity_sha256"] or cid != rec["campaign_id"]:
        raise DeltaRefusal("the campaign identity changed since the transfer was bound; re-verify with "
                           "`delta transfer verify --canonical DIR`", EXIT_STALE)
    proof = verify(rec["canonical_root"], worktree)
    if croot != rec["canonical_root"] or proof.campaign_id != cid:
        raise DeltaRefusal("the transfer no longer matches the canonical campaign", EXIT_REFUSAL)
    return cid
