"""Review binding: what a GM's approval was given *for* (spec 039 FR-017, FR-020, SC-005).

A :class:`ReviewBinding` records the exact hashes of the candidate, the plan, the evidence and the
rules a review covered, the decisions made, who made them, and the findings the GM was shown.  A
change to any bound hash makes the binding stale (:func:`is_stale`), and apply / publish refuse with
exit 3 naming the hash that moved (:func:`require_fresh`).

Four approval scopes (``draft``, ``attestation``, ``association``, ``publication``) are kept
distinct: a binding is stored under its own scope and a lookup for one scope can never be answered
by another (:func:`require_scope`).

Decisions are never set here by a model or by a default: they are read from the review authority
(:func:`sync_from_review`) or recorded explicitly (:func:`record_decision`).  A ``discuss``,
``reject`` or unsaved (``unset``) decision is blocking (:func:`blockers`).

This is a NEW record, deliberately not a ``StrictPromotionModel`` subclass (R8).  No model call.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from .errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .plan import DELTA_ROOT_REL, DeltaPlan, plan_digest
from .records_io import read_json, write_json

APPROVAL_SCOPES = ("draft", "attestation", "association", "publication")
PRODUCTS = ("grounding", "npc")
DECISIONS = ("approve", "reject", "discuss", "unset")
HASH_FIELDS = ("candidate_sha256", "plan_sha256", "evidence_sha256", "rules_sha256")
HASH_LABELS = {"candidate_sha256": "candidate", "plan_sha256": "plan",
               "evidence_sha256": "evidence", "rules_sha256": "rules"}

#: Authority / rule files whose bytes are part of what a review covered (absent files hash as "absent").
RULE_FILES = ("docs/entity_registry.yaml", "config/players.yaml", "docs/thread_registry.yaml", "docs/canon.yaml")


class BoundDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    level: Literal["item", "document"] = "item"
    decision: Literal["approve", "reject", "discuss", "unset"] = "unset"
    member: str | None = None  # NPC slug, when the decision is about one member
    reviewer: str | None = None
    note: str | None = None


class ReviewBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    product: Literal["grounding", "npc"]
    approval_scope: Literal["draft", "attestation", "association", "publication"]
    candidate_sha256: str
    plan_sha256: str
    evidence_sha256: str
    rules_sha256: str
    members: list[str] = Field(default_factory=list)  # NPC slugs the hashes cover (empty for grounding)
    review_id: str | None = None
    decisions: list[BoundDecision] = Field(default_factory=list)
    reviewer: str | None = None
    decision_revision: int = 0
    inherited_findings: list[str] = Field(default_factory=list)
    outstanding_findings: list[str] = Field(default_factory=list)
    # NPC bindings: per-member hashes, so redrafting one member never stales another (FR-014, SC-005).
    member_hashes: dict[str, dict[str, str]] = Field(default_factory=dict)  # slug -> {candidate, evidence}
    shared_sha256: str = ""  # census + associations: inputs every member shares


# ── paths ───────────────────────────────────────────────────────────────────


def review_dir(campaign_dir: Path | str, plan_id: str) -> Path:
    return Path(campaign_dir) / DELTA_ROOT_REL / plan_id / "review"


def binding_path(campaign_dir: Path | str, plan_id: str, product: str, scope: str) -> Path:
    return review_dir(campaign_dir, plan_id) / f"{product}.{scope}.json"


def document_path(campaign_dir: Path | str, plan_id: str) -> Path:
    return review_dir(campaign_dir, plan_id) / "review.md"


# ── hashing ─────────────────────────────────────────────────────────────────


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _combine(parts: dict[str, str | None]) -> str:
    return _sha(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes()) if path.is_file() else "absent"


def rules_digest(campaign_dir: Path | str) -> str:
    root = Path(campaign_dir)
    return _combine({rel: _file_sha(root / rel) for rel in RULE_FILES})


def _grounding_hashes(root: Path, plan: DeltaPlan) -> dict[str, str]:
    from . import grounding_publish as gp
    from .cli_plan import selection_path

    candidates, lineage, request = gp.load_inputs(root, plan.plan_id)
    cand = _combine({**{n: _sha(b) for n, b in candidates.items()},
                     "lineage": _sha(gp.lineage_bytes(lineage)), "request": _sha(request)})
    return {"candidate_sha256": cand,
            "evidence_sha256": _combine({"sources": _file_sha(selection_path(root, plan.plan_id))})}


def _npc_state_rows(root: Path, plan: DeltaPlan, slugs: Iterable[str] | None):
    from . import npc_baseline, npc_update

    state = npc_update.load_state(root, plan.plan_id)
    members = [m for m in state["members"] if slugs is None or m["slug"] in set(slugs)]
    return state, members, npc_baseline.npc_root_for(root) / state["range"]


def _npc_parts(root: Path, plan: DeltaPlan, slugs: Iterable[str] | None) -> tuple[dict[str, dict[str, str]], str]:
    """``({slug: {candidate, evidence}}, shared)``: each member's own hashes, and the inputs all share."""
    from . import npc_update
    from .associations import store_path as association_path
    from .census import census_path

    _state, members, rdir = _npc_state_rows(root, plan, slugs)
    per: dict[str, dict[str, str]] = {}
    for m in sorted(members, key=lambda r: r["slug"]):
        stem = m["stem"]
        per[m["slug"]] = {
            "candidate": _combine({"draft": _file_sha(rdir / "draft" / f"{stem}.md"),
                                   "composition": _file_sha(rdir / "gm" / f"{stem}.md")}),
            "evidence": _combine({
                "pack": _file_sha(rdir / "evidence" / f"{stem}.md"),
                "spans": _file_sha(npc_update.delta_dir(root, plan.plan_id) / f"{stem}.spans.json")})}
    shared = _combine({"census": _file_sha(census_path(root, plan.plan_id)),
                       "associations": _file_sha(association_path(root, plan.plan_id))})
    return per, shared


