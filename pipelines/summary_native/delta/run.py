"""RunState: the versioned, restart-safe record of one delta run (spec 039 R7).

Persistence reuses ``scheduler.atomic_write_record`` / ``read_record``.  This module
holds the record and small transition helpers only; resume/dispatch is elsewhere.
A failed stage is never marked success.  No model call is made here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pipelines.summary_native.scheduler import atomic_write_record, read_record

from .errors import DeltaRefusal

SCHEMA_VERSION = 1


class RunStatus(str, Enum):
    running = "running"
    failed = "failed"
    stale = "stale"
    awaiting_review = "awaiting_review"
    partial = "partial"
    recovery_required = "recovery_required"
    complete = "complete"


class StageStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class MemberOutcome(str, Enum):
    published = "published"
    held = "held"
    rejected = "rejected"
    unchanged = "unchanged"
    failed = "failed"


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str


class Stage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    status: StageStatus = StageStatus.pending
    artifacts: list[Artifact] = Field(default_factory=list)
    inputs_digest: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str
    outcome: MemberOutcome
    receipt_ref: str | None = None
    reason: str | None = None


class Counts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parsed_new: int = 0
    parsed_historical: int = 0
    integrity_only: int = 0
    model_input: int = 0
    reused_artifact: int = 0
    model_calls: int = 0
    checks: int = 0


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    run_id: str
    plan_ref: str
    status: RunStatus = RunStatus.running
    stages: list[Stage] = Field(default_factory=list)
    members: list[Member] = Field(default_factory=list)
    counts: Counts = Field(default_factory=Counts)
    #: subjects whose publication a grounding publication requires; a held one blocks it (FR-019)
    grounding_requires: list[str] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_run(state: RunState, path: Path | str) -> None:
    atomic_write_record(Path(path), state.model_dump(mode="json"))


def load_run(path: Path | str) -> RunState:
    record = read_record(Path(path))
    record.pop("schema", None)  # scheduler envelope marker, not ours
    version = record.get("schema_version")
    if version != SCHEMA_VERSION:
        raise DeltaRefusal(f"unsupported run state schema_version {version!r}")
    return RunState.model_validate(record)


def _stage(state: RunState, name: str) -> Stage:
    for stage in state.stages:
        if stage.name == name:
            return stage
    raise KeyError(f"no stage {name!r}")


def start_stage(state: RunState, name: str, inputs_digest: str | None = None) -> Stage:
    """Begin (or restart) a stage; prior artifacts are dropped, never reused here."""
    try:
        stage = _stage(state, name)
    except KeyError:
        stage = Stage(name=name)
        state.stages.append(stage)
    stage.status = StageStatus.running
    stage.inputs_digest = inputs_digest
    stage.artifacts = []
    stage.started_at = _now()
    stage.finished_at = None
    state.status = RunStatus.running
    return stage


def finish_stage(state: RunState, name: str, *, ok: bool,
                 artifacts: list[Artifact] | None = None) -> Stage:
    """Close a stage.  ``ok=False`` marks it failed and the run failed; never success."""
    stage = _stage(state, name)
    stage.finished_at = _now()
    if ok:
        stage.status = StageStatus.succeeded
        stage.artifacts = list(artifacts or [])
    else:
        stage.status = StageStatus.failed
        stage.artifacts = []
        state.status = RunStatus.failed
    return stage


# ── stage execution, batching, status derivation and resume (spec 039 T069-T072) ─────────────────
#
# Everything below is deterministic orchestration over operations that already exist.  The only model
# call is ``npc_update.draft`` (through ``npc_draft.run_draft``); this module makes none itself, and
# counts the ones that happen by wrapping the seam for the duration of the draft stage.

import contextlib
import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, Iterable

from pipelines.summary_native.scheduler import EndpointState, Scheduler, WorkItem, reconcile_items

from .errors import EXIT_OK, EXIT_PARTIAL, EXIT_RECOVERY, EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE
from .plan import DELTA_ROOT_REL, DeltaPlan, StoppingPoint, plan_digest

#: Internal engine constant, not an input to selection: how many members one dispatch item carries.
DEFAULT_BATCH_SIZE = 4

NPC_STAGES = ("census", "draft", "verify", "publish")
GROUNDING_STAGE = "grounding_apply"
RECEIPT_STAGE = "receipt"
STAGE_POINT = {"census": StoppingPoint.prepare, "draft": StoppingPoint.propose, "verify": StoppingPoint.verify,
               "publish": StoppingPoint.apply, GROUNDING_STAGE: StoppingPoint.apply}
_POINT_ORDER = {p: i for i, p in enumerate(StoppingPoint)}
GOOD = (MemberOutcome.published, MemberOutcome.unchanged)
BAD = (MemberOutcome.held, MemberOutcome.rejected, MemberOutcome.failed)


def plan_dir(campaign_dir: Path | str, plan_id: str) -> Path:
    return Path(campaign_dir) / DELTA_ROOT_REL / plan_id


def run_path(campaign_dir: Path | str, plan_id: str) -> Path:
    return plan_dir(campaign_dir, plan_id) / "run.json"


def batches_path(campaign_dir: Path | str, plan_id: str) -> Path:
    return plan_dir(campaign_dir, plan_id) / "batches.json"


def receipt_path(campaign_dir: Path | str, plan_id: str) -> Path:
    return plan_dir(campaign_dir, plan_id) / "receipt.json"


def requires_path(campaign_dir: Path | str, plan_id: str) -> Path:
    return plan_dir(campaign_dir, plan_id) / "grounding_requires.json"


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path | str) -> str | None:
    p = Path(path)
    return _sha_bytes(p.read_bytes()) if p.is_file() else None


def digest_of(*parts: object) -> str:
    """One digest over a canonical encoding of the parts (inputs of a stage)."""
    return _sha_bytes(json.dumps(list(parts), sort_keys=True, default=str).encode("utf-8"))


def required_stages(plan: DeltaPlan) -> list[str]:
    """The stages this plan's products and stopping point call for, in order."""
    names: list[str] = list(NPC_STAGES) if "npc" in plan.products else []
    if "grounding" in plan.products:
        names.append(GROUNDING_STAGE)
    stop = _POINT_ORDER[plan.stopping_point]
    return [n for n in names if _POINT_ORDER[STAGE_POINT[n]] <= stop]


