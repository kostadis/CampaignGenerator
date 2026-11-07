"""Unchanged attestation (spec 039 T052, FR-013, N5, #585).

"This dossier is still correct as of these added sources", recorded against the exact published
sha256 the GM looked at. It never edits the dossier: the original bytes and horizon stay.

Record: ``<campaign>/docs/npcs/summary_native/delta/attestations/<slug>-<sha12>-<n>.json``
(``npc_baseline.ATTESTATIONS_REL``); ``npc_baseline`` reads them back under ``attestations``.
Exit codes: missing reason -> 2; subject not published -> 1; publication digest differs from the
file now on disk (or from the log) -> 3.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pipelines.summary_native import npc_slug

from . import npc_baseline
from .errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .records_io import write_json

_SHA = re.compile(r"^[0-9a-f]{64}$")


class Attestation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    slug: str
    subject: str
    publication_sha256: str
    horizon: int | None = None  # the horizon the attestation does NOT change
    added_sources: list[dict] = Field(default_factory=list)  # [{path, sha256}]
    added_evidence: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    rulings: dict = Field(default_factory=dict)
    reason: str
    scope: str = "unchanged_through_added_sources"
    plan_id: str | None = None
    created_at: str


def attest(campaign_dir: Path | str, subject: str, *, reason: str, publication_sha256: str,
           added_sources: list[dict] | None = None, added_evidence: list[str] | None = None,
           links: list[str] | None = None, rulings: dict | None = None, plan_id: str | None = None,
           npc_root: Path | None = None, now: str | None = None) -> Attestation:
    root = Path(campaign_dir)
    if not (reason or "").strip():
        raise DeltaRefusal("an attestation needs the GM's reason; --reason is required and cannot be blank",
                           EXIT_USAGE)
    if not _SHA.fullmatch(publication_sha256 or ""):
        raise DeltaRefusal("--publication must be a full lowercase sha256", EXIT_USAGE)
    slug = npc_slug.slug_for(subject)
    nroot = Path(npc_root) if npc_root else npc_baseline.npc_root_for(root)
    bl = npc_baseline.baseline_for(root, slug, npc_root=nroot)
    if bl is None:
        raise DeltaRefusal(f"{subject}: not in the publish log; there is no publication to attest", EXIT_REFUSAL)
    current = bl.publication.get("body_sha256")
    if current != publication_sha256 or bl.publication.get("published_sha256") != publication_sha256:
        raise DeltaRefusal(
            f"{subject}: the published dossier is {str(current)[:12]}, not {publication_sha256[:12]}; "
            "the attestation is bound to the exact bytes you reviewed. Re-review and retry.", EXIT_STALE)
    if bl.status != "ok":
        raise DeltaRefusal(f"{subject}: baseline is {bl.status}; repair it before attesting", EXIT_REFUSAL)
    if added_evidence is None or rulings is None:
        d_ev, d_rul = derive_evidence_and_rulings(root, subject, plan_id)
        added_evidence = d_ev if added_evidence is None else added_evidence
        rulings = d_rul if rulings is None else rulings
    existing = npc_baseline.load_attestations(root, slug, publication_sha256)
    aid = f"att-{slug}-{publication_sha256[:12]}-{len(existing) + 1}"
    rec = Attestation(
        id=aid, slug=slug, subject=bl.subject, publication_sha256=publication_sha256, horizon=bl.horizon,
        added_sources=list(added_sources or []), added_evidence=list(added_evidence or []),
        links=list(links or []), rulings=dict(rulings or {}), reason=reason.strip(), plan_id=plan_id,
        created_at=now or datetime.now(timezone.utc).isoformat(timespec="seconds"))
    write_json(npc_baseline.attestations_dir(root) / f"{aid}.json", rec.model_dump(mode="json"))
    return rec


def covering_attestation(campaign_dir: Path | str, subject: str, plan, *, npc_root: Path | None = None) -> dict | None:
    """The attestation (if any) that lets ``subject`` stay unchanged through ``plan``'s sources (FR-013, #585).

    It must be bound to the dossier's CURRENT published sha256 (an attestation of bytes since
    replaced does not count) and its ``added_sources`` must carry every source sha the plan selected.
    The newest such attestation wins. Reads only; never creates one.
    """
    root = Path(campaign_dir)
    slug = npc_slug.slug_for(subject)
    bl = npc_baseline.baseline_for(root, slug, npc_root=npc_root)
    if bl is None or not bl.ok:
        return None
    current = bl.publication.get("published_sha256")
    wanted = {src.sha256 for src in plan.sources}
    for rec in reversed(npc_baseline.load_attestations(root, slug, current)):
        have = {str(a.get("sha256")) for a in rec.get("added_sources", []) if isinstance(a, dict)}
        if wanted and wanted <= have:
            return rec
    return None


def derive_evidence_and_rulings(campaign_dir: Path | str, subject: str, plan_id: str | None) -> tuple[list[str], dict]:
    """What the GM was shown when attesting: the census' evidence ids for the subject and its ruling."""
    if not plan_id:
        return [], {}
    from .census import census_path, load_census

    root = Path(campaign_dir)
    if not census_path(root, plan_id).is_file():
        return [], {}
    slug = npc_slug.slug_for(subject)
    for e in load_census(root, plan_id).entries:
        if e.slug == slug or e.subject.casefold() == subject.casefold():
            ev = sorted({f"ch{sp.chapter:03d}/{sp.kind}/{sp.id} ({sp.strength})" for sp in e.evidence})
            return ev, ({"ruling": e.ruling} if e.ruling else {})
    return [], {}