def _npc_hashes(root: Path, plan: DeltaPlan, slugs: Iterable[str] | None) -> dict[str, str]:
    per, shared = _npc_parts(root, plan, slugs)
    return {"candidate_sha256": _combine({s: h["candidate"] for s, h in per.items()}),
            "evidence_sha256": _combine({**{s: h["evidence"] for s, h in per.items()}, "shared": shared})}


def current_hashes(campaign_dir: Path | str, plan: DeltaPlan, product: str,
                   members: Iterable[str] | None = None) -> dict[str, str]:
    """The four hashes now.  ``members`` (NPC slugs) restricts the NPC hashes to those members."""
    root = Path(campaign_dir)
    if product == "grounding":
        out = _grounding_hashes(root, plan)
    elif product == "npc":
        out = _npc_hashes(root, plan, None if members is None else list(members))
    else:
        raise DeltaRefusal(f"unknown product {product!r}", EXIT_USAGE)
    out["plan_sha256"] = plan_digest(plan)
    out["rules_sha256"] = rules_digest(root)
    return out


# ── findings ────────────────────────────────────────────────────────────────


def collect_findings(campaign_dir: Path | str, plan: DeltaPlan, product: str,
                     members: Iterable[str] | None = None) -> tuple[list[str], list[str]]:
    """``(inherited, outstanding)`` as shown to the reviewer.  Read-only; never judges anything."""
    root = Path(campaign_dir)
    inherited: list[str] = []
    outstanding: list[str] = []
    if product == "grounding":
        from .baseline import bind
        from .grounding_check import load_check_report

        report = load_check_report(root, plan.plan_id)
        if report is None:
            outstanding.append("no consistency check recorded")
        else:
            for f in report.get("findings", []):
                line = f"{f['severity']}: {f['document']}:{f['line']} {f['code']} {f['detail']}"
                (outstanding if f["severity"] == "blocking" else inherited).append(line)
        try:
            baseline = bind(root)
            inherited.extend(f"baseline drift {h.hunk_id} in {h.document}" for h in baseline.drift)
        except DeltaRefusal as exc:
            inherited.append(f"baseline unavailable: {exc.message}")
    else:
        from . import npc_baseline, npc_update

        _state, rows, rdir = _npc_state_rows(root, plan, None if members is None else list(members))
        for m in rows:
            bl = npc_baseline.baseline_for(root, m["slug"])
            if bl is not None:
                if bl.status != "ok":
                    inherited.append(f"{m['slug']}: baseline {bl.status}")
                inherited.extend(f"{m['slug']}: baseline warning {w}" for w in bl.warnings)
            verdict = npc_update.npc_publish_verdict(rdir, m["stem"])
            if verdict != "pass":
                outstanding.append(f"{m['slug']}: verification {verdict or 'not run'}")
    return sorted(set(inherited)), sorted(set(outstanding))


# ── record ──────────────────────────────────────────────────────────────────


def make_binding(campaign_dir: Path | str, plan: DeltaPlan, product: str, scope: str, *,
                 members: Iterable[str] | None = None, review_id: str | None = None,
                 reviewer: str | None = None, decisions: list[BoundDecision] | None = None) -> ReviewBinding:
    if scope not in APPROVAL_SCOPES:
        raise DeltaRefusal(f"unknown approval scope {scope!r}; one of {', '.join(APPROVAL_SCOPES)}", EXIT_USAGE)
    slugs = sorted(set(members)) if members is not None else None
    hashes = current_hashes(campaign_dir, plan, product, slugs)
    inherited, outstanding = collect_findings(campaign_dir, plan, product, slugs)
    per, shared = _npc_parts(Path(campaign_dir), plan, slugs) if product == "npc" else ({}, "")
    return ReviewBinding(plan_id=plan.plan_id, product=product, approval_scope=scope, **hashes,
                         members=slugs or [], review_id=review_id, reviewer=reviewer,
                         decisions=decisions or [], inherited_findings=inherited, outstanding_findings=outstanding,
                         member_hashes=per, shared_sha256=shared)