def _rel(root: Path, path: Path) -> str:
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def _artifacts(root: Path, paths: Iterable[Path]) -> list[Artifact]:
    out = []
    for p in sorted({Path(x) for x in paths}):
        sha = sha_file(p)
        if sha is not None:
            out.append(Artifact(path=_rel(root, p), sha256=sha))
    return out


def get_stage(state: RunState, name: str) -> Stage | None:
    return next((s for s in state.stages if s.name == name), None)


def stage_reuse(root: Path, state: RunState, name: str, digest: str) -> str:
    """``reuse`` | ``run`` | ``stale``.

    ``reuse``: a succeeded stage, same inputs digest, every artifact present with its recorded bytes.
    ``stale``: the inputs match but an artifact was changed on disk since (re-running would silently
    redo work over someone's edit).  Anything else (never ran, failed, interrupted, inputs changed,
    an artifact missing) is ``run``.
    """
    stage = get_stage(state, name)
    if stage is None or stage.status is not StageStatus.succeeded or stage.inputs_digest != digest:
        return "run"
    changed = False
    for art in stage.artifacts:
        sha = sha_file(Path(root) / art.path)
        if sha is None:
            return "run"
        changed = changed or sha != art.sha256
    return "stale" if changed else "reuse"


class StageStale(DeltaRefusal):
    def __init__(self, name: str):
        super().__init__(f"stage {name!r}: an output changed on disk since it completed; re-run with --force "
                         "to redo it (a model may be called)", EXIT_STALE)


@dataclass
class StageReport:
    name: str
    status: str
    reused: bool = False


