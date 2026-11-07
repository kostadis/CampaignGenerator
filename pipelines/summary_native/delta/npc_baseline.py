"""Per-subject NPC baselines for a delta run (spec 039 T047, data-model NpcBaseline, N1).

A baseline is what was *published*, read from ``publish_log.json`` and the published file's own
header digest. It is never "the newest range folder": a newer draft the publish log does not name
is ignored. No model call.

Status is ``ok`` or ``repair_required:<reason>``. Reasons: ``target_missing``,
``hand_edited_target`` (published body digest differs from the header or the log),
``not_summary_native`` (a hand-built dossier has no draft lineage), ``bad_range``,
``draft_missing``, ``draft_lineage_broken`` (draft bytes no longer match the digest the
publication header recorded), ``draft_lineage_unproven`` (the header records no draft digest at all), ``evidence_missing`` (only when ``require_evidence=True``).
Absent evidence is otherwise a *warning* (``evidence_digest`` is ``None``): the fixture, and any
campaign published before evidence packs were kept, have none, and sparse verification is built
for exactly that case.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pipelines.summary_native import npc_publish, npc_slug

#: Where unchanged-attestations live (written by ``delta.attest``): one JSON per attestation.
ATTESTATIONS_REL = "docs/npcs/summary_native/delta/attestations"
NPC_ROOT_REL = "docs/npcs/summary_native"
_RANGE_RE = re.compile(r"^ch(\d+)-(\d+)$")
_NPC_FIELD_RE = re.compile(r"\|\s*npc:\s*([^|]+?)\s*\|")
_DRAFT_FIELD_RE = re.compile(r"draft sha256:\s*([0-9a-f]{64})")
_AUTHORED_FIELD_RE = re.compile(r"authored sha256:\s*([0-9a-f]{64})")


class NpcBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    subject: str
    publication: dict = Field(default_factory=dict)  # {published_sha256, body_sha256, horizon, range, run}
    draft: str | None = None
    evidence: str | None = None
    composition: str | None = None
    authored: str | None = None
    horizon: int | None = None
    attestations: list[dict] = Field(default_factory=list)
    status: str = "ok"
    warnings: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def npc_root_for(campaign_dir: Path | str) -> Path:
    return Path(campaign_dir) / NPC_ROOT_REL


def attestations_dir(campaign_dir: Path | str) -> Path:
    return Path(campaign_dir) / ATTESTATIONS_REL


def _sha_file(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def horizon_of(range_name: str) -> int | None:
    m = _RANGE_RE.match(range_name or "")
    return int(m.group(2)) if m else None


def load_attestations(campaign_dir: Path | str, slug: str | None = None,
                      publication_sha256: str | None = None) -> list[dict]:
    import json
    out: list[dict] = []
    d = attestations_dir(campaign_dir)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if slug and rec.get("slug") != slug:
            continue
        if publication_sha256 and rec.get("publication_sha256") != publication_sha256:
            continue
        out.append(rec)
    return out


def baseline_for(campaign_dir: Path | str, slug: str, *, npc_root: Path | None = None,
                 require_evidence: bool = False) -> NpcBaseline | None:
    """The baseline for one published slug, or ``None`` when the log does not name it."""
    root = Path(campaign_dir)
    nroot = Path(npc_root) if npc_root else npc_root_for(root)
    entry = npc_publish.read_publish_log(root, nroot).get(slug)
    if entry is None:
        return None
    return _build(root, nroot, slug, entry, require_evidence)


def load_baselines(campaign_dir: Path | str, *, npc_root: Path | None = None,
                   require_evidence: bool = False) -> dict[str, NpcBaseline]:
    """``{slug: NpcBaseline}`` for every slug in the publish log (sorted)."""
    root = Path(campaign_dir)
    nroot = Path(npc_root) if npc_root else npc_root_for(root)
    log = npc_publish.read_publish_log(root, nroot)
    return {s: _build(root, nroot, s, log[s], require_evidence) for s in sorted(log)}


def _build(root: Path, nroot: Path, slug: str, entry: dict, require_evidence: bool) -> NpcBaseline:
    target = nroot.parent / f"{slug}.md"
    rng = str(entry.get("range") or "")
    logged = entry.get("published_sha256")
    b = NpcBaseline(slug=slug, subject=slug, horizon=horizon_of(rng),
                    publication={"published_sha256": logged, "body_sha256": None,
                                 "horizon": horizon_of(rng), "range": rng or None,
                                 "run": entry.get("run"), "source": entry.get("source")})
    if not target.is_file():
        b.status = "repair_required:target_missing"
        return b
    text = target.read_text(encoding="utf-8")
    body_sha, header_sha = npc_publish.published_body_sha(text)
    b.publication["body_sha256"] = body_sha
    first = text.partition("\n")[0]
    m = _NPC_FIELD_RE.search(first)
    if m:
        b.subject = m.group(1)
    b.attestations = load_attestations(root, slug, logged)

    if body_sha is None or body_sha != header_sha or body_sha != logged:
        b.status = "repair_required:hand_edited_target"
        return b
    if entry.get("source") != "summary_native":
        b.status = "repair_required:not_summary_native"
        return b
    if horizon_of(rng) is None:
        b.status = "repair_required:bad_range"
        return b

    stem = npc_slug.stem_for("npc", b.subject)
    rdir = nroot / rng
    draft = rdir / "draft" / f"{stem}.md"
    b.draft = _sha_file(draft)
    b.composition = _sha_file(rdir / "gm" / f"{stem}.md")
    b.authored = _sha_file(nroot.parent / "authored" / f"{slug}.authored.yaml")
    b.evidence = _sha_file(rdir / "evidence" / f"{stem}.md")
    if b.draft is None:
        b.status = "repair_required:draft_missing"
        return b
    dm = _DRAFT_FIELD_RE.search(first)
    if dm is None:
        # no recorded draft digest: nothing proves this draft is the one the publication was made from
        b.status = "repair_required:draft_lineage_unproven"
        return b
    if dm.group(1) != b.draft:
        b.status = "repair_required:draft_lineage_broken"
        return b
    if b.evidence is None:
        if require_evidence:
            b.status = "repair_required:evidence_missing"
            return b
        b.warnings.append("evidence_missing")
    return b