def save_binding(campaign_dir: Path | str, binding: ReviewBinding) -> Path:
    return write_json(binding_path(campaign_dir, binding.plan_id, binding.product, binding.approval_scope),
                      binding.model_dump(mode="json"))


def load_binding(campaign_dir: Path | str, plan_id: str, product: str, scope: str) -> ReviewBinding | None:
    """The binding stored for exactly ``scope``; another scope's file is never consulted."""
    path = binding_path(campaign_dir, plan_id, product, scope)
    if not path.is_file():
        return None
    binding = ReviewBinding(**read_json(path))
    require_scope(binding, scope)
    return binding


def require_scope(binding: ReviewBinding, needed: str) -> ReviewBinding:
    """An approval of one scope never satisfies another (FR-017)."""
    if binding.approval_scope != needed:
        raise DeltaRefusal(f"the review binding is a {binding.approval_scope!r} approval; "
                           f"a {needed!r} approval is required and the scopes are not interchangeable",
                           EXIT_REFUSAL)
    return binding


def is_stale(binding: ReviewBinding, current: dict[str, str]) -> list[str]:
    """Reasons, one per bound hash that differs from ``current`` (empty = fresh)."""
    return [f"{HASH_LABELS[f]} changed since review (bound {getattr(binding, f)[:12]}, now {current[f][:12]})"
            for f in HASH_FIELDS if current.get(f) != getattr(binding, f)]


def _npc_stale_reasons(root: Path, plan: DeltaPlan, binding: ReviewBinding, chosen: Iterable[str]) -> list[str]:
    """Only the chosen members' own hashes, plus the plan, the rules and the inputs members share."""
    chosen = sorted(set(chosen))
    per, shared = _npc_parts(root, plan, chosen)
    reasons: list[str] = []
    for slug in chosen:
        bound, now = binding.member_hashes.get(slug), per.get(slug)
        if bound is None or now is None:
            reasons.append(f"{slug}: not covered by the review binding")
            continue
        for key in ("candidate", "evidence"):
            if bound[key] != now[key]:
                reasons.append(f"{slug}: {key} changed since review (bound {bound[key][:12]}, now {now[key][:12]})")
    if binding.shared_sha256 and binding.shared_sha256 != shared:
        reasons.append(f"evidence (census/associations) changed since review (bound {binding.shared_sha256[:12]}, "
                       f"now {shared[:12]})")
    if plan_digest(plan) != binding.plan_sha256:
        reasons.append("plan changed since review")
    if rules_digest(root) != binding.rules_sha256:
        reasons.append("rules changed since review")
    return reasons


def blockers(binding: ReviewBinding, *, members: Iterable[str] | None = None) -> list[str]:
    """Decisions that stop the action: anything but a saved ``approve``; no decisions at all blocks."""
    wanted = None if members is None else set(members)
    rel = [d for d in binding.decisions if wanted is None or d.member is None or d.member in wanted]
    if not rel:
        return ["no decision has been recorded"]
    labels = {"unset": "no saved decision", "discuss": "marked Discuss", "reject": "rejected"}
    return [f"{d.id}: {labels[d.decision]}" for d in rel if d.decision != "approve"]


def member_holds(binding: ReviewBinding, members: Iterable[str]) -> dict[str, str]:
    """``{slug: reason}`` for each chosen member whose own decision is not a saved approve (FR-019)."""
    out: dict[str, str] = {}
    for slug in members:
        mine = [d for d in binding.decisions if d.member == slug]
        if not mine:
            out[slug] = "review decisions block this member: no decision has been recorded"
            continue
        bad = [f"{d.id}: {dict(unset='no saved decision', discuss='marked Discuss', reject='rejected')[d.decision]}"
               for d in mine if d.decision != "approve"]
        if bad:
            out[slug] = "review decisions block this member: " + "; ".join(bad)
    return out


def record_decision(campaign_dir: Path | str, binding: ReviewBinding, decision_id: str, decision: str, *,
                    reviewer: str, level: str = "item", member: str | None = None,
                    note: str | None = None) -> ReviewBinding:
    """Explicitly record one decision (an explicit value is required: there is no default approval)."""
    if decision not in DECISIONS:
        raise DeltaRefusal(f"decision must be one of {', '.join(DECISIONS)}", EXIT_USAGE)
    if not reviewer or not reviewer.strip():
        raise DeltaRefusal("a reviewer is required", EXIT_USAGE)
    rest = [d for d in binding.decisions if d.id != decision_id]
    rest.append(BoundDecision(id=decision_id, level=level, decision=decision, member=member,
                              reviewer=reviewer, note=note))
    new = binding.model_copy(update={"decisions": sorted(rest, key=lambda d: d.id),
                                     "decision_revision": binding.decision_revision + 1, "reviewer": reviewer})
    save_binding(campaign_dir, new)
    return new