@dataclass
class RunReport:
    plan_id: str
    status: RunStatus
    exit_code: int
    stages: list[StageReport] = field(default_factory=list)
    calls_this_run: int = 0
    reused: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    next_action: str = ""
    receipt: str | None = None

    def to_dict(self) -> dict:
        return {"plan_id": self.plan_id, "status": self.status.value, "exit_code": self.exit_code,
                "stages": [vars(s) for s in self.stages], "call_counts": {"model": self.calls_this_run},
                "reused_stages": self.reused, "recovery_required": self.ambiguous,
                "next_action": self.next_action, "receipt": self.receipt}


def run_stage(root: Path, state: RunState, name: str, digest: str, fn: Callable[[], Iterable[Path]], *,
              save: Callable[[], None], force: bool = False, digest_after: Callable[[], str] | None = None) -> bool:
    """Run one stage unless a completed one with the same inputs can be reused; True when reused.

    The stage is persisted as running *before* ``fn`` so a crash leaves a visible, non-success record.
    An exception marks it failed (never success) and propagates; a ``BaseException`` (a crash) leaves it
    running.  ``digest_after`` records the digest of the state the stage *produced* when that is what a
    replay will compare against (publication changes its own inputs).
    """
    verdict = stage_reuse(root, state, name, digest)
    if verdict == "reuse":
        return True
    if verdict == "stale" and not force:
        raise StageStale(name)
    start_stage(state, name, digest)
    save()
    try:
        paths = list(fn())
    except Exception:
        finish_stage(state, name, ok=False)
        save()
        raise
    finish_stage(state, name, ok=True, artifacts=_artifacts(root, paths))
    if digest_after is not None:
        get_stage(state, name).inputs_digest = digest_after()  # type: ignore[union-attr]
    save()
    return False


@contextlib.contextmanager
def count_model_calls(counter: list[int]):
    """Count calls through ``npc_draft``'s model seam while a stage runs (measured, not asserted)."""
    from pipelines.summary_native import npc_draft

    inner = npc_draft.stream_api

    def counted(*args, **kwargs):
        counter[0] += 1
        return inner(*args, **kwargs)

    npc_draft.stream_api = counted
    try:
        yield
    finally:
        npc_draft.stream_api = inner


# ── batches (R7): materialised from the plan before dispatch ──────────────────────────────────


def materialize_batches(campaign_dir: Path | str, plan_id: str, subjects: Iterable[str], batch_size: int) -> list[list[str]]:
    """Persist the work batches.  Batch size only chunks an already-chosen, sorted member list; it is
    never an input to which subjects are selected."""
    if batch_size < 1:
        raise DeltaRefusal("batch size must be at least 1", EXIT_USAGE)
    ordered = sorted(dict.fromkeys(subjects), key=str.casefold)
    batches = [ordered[i:i + batch_size] for i in range(0, len(ordered), batch_size)]
    from .records_io import write_json
    write_json(batches_path(campaign_dir, plan_id), {
        "plan_id": plan_id, "batch_size": batch_size, "subjects": ordered,
        "items": [{"item_id": f"batch-{i:03d}", "ordinal": i, "subjects": b, "state": "pending"}
                  for i, b in enumerate(batches)]})
    return batches


def dispatch_batches(campaign_dir: Path | str, plan_id: str, call: Callable[[list[str]], object],
                     done: Callable[[str], bool]) -> dict[str, object]:
    """Dispatch pending batches through ``Scheduler.run_local``; ``reconcile_items`` decides what is pending.

    ``done(subject)`` is the artifact check: a batch whose every member is already done (its recorded
    result still true on disk) is complete and is not dispatched again.  Returns ``{item_id: value}``.
    """
    from .records_io import read_json, write_json

    path = batches_path(campaign_dir, plan_id)
    record = read_json(path)
    for item in record["items"]:
        if all(done(s) for s in item["subjects"]):
            item["state"] = "cached"
    complete, pending = reconcile_items(record, lambda item: all(done(s) for s in item["subjects"]))
    if not pending:
        return {}
    work = [WorkItem(item_id=i["item_id"], ordinal=i["ordinal"], operation="delta_batch") for i in pending]
    by_id = {i["item_id"]: i for i in pending}
    result = Scheduler([EndpointState("local", limit=1)]).run_local(
        work, lambda w: call(list(by_id[w.item_id]["subjects"])))
    for item in record["items"]:
        if item["item_id"] in result.values:
            item["state"] = "succeeded"
        elif item["item_id"] in result.failures:
            item["state"] = "failed"
    write_json(path, record)
    if result.failures:
        first = next(iter(result.failures.values()))
        raise DeltaRefusal(f"batch dispatch failed: {first.code}: {first.message}", EXIT_REFUSAL)
    return result.values


