"""Fixed CLI stage execution. Every run writes a distinct output directory."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from campaignlib.util import atomic_write_bytes
from .engine import binding, require_fresh, run_by_id
from .storage import WorkflowError, now


def build_command(engine, state, run):
    from .stages import STAGES
    stage = STAGES[run.stage]
    if stage.command is None:
        return None
    options = run.task["options"]
    allowed = {"input", "gmassist", "summary", "session-summary", "plan", "recap", "party", "characters", "party-config", "players-config", "narration-genre-file", "batch", "batch-scenes", "narrate-tokens", "prose-mode", "reflections", "title"}
    if set(options) - allowed:
        raise WorkflowError("unsupported stage options: " + ", ".join(sorted(set(options) - allowed)))
    root = engine.store.contained(run.task["output_dir"])
    root.mkdir(parents=True, exist_ok=True)
    selected_dir = root.parent / "selected"
    selected_dir.mkdir(exist_ok=True)
    # Directory-consuming CLIs see only the exact explicitly selected sources.
    by_path = {e.path: e for e in run.inputs}
    for relative in run.selection:
        if relative in by_path:
            evidence = by_path[relative]
            atomic_write_bytes(selected_dir / Path(relative).name, engine.store.bytes(evidence))
    command = [str(Path(sys.executable).parent / stage.command)]
    effective = run.generation
    if stage.command != "assemble":
        command += ["--backend", effective.backend, "--model", effective.model]
        if effective.effort:
            flag = {"codex-cli": "--codex-reasoning-effort", "claude-code": "--claude-code-effort"}.get(effective.backend)
            if flag is None:
                raise WorkflowError("effort selection is not supported by this backend")
            command += [flag, effective.effort]
        if options.get("batch"):
            command += ["--batch"]
    def source(key):
        value = options.get(key)
        if not value or value not in by_path:
            raise WorkflowError(f"{key} must name an explicitly selected run input")
        return str(engine.source(value))
    if stage.command == "enhance_summary":
        command += [source("input"), "--gmassist", source("gmassist"), "--output", str(root / "session-summary.md"), "--no-log"]
    elif stage.command == "scene_extract":
        command += [source("input"), "--summary", source("summary"), "--output-dir", str(root), "--no-log"]
        if "batch-scenes" in options:
            command += ["--batch-scenes" if options["batch-scenes"] else "--no-batch-scenes"]
    elif stage.command == "sd_plan":
        command += ["--scene-extractions", str(selected_dir), "--party-config", run.task["context"]["paths"]["party-config"], "--characters", ",".join(run.task["context"]["characters"]), "--campaign-dir", str(engine.campaign), "--require-proposal", "--out", str(root / "plan.md")]
        if options.get("session-summary"):
            command += ["--session-summary", source("session-summary")]
    elif stage.command == "sd_narrate":
        command += [source("recap"), "--plan", source("plan"), "--scene-extractions", str(selected_dir), "--per-scene-output", str(root), "--narration-genre-file", run.task["context"]["paths"]["narration-genre-file"]]
        from session_doc.io import parse_plan, resolve_scene_extraction_file
        sections = parse_plan(Path(source("plan")).read_text(), 100000)
        indices = []
        matched = []
        for index, section in enumerate(sections, 1):
            match = resolve_scene_extraction_file(selected_dir, index, section.get("scene", ""))
            if match is not None:
                indices.append(index)
                matched.append(match)
        if not indices or len(matched) != len(set(matched)) or len(matched) != len(run.selection):
            raise WorkflowError("selected scenes do not resolve uniquely against the approved plan")
        command += ["--scene", *map(str, indices)]
        if len(matched) == 1:
            command += ["--scene-extraction-file", str(matched[0])]
        for key in ("narrate-tokens",):
            if key in options:
                command += ["--" + key, str(options[key])]
        if options.get("prose-mode"):
            command += ["--prose-mode"]
        if options.get("reflections"):
            command += ["--reflections"]
    elif stage.command == "assemble":
        command += [str(selected_dir), "--output", str(root / "session-document.md")]
        if options.get("title"):
            command += ["--title", options["title"]]
    if stage.command in {"enhance_summary", "scene_extract", "sd_narrate"}:
        for key in ("party-config", "players-config"):
            if key in run.task["context"]["paths"]:
                command += ["--" + key, run.task["context"]["paths"][key]]
    return command


def execute(engine, run_id: str, expected_revision: int):
    with engine.store.lock():
        state = engine.store.load()
        if state.revision != expected_revision:
            raise WorkflowError("stale workspace revision; reload before execution")
        run = run_by_id(state, run_id)
        require_fresh(engine.store, state, run)
        if run.status != "pending_agent":
            raise WorkflowError("run is not pending; inspect resume before retrying")
        command = build_command(engine, state, run)
        if command is None:
            return {"pending_agent": run.model_dump(mode="json"), "message": "Run the named skill natively, then submit output references. Human approval follows checks."}
        run.generation.command = command
        run.status = "running"
        engine.store.save(state, expected_revision=state.revision)
    log = engine.store.contained(f".session-workflow/work/{run.id}/execution.log")
    try:
        with log.open("wb") as handle:
            result = subprocess.run(command, cwd=engine.campaign, stdout=handle, stderr=subprocess.STDOUT, env={**os.environ, "CAMPAIGN_DIR": str(engine.campaign), "CG_BACKEND": run.generation.backend})
        if result.returncode:
            raise WorkflowError(f"stage failed with exit code {result.returncode}; inspect {log}")
        outputs = sorted(str(p.relative_to(engine.store.session)) for p in engine.store.contained(run.task["output_dir"]).glob("*.md"))
        with engine.store.lock():
            state = engine.store.load()
            engine.op_submit(state, run_id=run.id, outputs=outputs, generation=run.generation.model_dump())
            state.events.append({"operation": "execute", "run_id": run.id, "at": now(), "log": str(log.relative_to(engine.store.session))})
            engine.store.save(state, expected_revision=state.revision)
    except BaseException as exc:
        with engine.store.lock():
            state = engine.store.load()
            failed = run_by_id(state, run.id)
            failed.status = "failed"
            failed.failure = str(exc)
            engine.store.save(state, expected_revision=state.revision)
        raise
    return engine.status()


def resume(engine):
    status = engine.status()
    by_id = {r["id"]: r for r in status["runs"]}
    pending = []
    runs = engine.store.load().runs
    revised = {run.task.get("revises") for run in runs}
    for run in runs:
        view = by_id[run.id]
        if view["status"] == "approved" or run.id in revised:
            continue
        if view["status"] == "stale":
            next_action = "start a new run for the affected selection and review affected transitions"
        elif run.status in {"failed", "running"}:
            next_action = "inspect execution.log and preserved outputs; start a distinct retry run"
        elif run.status == "pending_agent":
            next_action = "execute fixed CLI stage or perform pending native skill task"
        elif view["missing_checks"]:
            next_action = "submit missing specialist checks; staged-consistency coordinates without duplicate audits"
        elif view["unresolved_findings"]:
            next_action = "human finding adjudication"
        else:
            next_action = "explicit human draft approval"
        pending.append({"run_id": run.id, "stage": run.stage, "next_action": next_action, "task": run.task})
    return {**status, "pending": pending}
