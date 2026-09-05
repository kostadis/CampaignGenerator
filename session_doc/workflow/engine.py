"""Deterministic shared review engine. Agents submit drafts; humans rule."""
from __future__ import annotations

from pathlib import Path
import uuid

from .models import Application, Approval, Check, Decision, Evidence, Generation, Run, Workflow
from .storage import Store, WorkflowError, digest, fingerprint, now


def selected(values: list[str]) -> list[str]:
    if not values or any(not str(x).strip() for x in values):
        raise WorkflowError("explicit nonempty selection required")
    if len(set(values)) != len(values):
        raise WorkflowError("duplicate selection identities are not allowed")
    return values


def run_by_id(state: Workflow, run_id: str) -> Run:
    for run in state.runs:
        if run.id == run_id:
            return run
    raise WorkflowError(f"unknown run: {run_id}")


def findings(run: Run):
    return [finding for check in run.checks for finding in check.findings]


def binding(run: Run) -> str:
    return fingerprint({"inputs": [x.model_dump() for x in run.inputs], "outputs": [x.model_dump() for x in run.outputs], "checks": [x.model_dump() for x in run.checks], "decisions": [x.model_dump() for x in run.decisions], "generation": run.generation.model_dump(), "selection": run.selection, "dependencies": run.dependencies})


def stale_reasons(store: Store, state: Workflow, run: Run, seen=None) -> list[str]:
    seen = set() if seen is None else set(seen)
    if run.id in seen:
        return ["dependency cycle"]
    seen.add(run.id)
    reasons = [f"changed or missing: {x.path}" for x in [*run.inputs, *run.outputs] if not store.fresh(x)]
    for check in run.checks:
        for finding in check.findings:
            if finding.rule and not store.fresh(finding.rule.authority):
                reasons.append(f"changed rule: {finding.rule.authority.path}")
    for parent_id in run.dependencies:
        parent = run_by_id(state, parent_id)
        if not parent.approval or parent.approval.binding != binding(parent):
            reasons.append(f"unapproved dependency: {parent_id}")
        reasons += stale_reasons(store, state, parent, seen)
    return sorted(set(reasons))


def require_fresh(store: Store, state: Workflow, run: Run):
    reasons = stale_reasons(store, state, run)
    if reasons:
        raise WorkflowError("stale run; " + "; ".join(reasons))


def unresolved(run: Run) -> list[str]:
    latest = {d.finding_id: d for d in run.decisions}
    return [f.id for f in findings(run) if f.id not in latest or latest[f.id].decision == "discuss"]


def require_approved(store: Store, state: Workflow, run: Run):
    require_fresh(store, state, run)
    if not run.approval or run.approval.binding != binding(run):
        raise WorkflowError(f"human draft approval required for {run.id}")