# ── decisions from the review authority ─────────────────────────────────────


def decisions_from_review(campaign_dir: Path | str, review_id: str, *, signoffs_only: bool = False,
                          members: Iterable[str] | None = None) -> tuple[list[BoundDecision], str | None]:
    """Read-only: each review item's current decision, ``unset`` when none is saved or it is stale."""
    from pipelines.summary_native.review.delegated import _current_decision, _latest
    from pipelines.summary_native.review.store import ReviewStoreError, read_review_state
    from pipelines.summary_native.npc_slug import slug_for

    try:
        _manifest, items, events, stale = read_review_state(Path(campaign_dir), review_id)
    except ReviewStoreError as exc:
        raise DeltaRefusal(f"cannot read review {review_id}: {exc}", EXIT_REFUSAL) from exc
    wanted = None if members is None else set(members)
    out: list[BoundDecision] = []
    reviewer = None
    for item in items:
        action = item.proposed_action.action
        if signoffs_only and action != "signoff_npc_draft":
            continue
        member = None
        if action == "signoff_npc_draft":
            member = slug_for(str(item.proposed_action.details.get("npc", "")))
            if wanted is not None and member not in wanted:
                continue
        event = _latest(events, item.item_id)
        current = _current_decision(event, item, stale)
        verdict = event.get("verdict") if current else "unset"
        if verdict not in DECISIONS:
            verdict = "unset"
        who = event.get("reviewer") if current else None
        reviewer = who or reviewer
        out.append(BoundDecision(id=item.item_id, level="document" if item.scope.kind == "document" else "item",
                                 decision=verdict, member=member, reviewer=who))
    return sorted(out, key=lambda d: d.id), reviewer


def sync_from_review(campaign_dir: Path | str, binding: ReviewBinding) -> ReviewBinding:
    """Refresh the binding's decisions from its review; bump ``decision_revision`` only on change."""
    if not binding.review_id:
        return binding
    decisions, reviewer = decisions_from_review(
        campaign_dir, binding.review_id, signoffs_only=binding.product == "npc",
        members=binding.members if binding.product == "npc" else None)
    if decisions == binding.decisions:
        return binding
    new = binding.model_copy(update={"decisions": decisions, "reviewer": reviewer or binding.reviewer,
                                     "decision_revision": binding.decision_revision + 1})
    save_binding(campaign_dir, new)
    return new


# ── the gate apply / publish call ───────────────────────────────────────────


def require_fresh(campaign_dir: Path | str, plan: DeltaPlan, product: str, *, scope: str = "publication",
                  members: Iterable[str] | None = None, required: bool = False,
                  enforce_decisions: bool = True) -> ReviewBinding | None:
    """Refuse (exit 3) when a bound hash changed since the review; refuse (exit 1) on a blocking decision.

    With no binding recorded for ``scope`` the existing gates (sign-offs, preview digest) stand alone
    and ``None`` is returned, unless ``required``.  A binding recorded for another scope never counts.
    """
    root = Path(campaign_dir)
    binding = load_binding(root, plan.plan_id, product, scope)
    if binding is None:
        if required:
            raise DeltaRefusal(f"no {scope!r} review binding for plan {plan.plan_id}; run `delta review handoff` "
                               "and review before applying", EXIT_REFUSAL)
        return None
    chosen = sorted(set(members)) if members is not None else None
    if chosen is not None and product == "npc":
        uncovered = [m for m in chosen if m not in set(binding.members)]
        if uncovered:
            raise DeltaRefusal(f"not covered by the review binding: {', '.join(uncovered)}; run `delta review handoff`",
                               EXIT_STALE)
    if product == "npc" and binding.member_hashes:
        reasons = _npc_stale_reasons(root, plan, binding, chosen if chosen is not None else binding.members)
    else:
        covered = binding.members if product == "npc" else None
        reasons = is_stale(binding, current_hashes(root, plan, product, covered))
    if reasons:
        raise DeltaRefusal("the review is stale: " + "; ".join(reasons) + "; review again with `delta review handoff`",
                           EXIT_STALE)
    binding = sync_from_review(root, binding)
    if not enforce_decisions:
        return binding  # the caller holds each unapproved member itself (FR-019)
    stops = blockers(binding, members=chosen if product == "npc" else None)
    if stops:
        raise DeltaRefusal("review decisions block this action: " + "; ".join(stops), EXIT_REFUSAL)
    return binding
