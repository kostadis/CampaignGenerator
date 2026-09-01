"""Atomic, hash-bound proposal staging, reconsideration, and comparison apply."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from campaignlib.narration_context import resolve_narration_guidance

from .indexes import visible_confirmed_slugs
from .models import (
    AtomicProposal,
    CampaignScope,
    CanonicalEvidenceBinding,
    StateError,
    ValidationError,
    proposal_fingerprint,
    require_stable_id,
    sha256_bytes,
)
from .paths import authorized_target, contained_path
from .storage import (
    _journaled_writes,
    campaign_lock,
    load_iteration,
    read_json,
    save_iteration,
    write_bytes,
    write_json,
)


IMPACT_BLOCK_RE = re.compile(r"```json narration-wiki-impact\s*\n(.*?)\n```", re.S)


def _load_impacts(scope: CampaignScope) -> list[dict[str, Any]]:
    ledger = scope.campaign_wiki_root / "skill-impact.md"
    if not ledger.is_file():
        return []
    try:
        text = ledger.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(f"impact ledger cannot be read: {exc}") from exc
    rows = []
    for block in IMPACT_BLOCK_RE.findall(text):
        try:
            value = json.loads(block)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"impact ledger contains malformed structured data: {exc}") from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _proposal_draft(iteration_root: Path, draft_path: str | Path) -> tuple[dict[str, Any], Path]:
    candidate = Path(draft_path).expanduser()
    if not candidate.is_absolute():
        candidate = iteration_root / candidate
    candidate = contained_path(iteration_root, candidate)
    if not candidate.is_file():
        raise ValidationError("proposal draft must be a file inside the selected iteration")
    try:
        value = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValidationError(f"proposal draft is invalid YAML/UTF-8: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError("proposal draft must be an object")
    if "targets" in value or isinstance(value.get("target"), list):
        raise ValidationError("proposal must name exactly one target")
    return value, candidate


def _after_bytes(iteration_root: Path, draft: dict[str, Any], draft_path: Path) -> bytes:
    inline = draft.get("after_text", draft.get("replacement"))
    if inline is not None:
        if not isinstance(inline, str):
            raise ValidationError("proposal after_text must be UTF-8 text")
        return inline.encode("utf-8")
    named = draft.get("candidate", "candidate")
    candidate = Path(str(named))
    if not candidate.is_absolute():
        candidate = draft_path.parent / candidate
    candidate = contained_path(iteration_root, candidate)
    try:
        raw = candidate.read_bytes()
        raw.decode("utf-8")
    except FileNotFoundError as exc:
        raise ValidationError("proposal candidate file is missing") from exc
    except UnicodeDecodeError as exc:
        raise ValidationError("proposal candidate must be UTF-8") from exc
    return raw


def _validate_bindings(
    scope: CampaignScope,
    affected_rule: str,
    bindings: Iterable[Mapping[str, Any]],
    prior: dict[str, Any] | None,
) -> list[dict[str, str]]:
    manifest = read_json(scope.iteration_root / "trace-manifest.json")
    current = {(row.get("path"), row.get("sha256")) for row in manifest.get("artifacts", [])}
    current_digests = {digest for _, digest in current}
    prior_digests = {
        item.get("source_sha256")
        for item in ((prior or {}).get("reconsideration") or {}).get("bindings", [])
        if isinstance(item, dict)
    }
    result = []
    for value in bindings:
        try:
            binding = CanonicalEvidenceBinding(
                source_ref=str(value["source_ref"]),
                source_sha256=str(value["source_sha256"]),
                applies_to_kind=str(value["applies_to_kind"]),
                applies_to_key=str(value["applies_to_key"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValidationError("evidence binding must contain all four contract fields") from exc
        if (binding.source_ref, binding.source_sha256) not in current:
            if binding.source_sha256 in current_digests:
                raise ValidationError("moving the same evidence digest to a new path is not new evidence")
            raise ValidationError("evidence binding is not a member of the current manifest")
        if binding.source_sha256 in prior_digests:
            raise ValidationError("evidence digest was already considered by the prior rejection")
        if binding.applies_to_kind not in {"rule", "measurement_category"}:
            raise ValidationError("evidence binding applies_to_kind is invalid")
        if binding.applies_to_key != affected_rule:
            raise ValidationError("evidence binding does not apply to the affected rule")
        result.append({
            "source_ref": binding.source_ref,
            "source_sha256": binding.source_sha256,
            "applies_to_kind": binding.applies_to_kind,
            "applies_to_key": binding.applies_to_key,
        })
    if not result:
        raise ValidationError("new-evidence reconsideration requires at least one binding")
    return sorted(result, key=lambda row: (row["source_sha256"], row["source_ref"]))


def stage_proposal(
    scope: CampaignScope,
    proposal_id: str,
    draft_path: str | Path,
    *,
    evidence_bindings: Iterable[Mapping[str, Any]] = (),
    override_rationale: str | None = None,
) -> dict[str, Any]:
    proposal_id = require_stable_id(proposal_id, "proposal-id")
    root = scope.iteration_root / "proposals" / proposal_id
    if root.exists():
        raise StateError(f"proposal {proposal_id} already exists")
    iteration = load_iteration(scope)
    if iteration.active_proposal_id:
        raise StateError(f"iteration already has active proposal {iteration.active_proposal_id}")
    draft, source = _proposal_draft(scope.iteration_root, draft_path)
    pattern_slugs = sorted(set(str(item) for item in draft.get("pattern_slugs", [])))
    if not pattern_slugs:
        raise ValidationError("proposal requires at least one confirmed pattern slug")
    hidden = sorted(set(pattern_slugs) - visible_confirmed_slugs(scope))
    if hidden:
        raise ValidationError(f"proposal uses unconfirmed or unavailable patterns: {', '.join(hidden)}")
    affected_rule = require_stable_id(str(draft.get("affected_rule", "")), "affected-rule")
    target_kind = str(draft.get("target_kind", ""))
    target_path = Path(str(draft.get("target_path", ""))).as_posix()
    guidance = resolve_narration_guidance(scope.campaign_root, require_rulebook=True)
    scope = replace(scope, guidance=guidance)
    target = authorized_target(scope, target_kind, target_path)
    before = target.read_bytes()
    try:
        before.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("authorized proposal target must be UTF-8") from exc
    expected_before = draft.get("expected_before_sha256")
    if expected_before is not None and str(expected_before) != sha256_bytes(before):
        raise StateError("proposal draft was based on a stale target hash")
    after = _after_bytes(scope.iteration_root, draft, source)
    if before == after:
        raise ValidationError("proposal candidate must differ from the target")
    before_hash = sha256_bytes(before)
    after_hash = sha256_bytes(after)
    diff = "".join(difflib.unified_diff(
        before.decode("utf-8").splitlines(keepends=True),
        after.decode("utf-8").splitlines(keepends=True),
        fromfile=target_path,
        tofile=target_path,
        lineterm="\n",
    ))
    fingerprint = proposal_fingerprint(target_kind, target_path, affected_rule, before_hash, after_hash)
    impacts = _load_impacts(scope)
    if any(row.get("proposal_id") == proposal_id for row in impacts):
        raise StateError(f"proposal ID already appears in impact ledger: {proposal_id}")
    prior = next(
        (row for row in impacts if row.get("proposal_fingerprint") == fingerprint and row.get("ruling") == "Rejected"),
        None,
    )
    bindings = list(evidence_bindings)
    if bindings and str(override_rationale or "").strip():
        raise ValidationError("new evidence and GM override are mutually exclusive")
    reconsideration: dict[str, Any] | None = None
    if bindings:
        reconsideration = {
            "kind": "new_evidence",
            "bindings": _validate_bindings(scope, affected_rule, bindings, prior),
        }
    elif str(override_rationale or "").strip():
        reconsideration = {"kind": "gm_override", "rationale": str(override_rationale).strip()}
    if prior and reconsideration is None:
        raise StateError("equivalent rejected proposal requires canonical new evidence or a GM override")
    proposal = AtomicProposal(
        proposal_id=proposal_id,
        iteration_id=scope.iteration_id,
        pattern_slugs=pattern_slugs,
        affected_rule=affected_rule,
        target_kind=target_kind,
        target_path=target_path,
        before_sha256=before_hash,
        after_sha256=after_hash,
        diff_sha256=sha256_bytes(diff.encode("utf-8")),
        proposal_fingerprint=fingerprint,
        reconsideration=reconsideration,
    )
    # Staging lands in a sibling directory and is renamed into place only once
    # the live target has been re-checked.  Writing straight into `root` created
    # the proposal directory before that check, so a lost race left a half-staged
    # directory that made every retry of the same ID refuse.
    staging = root.with_name(f".{proposal_id}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        write_bytes(staging / "draft.yaml", source.read_bytes())
        write_bytes(staging / "candidate", after)
        write_bytes(staging / "before.snapshot", before)
        write_bytes(staging / "after.snapshot", after)
        write_bytes(staging / "change.diff", diff.encode("utf-8"))
        write_json(staging / "proposal.json", proposal.to_dict())
        if target.read_bytes() != before:
            raise StateError("proposal staging changed or raced with the live target")
        root.parent.mkdir(parents=True, exist_ok=True)
        os.rename(staging, root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    iteration.state = "proposal_staged"
    iteration.active_proposal_id = proposal_id
    save_iteration(scope, iteration)
    return {
        "proposal_id": proposal_id,
        "state": "staged",
        "target_kind": target_kind,
        "target_path": target_path,
        "before_sha256": before_hash,
        "after_sha256": after_hash,
        "diff_sha256": proposal.diff_sha256,
        "proposal_fingerprint": fingerprint,
    }


def apply_proposal(scope: CampaignScope, proposal_id: str) -> dict[str, Any]:
    proposal_id = require_stable_id(proposal_id, "proposal-id")
    root = scope.iteration_root / "proposals" / proposal_id
    proposal = read_json(root / "proposal.json")
    if proposal.get("state") == "comparison_applied":
        target = scope.campaign_root / str(proposal["target_path"])
        if sha256_bytes(target.read_bytes()) == proposal.get("after_sha256"):
            return {"proposal_id": proposal_id, "state": "comparison_applied", "idempotent": True}
    if proposal.get("state") != "staged":
        raise StateError("proposal-apply requires a staged proposal")
    guidance = resolve_narration_guidance(scope.campaign_root, require_rulebook=True)
    scope = replace(scope, guidance=guidance)
    target = authorized_target(scope, str(proposal["target_kind"]), str(proposal["target_path"]))
    if sha256_bytes(target.read_bytes()) != proposal.get("before_sha256"):
        raise StateError("live proposal target no longer matches the staged before hash")
    after = (root / "after.snapshot").read_bytes()
    if sha256_bytes(after) != proposal.get("after_sha256"):
        raise ValidationError("after snapshot hash does not match proposal")
    proposal["state"] = "comparison_applied"
    with campaign_lock(scope):
        _journaled_writes(scope, "proposal_apply", proposal_id, [
            (target, after),
            (root / "proposal.json", (json.dumps(proposal, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")),
        ])
    iteration = load_iteration(scope)
    iteration.state = "comparison_applied"
    iteration.active_proposal_id = proposal_id
    save_iteration(scope, iteration)
    return {"proposal_id": proposal_id, "state": "comparison_applied", "after_sha256": proposal["after_sha256"]}