# ── status derivation (T072) ─────────────────────────────────────────────────────────────────


def derive_status(state: RunState, plan: DeltaPlan, *, ambiguous: int = 0, stale: bool = False) -> RunStatus:
    """The run's status from per-member outcomes and stage records alone.

    * an ambiguous member (target written, log not updated; an unresolved activation) -> ``recovery_required``
      until reconciled;
    * a failed stage -> ``failed``; a stage not yet succeeded -> ``running``;
    * mixed published/held -> ``partial``, never ``complete``; held with nothing published ->
      ``awaiting_review``;
    * ``complete`` only when the stopping point is reached for every required member.
    """
    if stale:
        return RunStatus.stale
    if ambiguous:
        return RunStatus.recovery_required
    late = ("publish", GROUNDING_STAGE)
    for name in required_stages(plan):
        if name in late:
            continue
        stage = get_stage(state, name)
        if stage is None or stage.status in (StageStatus.pending, StageStatus.running):
            return RunStatus.running
        if stage.status is StageStatus.failed:
            return RunStatus.failed
    outcomes = {m.outcome for m in state.members}
    bad, published = outcomes & set(BAD), MemberOutcome.published in outcomes
    if bad:
        if published:
            return RunStatus.partial
        return RunStatus.failed if outcomes <= {MemberOutcome.failed} else RunStatus.awaiting_review
    for name in required_stages(plan):
        stage = get_stage(state, name)
        if stage is not None and stage.status is StageStatus.failed:
            return RunStatus.failed
        if stage is None or stage.status is not StageStatus.succeeded:
            return RunStatus.running
    return RunStatus.complete


def blocked_by_hold(state: RunState) -> list[str]:
    """Required subjects of a grounding publication that are not published (or unchanged)."""
    by = {m.subject: m.outcome for m in state.members}
    return [s for s in state.grounding_requires if by.get(s) not in GOOD]


EXIT_FOR_STATUS = {RunStatus.complete: EXIT_OK, RunStatus.partial: EXIT_PARTIAL,
                   RunStatus.awaiting_review: EXIT_PARTIAL, RunStatus.recovery_required: EXIT_RECOVERY,
                   RunStatus.stale: EXIT_STALE, RunStatus.failed: EXIT_REFUSAL, RunStatus.running: EXIT_REFUSAL}


# ── ambiguity (read-only) ─────────────────────────────────────────────────────────────────────


def ambiguous_members(campaign_dir: Path | str, plan_id: str) -> list[str]:
    """Slugs with a publication intent that no receipt answers (target may be written, log not)."""
    from . import npc_update

    rdir = npc_update.receipts_dir(campaign_dir, plan_id)
    out = []
    for ipath in sorted(rdir.glob("*.intent.json")) if rdir.is_dir() else []:
        try:
            intent = json.loads(ipath.read_text(encoding="utf-8"))
            slug = intent["slug"]
        except (OSError, ValueError, KeyError):
            out.append(ipath.name)
            continue
        rpath = rdir / f"{slug}.json"
        try:
            done = json.loads(rpath.read_text(encoding="utf-8")) if rpath.is_file() else None
        except ValueError:
            done = None
        if not done or done.get("intent_id") != intent.get("intent_id"):
            out.append(slug)
    return out


