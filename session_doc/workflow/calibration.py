"""Durable, hash-bound native calibration; never a whole-draft approval."""
from typing import Literal

from pydantic import Field

from .models import Approval, Contract, Decision, Evidence
from .storage import WorkflowError, fingerprint, now


class Card(Contract):
    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    scene: str = Field(min_length=1)
    speaker: str = Field(min_length=1)
    location: str = Field(min_length=1)
    source: Evidence
    sample: Evidence
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    risk: str = ""


class Report(Contract):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1)
    method: str = Field(min_length=1)
    cards: list[Card] = Field(min_length=1)
    authorities: list[Evidence] = Field(min_length=1)


class Calibration(Contract):
    schema_version: Literal[1] = 1
    report: Report
    decisions: list[Decision] = Field(default_factory=list)
    approval: Approval | None = None


def load(run):
    raw = run.task.get("calibration")
    return Calibration.model_validate(raw) if raw is not None else None


def evidence(calibration):
    refs = [*calibration.report.authorities]
    for card in calibration.report.cards:
        refs.extend([card.source, card.sample])
    return refs


def stale(store, run):
    calibration = load(run)
    return sorted({f"changed calibration evidence: {e.path}" for e in evidence(calibration) if not store.fresh(e)}) if calibration else []


def binding(calibration):
    return fingerprint({"report": calibration.report.model_dump(), "decisions": [d.model_dump() for d in calibration.decisions]})


def unresolved(calibration):
    latest = {d.finding_id: d for d in calibration.decisions}
    return [c.id for c in calibration.report.cards if c.id not in latest or latest[c.id].decision == "discuss"]


def approved(calibration):
    return bool(calibration and calibration.approval and calibration.approval.binding == binding(calibration))


def view(run):
    calibration = load(run)
    if not calibration:
        return None
    return {**calibration.model_dump(), "binding": binding(calibration),
            "approved": approved(calibration), "unresolved": unresolved(calibration),
            "cards": [{**c.model_dump(), "finding_sha256": fingerprint(c)} for c in calibration.report.cards]}


def pending(engine, state, run_id):
    from .engine import require_fresh, run_by_id
    run = run_by_id(state, run_id)
    require_fresh(engine.store, state, run)
    if run.stage != "voice-smooth" or run.status != "pending_agent":
        raise WorkflowError("calibration requires a pending voice-smooth run")
    return run


def register(engine, state, *, run_id, report, replaces_binding=None):
    # Replacing a stale report is explicit; all earlier review remains in events.
    from .engine import require_fresh, run_by_id
    run = run_by_id(state, run_id)
    if run.stage != "voice-smooth" or run.status != "pending_agent":
        raise WorkflowError("calibration requires a pending voice-smooth run")
    old = load(run)
    if (binding(old) if old else None) != replaces_binding:
        raise WorkflowError("stale calibration replacement binding")
    run.task.pop("calibration", None)
    require_fresh(engine.store, state, run)
    parsed = Report.model_validate(report)
    ids = [c.id for c in parsed.cards]
    if len(ids) != len(set(ids)):
        raise WorkflowError("duplicate calibration card identities")
    inputs = {(e.path, e.sha256) for e in run.inputs}
    for authority in parsed.authorities:
        if (authority.path, authority.sha256) not in inputs:
            raise WorkflowError("calibration authority must be a resolved run input")
    for card in parsed.cards:
        if card.source.path not in run.selection or (card.source.path, card.source.sha256) not in inputs:
            raise WorkflowError("calibration source must be explicitly selected")
        sample_path = engine.store.contained(card.sample.path)
        review_root = engine.store.contained(f".session-workflow/work/{run.id}/review")
        if not sample_path.is_relative_to(review_root) or card.sample.label != "derived":
            raise WorkflowError("preserve derived calibration samples under this run's review directory")
        if card.before not in engine.store.bytes(card.source).decode() or card.after not in engine.store.bytes(card.sample).decode():
            raise WorkflowError("calibration comparison does not match preserved evidence")
    calibration = Calibration(report=parsed)
    for ref in evidence(calibration):
        engine.store.bytes(ref)
        if not engine.store.fresh(ref):
            raise WorkflowError("stale calibration evidence")
    if old:
        state.events.append({"operation": "calibration-superseded", "run_id": run.id, "at": now(), "calibration": old.model_dump()})
    run.task["calibration"] = calibration.model_dump()


def decide(engine, state, *, run_id, decisions):
    from .engine import LOCAL_REVIEWER, REVIEW_ACTIONS
    run = pending(engine, state, run_id)
    calibration = load(run)
    if not calibration or not decisions:
        raise WorkflowError("explicit nonempty calibration decisions required")
    known = {c.id: c for c in calibration.report.cards}
    seen = set()
    for raw in decisions:
        item = Decision.model_validate({"actor": LOCAL_REVIEWER, "rationale": REVIEW_ACTIONS.get(raw.get("decision"), ""), "at": now(), **raw})
        if item.finding_id in seen or item.finding_id not in known or item.finding_sha256 != fingerprint(known[item.finding_id]):
            raise WorkflowError("stale, duplicate or unknown calibration decision")
        seen.add(item.finding_id)
        calibration.decisions.append(item)
    calibration.approval = None
    run.task["calibration"] = calibration.model_dump()


def approve(engine, state, *, run_id, calibration_binding):
    from .engine import LOCAL_REVIEWER
    run = pending(engine, state, run_id)
    calibration = load(run)
    if not calibration or calibration_binding != binding(calibration):
        raise WorkflowError("stale calibration approval binding")
    if unresolved(calibration):
        raise WorkflowError("unresolved calibration cards: " + ", ".join(unresolved(calibration)))
    calibration.approval = Approval(actor=LOCAL_REVIEWER, rationale="Use this calibration for the remaining selected scenes; rejected examples retain original wording.", at=now(), binding=calibration_binding)
    run.task["calibration"] = calibration.model_dump()


def export(engine, run_id):
    from .engine import run_by_id
    state = engine.store.load()
    return {"schema_version": 1, "kind": "calibration-review", "session_id": state.session_id,
            "run_id": run_id, "revision": state.revision, "calibration": view(run_by_id(state, run_id))}


def import_review(engine, state, *, document):
    from .engine import run_by_id
    if set(document) != {"schema_version", "kind", "session_id", "run_id", "revision", "calibration"} or document["schema_version"] != 1 or document["kind"] != "calibration-review" or document["session_id"] != state.session_id or document["revision"] != state.revision:
        raise WorkflowError("stale or unsupported calibration import")
    current = view(run_by_id(state, document["run_id"]))
    incoming = document["calibration"]
    if not current or not isinstance(incoming, dict) or {k: v for k, v in incoming.items() if k != "decisions"} != {k: v for k, v in current.items() if k != "decisions"}:
        raise WorkflowError("stale or altered calibration import; only decisions may change")
    decisions = incoming.get("decisions", [])
    history = current["decisions"]
    if decisions[:len(history)] != history:
        raise WorkflowError("calibration import must preserve history and append new decisions")
    decide(engine, state, run_id=document["run_id"], decisions=decisions[len(history):])


def require_complete_submission(run, outputs):
    calibration = load(run)
    if run.stage == "voice-smooth":
        if not approved(calibration):
            raise WorkflowError("human calibration approval required; use session_workflow calibration-register then calibration-decide and calibration-approve")
        from pathlib import Path
        if sorted(Path(p).name for p in outputs) != sorted(Path(p).name for p in run.selection):
            raise WorkflowError("submit every explicitly selected voice-smooth scene, not only the calibration sample")