class Engine:
    def __init__(self, session: Path | str, campaign: Path | str):
        self.store = Store(session)
        self.campaign = Path(campaign).resolve(strict=True)
        if not self.store.session.is_relative_to(self.campaign):
            raise WorkflowError("session must be contained in campaign")

    def source(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.store.contained(value)
        if not path.resolve().is_relative_to(self.campaign):
            raise WorkflowError("source must be contained in the selected campaign")
        return path

    def initialize(self, config: str):
        with self.store.lock():
            if self.store.path.exists():
                raise WorkflowError("workflow already exists; inspect or migrate it explicitly")
            config_path = Path(config).resolve(strict=True)
            if not config_path.is_relative_to(self.campaign):
                raise WorkflowError("config must belong to this campaign")
            state = Workflow(session_id=self.store.session.name, config=str(config_path))
            self.store.save(state, expected_revision=0)
        return self.status()

    def status(self):
        state = self.store.load()
        views = []
        for run in state.runs:
            missing = sorted(set(run.required_checks) - {c.name for c in run.checks if c.status == "complete"})
            reasons = stale_reasons(self.store, state, run)
            views.append({"id": run.id, "stage": run.stage, "status": "stale" if reasons else "approved" if run.approval and run.approval.binding == binding(run) else run.status, "stale_reasons": reasons, "missing_checks": missing, "unresolved_findings": unresolved(run), "approval_binding": binding(run)})
        return {"state": state.model_dump(mode="json"), "runs": views, "recovery_required": self.store.contained(".session-workflow/transaction.yaml").exists()}

    def mutate(self, operation: str, payload: dict, revision: int):
        with self.store.lock():
            state = self.store.load()
            if state.revision != revision:
                raise WorkflowError("stale workspace revision; reload before submitting")
            if self.store.contained(".session-workflow/transaction.yaml").exists():
                raise WorkflowError("interrupted application; run session_workflow recover first")
            method = getattr(self, f"op_{operation.replace('-', '_')}", None)
            if method is None:
                raise WorkflowError(f"unsupported workflow operation: {operation}")
            result = method(state, **payload)
            if result is not False:
                state.events.append({"operation": operation, "at": now(), "revision": revision + 1})
                self.store.save(state, expected_revision=revision)
        return self.status()

    def op_start(self, state: Workflow, *, stage: str, selection: list[str], inputs: list[str], generation: dict, dependencies: list[str], required_checks: list[str], options: dict | None = None):
        from .stages import STAGES
        from .context import resolve_context, transcript_identity
        if stage not in STAGES:
            raise WorkflowError("unknown production stage")
        definition = STAGES[stage]
        parent_stages = {run_by_id(state, parent_id).stage for parent_id in dependencies}
        if not set(definition.parents) <= parent_stages:
            raise WorkflowError("missing approved stage dependencies: " + ", ".join(sorted(set(definition.parents) - parent_stages)))
        required_checks = sorted(set(required_checks) | set(definition.checks))
        options = options or {}
        allowed_options = {"input", "gmassist", "summary", "session-summary", "plan", "recap", "party", "characters", "party-config", "players-config", "narration-genre-file", "batch", "batch-scenes", "narrate-tokens", "prose-mode", "reflections", "title"}
        if set(options) - allowed_options:
            raise WorkflowError("unsupported stage options: " + ", ".join(sorted(set(options) - allowed_options)))
        context, configuration = resolve_context(self, state, stage, options)
        for parent_id in dependencies:
            require_approved(self.store, state, run_by_id(state, parent_id))
        labels = {e.path: e.label for previous in state.runs for e in previous.outputs}
        refs = [self.store.preserve(self.source(p), label=labels.get(p, "derived" if "smoothed" in p or ".cleaned." in p else "source")) for p in selected(inputs)]
        refs.append(self.store.preserve(Path(state.config), label="configuration"))
        run = Run(id=uuid.uuid4().hex, stage=stage, selection=selected(selection), inputs=refs, generation=Generation.model_validate(generation), dependencies=dependencies, required_checks=required_checks, started_at=now())
        run.inputs.extend(configuration)
        if stage in {"plan", "narrate", "release"}:
            if not set(selection) <= set(inputs):
                raise WorkflowError("scene selection must materialize input paths")
            if len({Path(p).name for p in selection}) != len(selection):
                raise WorkflowError("selected scene filenames must be unique")
        run.task = {"decision": definition.decision, "skills": list(definition.skills), "options": options, "context": context, "output_dir": f".session-workflow/work/{run.id}/outputs", "source_policy": "Original transcripts and captured extractions remain verbatim; corrections and smoothing are derived. Preserve new facts, discoveries, level changes, in-world magic, genuine dialogue and actual outcomes."}
        if stage == "identify":
            run.task["cues"] = [cue for evidence in run.inputs if evidence.path.endswith(".vtt") for cue in transcript_identity(self.store.bytes(evidence).decode(), context["players"], context["paths"].get("player_overrides", {}).get("speakers"))]
        state.runs.append(run)

    def op_submit(self, state: Workflow, *, run_id: str, outputs: list[str], generation: dict):
        run = run_by_id(state, run_id)
        require_fresh(self.store, state, run)
        if run.status not in {"pending_agent", "running"}:
            raise WorkflowError("run already completed; start a distinct run for a new version")
        resolved = Generation.model_validate(generation)
        for key in ("backend", "model", "effort"):
            if getattr(resolved, key) != getattr(run.generation, key):
                raise WorkflowError(f"effective {key} differs from selected run; start a distinct run")
        protected = {e.path for e in run.inputs if e.label == "source"}
        if set(outputs) & protected:
            raise WorkflowError("draft output cannot overwrite an original input")
        run.outputs = [self.store.preserve(self.store.contained(p), label="derived" if run.stage in {"identify", "remove-recap", "voice-smooth", "no-mech"} else "generated") for p in selected(outputs)]
        run.generation = resolved
        run.status = "generated"
        run.completed_at = now()

    def op_check(self, state: Workflow, *, run_id: str, check: dict):
        run = run_by_id(state, run_id)
        require_fresh(self.store, state, run)
        if run.status != "generated":
            raise WorkflowError("checking requires a completed draft")
        report = Check.model_validate(check)
        if any(c.name == report.name for c in run.checks):
            raise WorkflowError("check already submitted; create a new run for rechecking")
        output_hashes = {(x.path, x.sha256) for x in run.outputs}
        if {(x.path, x.sha256) for x in report.sources} != output_hashes:
            raise WorkflowError("check coverage must bind every output in this run")
        ids = {f.id for f in findings(run)}
        for f in report.findings:
            if f.id in ids:
                raise WorkflowError("duplicate finding identity")
            ids.add(f.id)
            if (f.evidence.path, f.evidence.sha256) not in output_hashes:
                raise WorkflowError("finding evidence is not this draft")
            self.store.bytes(f.evidence)
            if f.rule:
                self.store.bytes(f.rule.authority)
                if not self.store.fresh(f.rule.authority):
                    raise WorkflowError("stale rule authority")
            if f.change:
                if f.change.source != f.evidence:
                    raise WorkflowError("change source must match finding evidence")
                self.store.contained(f.change.target)
                if f.change.target == f.evidence.path and f.evidence.label == "source":
                    raise WorkflowError("original sources cannot be overwritten")
                if not f.change.before or self.store.bytes(f.evidence).decode().count(f.change.before) != 1:
                    raise WorkflowError("proposed replacement must identify one exact source occurrence")
        run.checks.append(report)

    def op_decide(self, state: Workflow, *, run_id: str, decisions: list[dict]):
        run = run_by_id(state, run_id)
        require_fresh(self.store, state, run)
        if not decisions:
            raise WorkflowError("explicit finding selection required")
        known = {f.id: f for f in findings(run)}
        seen = set()
        for raw in decisions:
            item = Decision.model_validate(raw)
            if item.finding_id in seen:
                raise WorkflowError("duplicate finding selection")
            seen.add(item.finding_id)
            if item.finding_id not in known or item.finding_sha256 != fingerprint(known[item.finding_id]):
                raise WorkflowError("stale or unknown finding decision")
            run.decisions.append(item)
        run.approval = None

    def op_approve(self, state: Workflow, *, run_id: str, actor: str, rationale: str, draft_binding: str):
        run = run_by_id(state, run_id)
        require_fresh(self.store, state, run)
        if run.status != "generated" or not run.outputs:
            raise WorkflowError("draft is not generated")
        if draft_binding != binding(run):
            raise WorkflowError("stale draft approval binding; review the current draft")
        missing = set(run.required_checks) - {c.name for c in run.checks if c.status == "complete"}
        if missing or any(c.status != "complete" for c in run.checks):
            raise WorkflowError("required checks missing, failed or skipped: " + ", ".join(sorted(missing)))
        if unresolved(run):
            raise WorkflowError("unresolved findings: " + ", ".join(unresolved(run)))
        latest = {d.finding_id: d.decision for d in run.decisions}
        if any(f.change and latest.get(f.id) == "approve" for f in findings(run)):
            raise WorkflowError("approved changes must be applied and the resulting draft checked before approval")
        if not actor.strip() or not rationale.strip():
            raise WorkflowError("human actor and rationale must be nonempty")
        run.approval = Approval(actor=actor, rationale=rationale, at=now(), binding=draft_binding)

    def op_apply(self, state: Workflow, *, run_id: str, finding_ids: list[str]):
        selected(finding_ids)
        key = fingerprint({"run_id": run_id, "finding_ids": sorted(finding_ids)})
        previous = next((a for a in state.applications if a.id == key), None)
        if previous:
            if not all(self.store.fresh(e) for e in previous.after.values()):
                raise WorkflowError("applied output changed; refusing repeated application")
            return False
        run = run_by_id(state, run_id)
        require_fresh(self.store, state, run)
        latest = {d.finding_id: d for d in run.decisions}
        known = {f.id: f for f in findings(run)}
        writes = {}
        originals = {}
        for fid in finding_ids:
            if fid not in known or fid not in latest or latest[fid].decision != "approve":
                raise WorkflowError("only individually approved findings can be applied")
            f = known[fid]
            if latest[fid].finding_sha256 != fingerprint(f) or not f.change:
                raise WorkflowError("stale decision or no executable proposed change")
            change = f.change
            target = self.store.contained(change.target)
            if target.exists() and digest(target.read_bytes()) != change.source.sha256:
                raise WorkflowError("source-mismatched application")
            if change.target.startswith(".session-workflow") or target.name == "session_workflow.yaml" or target.suffix == ".vtt":
                raise WorkflowError("workflow and transcript originals cannot be replacement targets")
            text = writes.get(change.target, self.store.bytes(change.source).decode())
            if text.count(change.before) != 1:
                raise WorkflowError("overlapping or ambiguous approved changes")
            writes[change.target] = text.replace(change.before, change.after, 1)
            originals[change.target] = digest(target.read_bytes()) if target.exists() else None
        after = {p: self.store.preserve_bytes(t.encode(), path=p, label="derived") for p, t in writes.items()}
        state.applications.append(Application(id=key, run_id=run_id, finding_ids=finding_ids, before=originals, after=after, at=now()))
        revised = Run(id=uuid.uuid4().hex, stage=run.stage, selection=run.selection, inputs=run.inputs, dependencies=run.dependencies, required_checks=run.required_checks, generation=run.generation, outputs=[after.get(e.path, e) for e in run.outputs] + [e for p, e in after.items() if p not in {x.path for x in run.outputs}], status="generated", started_at=now(), completed_at=now(), task={"revises": run.id})
        state.runs.append(revised)
        self.store.publish(state, after, expected_revision=state.revision)
        return False

    def op_select_version(self, state: Workflow, *, run_id: str):
        run = run_by_id(state, run_id)
        require_approved(self.store, state, run)
        state.selected_versions[run.stage] = run_id

    def export(self, run_id: str):
        state = self.store.load()
        run = run_by_id(state, run_id)
        return {"schema_version": 1, "session_id": state.session_id, "run_id": run_id, "draft_binding": binding(run), "revision": state.revision, "findings": [{**f.model_dump(), "finding_sha256": fingerprint(f)} for f in findings(run)], "decisions": [d.model_dump() for d in run.decisions]}

    def op_import(self, state: Workflow, *, document: dict):
        allowed = {"schema_version", "session_id", "run_id", "draft_binding", "revision", "findings", "decisions"}
        if set(document) - allowed or document.get("schema_version") != 1 or document.get("session_id") != state.session_id:
            raise WorkflowError("unsupported review import contract or session")
        run = run_by_id(state, document["run_id"])
        if document.get("draft_binding") != binding(run):
            raise WorkflowError("stale imported draft binding")
        self.op_decide(state, run_id=run.id, decisions=document["decisions"])