def ambiguous_activation(campaign_dir: Path | str, plan: DeltaPlan) -> list[str]:
    if "grounding" not in plan.products:
        return []
    from . import grounding_recovery as gr

    st = gr.inspect(campaign_dir, plan)
    return [f"grounding:{st.operation_id}"] if st.state in (gr.AMBIGUOUS, gr.INTERVENTION) else []


# ── the orchestrator ─────────────────────────────────────────────────────────────────────────


def load_or_start(campaign_dir: Path | str, plan: DeltaPlan) -> RunState:
    path = run_path(campaign_dir, plan.plan_id)
    plan_ref = f"{plan.plan_id}-r{plan.revision}"
    if path.is_file():
        state = load_run(path)
        if state.plan_ref != plan_ref:
            raise DeltaRefusal(f"run {state.run_id} belongs to {state.plan_ref}, not {plan_ref}; the plan changed",
                               EXIT_STALE)
        return state
    state = RunState(run_id=f"run-{plan.plan_id}", plan_ref=plan_ref)
    rp = requires_path(campaign_dir, plan.plan_id)
    if rp.is_file():
        state.grounding_requires = sorted(json.loads(rp.read_text(encoding="utf-8")).get("subjects", []))
    return state


def _upsert(state: RunState, subject: str, outcome: MemberOutcome, receipt_ref: str | None = None,
            reason: str | None = None) -> None:
    for m in state.members:
        if m.subject == subject:
            m.outcome, m.receipt_ref, m.reason = outcome, receipt_ref, reason
            return
    state.members.append(Member(subject=subject, outcome=outcome, receipt_ref=receipt_ref, reason=reason))


def _member_done(root: Path, plan_id: str, state: RunState, slug_of: dict[str, str], subject: str) -> bool:
    """A recorded publication that is still true on disk: receipt published, target and log agree."""
    from pipelines.summary_native import npc_publish, schema
    from . import npc_baseline, npc_update

    rec = next((m for m in state.members if m.subject == subject), None)
    if rec is None or rec.outcome is not MemberOutcome.published or not rec.receipt_ref:
        return False
    slug = slug_of.get(subject)
    receipt = Path(root) / rec.receipt_ref
    try:
        r = json.loads(receipt.read_text(encoding="utf-8"))
        text = (Path(root) / schema.NPCS_DIR / f"{slug}.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    body, _ = npc_publish.published_body_sha(text)
    log = npc_publish.read_publish_log(Path(root), npc_baseline.npc_root_for(root)).get(slug) or {}
    return (r.get("outcome") == "published" and body is not None and body == log.get("published_sha256")
            and body == r.get("target_sha256", body))


def advance(campaign_dir: Path | str, plan: DeltaPlan, *, batch_size: int = DEFAULT_BATCH_SIZE,
            force: bool = False, publisher=None, now=None, write_receipt: bool = True) -> RunReport:
    """Continue the run from its last durable stage; reuse compatible completed work by digest.

    Never makes a model call for a stage whose inputs are unchanged.  A run already complete is
    replayed without any content write (no stage runs, no state or receipt is rewritten).
    """
    from . import census as census_mod, npc_update, receipt as receipt_mod

    root = Path(campaign_dir)
    state = load_or_start(root, plan)
    calls = [0]
    reused: list[str] = []
    before = json.dumps(state.model_dump(mode="json"), sort_keys=True)

    def save() -> None:
        save_run(state, run_path(root, plan.plan_id))

    added = [False]

    def finish(stale: bool = False) -> RunReport:
        if not added[0]:
            state.counts.model_calls += calls[0]
            added[0] = True
        amb = ambiguous_members(root, plan.plan_id) + ambiguous_activation(root, plan)
        state.status = derive_status(state, plan, ambiguous=len(amb), stale=stale)
        if json.dumps(state.model_dump(mode="json"), sort_keys=True) != before:
            save()
        report = RunReport(plan.plan_id, state.status, EXIT_FOR_STATUS[state.status],
                           [StageReport(s.name, s.status.value, s.name in reused) for s in state.stages],
                           calls[0], reused, amb, _next_action(state, plan, amb))
        return report

    try:
        names = required_stages(plan)
        npc = [n for n in names if n in NPC_STAGES]
        slug_of: dict[str, str] = {}
        census_file = census_mod.census_path(root, plan.plan_id)
        rulings = root / census_mod.RULINGS_REL
        registry = _registry_sha(root)
        src_shas = [(s.chapter, s.sha256) for s in plan.sources]

        if "census" in npc:
            d = digest_of("census", plan_digest(plan), src_shas, registry, sha_file(rulings))
            if run_stage(root, state, "census", d, lambda: [census_mod.run_census(root, plan)[1]],
                         save=save, force=force):
                reused.append("census")
            census = census_mod.load_census(root, plan.plan_id)
            from . import attest as attest_mod

            for e in census.entries:
                if e.disposition != "mentioned_unchanged":
                    continue
                # FR-013 / #585: "unchanged" is the GM's attestation, never an inference from a passing mention.
                # It must name the dossier's CURRENT published sha and carry this plan's sources.
                rec = attest_mod.covering_attestation(root, e.subject, plan)
                if rec is not None:
                    _upsert(state, e.subject, MemberOutcome.unchanged, None, f"attested {rec['id']}")
                else:
                    _upsert(state, e.subject, MemberOutcome.held, None,
                            "needs attestation: run `summary_native delta npc attest "
                            f"{e.subject!r} --plan {plan.plan_id} --publication <published sha256> --reason ...`")
            census_sha = sha_file(census_file)

            if "draft" in npc:
                members = npc_update.select_members(census)
                slug_of = {e.subject: e.slug for e in members}
                dd = digest_of("draft", census_sha, plan.models.model_dump(mode="json"),
                               sorted(slug_of.values()))

                def draft() -> list[Path]:
                    if not members:
                        return []
                    with count_model_calls(calls):
                        out = npc_update.draft(root, plan, now=now)
                    if out.exit_code != 0:
                        raise DeltaRefusal(f"drafting did not complete (exit {out.exit_code}); "
                                           "re-run resume to continue", EXIT_REFUSAL)
                    nd = npc_update.delta_dir(root, plan.plan_id)
                    paths = [nd / "members.json"]
                    for m in members:
                        stem = _stem(m.subject)
                        paths += [nd / f"{stem}.spans.json", out.range_dir / "draft" / f"{stem}.md",
                                  out.range_dir / "evidence" / f"{stem}.md"]
                    return paths

                if run_stage(root, state, "draft", dd, draft, save=save, force=force):
                    reused.append("draft")

                if "verify" in npc and members:
                    nd = npc_update.delta_dir(root, plan.plan_id)
                    vd = digest_of("verify", [a.sha256 for a in get_stage(state, "draft").artifacts])  # type: ignore[union-attr]

                    def verify() -> list[Path]:
                        res = npc_update.verify(root, plan)
                        state.counts.checks = len(res)
                        return ([nd / f"{_stem(m.subject)}.verify.json" for m in members]
                                + [npc_update.graph_path(root, plan.plan_id)])

                    if run_stage(root, state, "verify", vd, verify, save=save, force=force):
                        reused.append("verify")
                elif "verify" in npc:
                    run_stage(root, state, "verify", digest_of("verify", []), lambda: [], save=save, force=force)

                if "publish" in npc:
                    _publish(root, plan, state, members, slug_of, batch_size, save, reused, force, now)

        if GROUNDING_STAGE in names:
            _grounding(root, plan, state, save, reused, force, publisher)

        report = finish()
        if write_receipt and report.status is RunStatus.complete:
            rd = digest_of("receipt", state.model_dump(mode="json")["members"], state.counts.model_dump(),
                           [(s.name, s.inputs_digest) for s in state.stages if s.name != RECEIPT_STAGE])
            if run_stage(root, state, RECEIPT_STAGE, rd,
                         lambda: [receipt_mod.write_receipt(root, plan, state)], save=save, force=force):
                reused.append(RECEIPT_STAGE)
            report = finish()
            report.receipt = str(receipt_path(root, plan.plan_id))
        return report
    except StageStale:
        raise
    except DeltaRefusal as exc:
        if exc.exit_code == EXIT_STALE:
            return finish(stale=True)
        raise


def _stem(subject: str) -> str:
    from pipelines.summary_native import npc_slug

    return npc_slug.stem_for("npc", subject)


def _registry_sha(root: Path) -> str | None:
    from campaignlib.registry import find_registry

    p = find_registry(root)
    return sha_file(p) if p else None


def _publish(root: Path, plan: DeltaPlan, state: RunState, members, slug_of: dict[str, str], batch_size: int,
             save, reused: list[str], force: bool, now) -> None:
    """The publish stage: per-member, batched, idempotent.  Held members stay held and keep their old
    publication; a stage with any member not published is not success."""
    from . import npc_update

    all_subjects = sorted(slug_of, key=str.casefold)
    if not all_subjects:
        run_stage(root, state, "publish", digest_of("publish", []), lambda: [], save=save, force=force)
        return
    # FR-020: publish only what the GM previewed. The preview record names the member set explicitly and
    # carries each member's rows; the run never computes a preview and confirms it itself.
    stored = npc_update.load_stored_preview(root, plan.plan_id)
    stored_rows = {r["slug"]: r for r in (stored or {}).get("members", [])}
    subjects = [s for s in all_subjects if slug_of[s] in stored_rows]
    for s in all_subjects:
        if s not in subjects:
            _upsert(state, s, MemberOutcome.held, None,
                    "not in a GM-previewed publication; run `summary_native delta npc publish --plan "
                    f"{plan.plan_id} --member {s!r}` to preview it")
    if not subjects:
        save()
        return

    def preview_sha() -> str:
        return npc_update.publish_preview(root, plan, subjects)["preview_sha256"]

    cur = preview_sha()
    stage = get_stage(state, "publish")
    all_done = all(_member_done(root, plan.plan_id, state, slug_of, s) for s in subjects)
    if stage and stage.status is StageStatus.succeeded and stage.inputs_digest == cur and all_done:
        reused.append("publish")  # an identical completed replay: nothing is written
        return
    if ambiguous_members(root, plan.plan_id):
        pass  # npc_publish.publish reconciles first (inside its lock); the run never repeats a target write

    def run() -> list[Path]:
        materialize_batches(root, plan.plan_id, subjects, batch_size)

        def call(batch: list[str]):
            todo = [s for s in batch if not _member_done(root, plan.plan_id, state, slug_of, s)]
            if not todo:
                return []
            now_rows = {r["slug"]: r for r in npc_update.publish_preview(root, plan, todo)["members"]}
            amb = set(ambiguous_members(root, plan.plan_id))

            def same(subject: str) -> bool:
                slug = slug_of[subject]
                keys = ["draft_sha256", "composition_sha256", "evidence_sha256"]
                if slug not in amb and not any(m.subject == subject and m.outcome is not MemberOutcome.held
                                               for m in state.members):
                    keys += ["target_sha256", "log_entry_sha256"]  # untouched so far: the target must be as previewed
                return all(now_rows.get(slug, {}).get(k) == stored_rows[slug].get(k) for k in keys)

            moved = [s for s in todo if not same(s)]
            for s in moved:
                _upsert(state, s, MemberOutcome.held, None,
                        "the previewed publication is stale (a draft, composition, evidence pack, target or log "
                        "entry changed); preview it again with `delta npc publish`")
            todo = [s for s in todo if s not in moved]
            if not todo:
                save()
                return []
            pv = npc_update.publish_preview(root, plan, todo)["preview_sha256"]
            try:
                results = npc_update.publish(root, plan, todo, pv, now=now)
            except DeltaRefusal as exc:
                if exc.exit_code != EXIT_REFUSAL:
                    raise  # stale (3) / usage (2): the run reports it as such
                for s in todo:  # no review binding yet: every member waits for the GM's handoff, none fails
                    _upsert(state, s, MemberOutcome.held, None, exc.message)
                save()
                return []
            for r in results:
                outcome = MemberOutcome(r.outcome)
                ref = None
                if r.receipt is not None:
                    ref = _rel(root, npc_update.receipts_dir(root, plan.plan_id) / f"{r.slug}.json")
                subj = next(s for s in todo if slug_of[s] == r.slug)
                _upsert(state, subj, outcome, ref, r.reason)
            save()
            return results

        dispatch_batches(root, plan.plan_id, call,
                         lambda s: _member_done(root, plan.plan_id, state, slug_of, s))
        rdir = npc_update.receipts_dir(root, plan.plan_id)
        if any(m.outcome in BAD for m in state.members if m.subject in slug_of):
            raise _Held()
        return [rdir / f"{slug_of[s]}.json" for s in subjects]

    try:
        run_stage(root, state, "publish", cur, run, save=save, force=force, digest_after=preview_sha)
    except _Held:
        pass


class _Held(Exception):
    """Some member is held or failed: the stage is not success, and the run is not an error."""


# ── grounding (T071): inspect/recover by operation identity, then apply ──────────────────────


def _grounding(root: Path, plan: DeltaPlan, state: RunState, save, reused: list[str], force: bool,
               publisher) -> None:
    from . import grounding_publish as gp, grounding_recovery as gr

    name = "grounding"
    blockers = blocked_by_hold(state)
    status = gr.inspect(root, plan)

    def hold(reason: str) -> None:
        _upsert(state, name, MemberOutcome.held, None, reason)

    if status.state in (gr.AMBIGUOUS, gr.INTERVENTION):
        status = gr.recover(root, plan)  # by operation identity, never a blind re-run
    if status.state == gr.INTERVENTION:
        hold(f"activation {status.operation_id} needs intervention: {status.detail}; run `{status.command}`")
        return
    if status.state == gr.COMMITTED:
        _upsert(state, name, MemberOutcome.published, None, f"activation {status.operation_id}")
        stage = get_stage(state, GROUNDING_STAGE)
        if stage is None or stage.status is not StageStatus.succeeded:
            start_stage(state, GROUNDING_STAGE, status.operation_id)
            finish_stage(state, GROUNDING_STAGE, ok=True)
        else:
            reused.append(GROUNDING_STAGE)
        save()
        return
    if status.state == gr.ABORTED:
        hold(status.detail or "aborted")
        return
    if blockers:
        hold(f"blocked: required member(s) not published: {', '.join(blockers)}")
        return
    pv = gp.grounding_dir(root, plan.plan_id) / gp.PREVIEW_FILE
    if not pv.is_file():
        hold("no grounding preview; run `delta grounding preview` and confirm it")
        return
    sha = json.loads(pv.read_text(encoding="utf-8"))["preview_sha256"]
    start_stage(state, GROUNDING_STAGE, sha)
    save()
    try:
        gp.apply(plan, sha, campaign_dir=root, publisher=publisher)
    except DeltaRefusal as exc:
        finish_stage(state, GROUNDING_STAGE, ok=False)
        hold(exc.message)
        save()
        if exc.exit_code == EXIT_STALE:
            raise
        return
    except Exception:
        finish_stage(state, GROUNDING_STAGE, ok=False)
        save()
        raise
    finish_stage(state, GROUNDING_STAGE, ok=True)
    _upsert(state, name, MemberOutcome.published, None, f"activation {status.operation_id}")
    save()


def _next_action(state: RunState, plan: DeltaPlan, ambiguous: list[str]) -> str:
    cmd = f"summary_native delta run resume --plan {plan.plan_id}"
    if ambiguous:
        return f"{cmd}  (reconciles {', '.join(ambiguous)} from its durable intent; nothing is rewritten blindly)"
    held = [m for m in state.members if m.outcome in BAD]
    if held:
        return ("resolve the held member(s) (" + ", ".join(f"{m.subject}: {m.reason or m.outcome.value}" for m in held)
                + f"), then `{cmd}`")
    if state.status is RunStatus.complete:
        return "nothing to do"
    return f"`{cmd}`"
