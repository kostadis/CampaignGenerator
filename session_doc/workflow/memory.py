"""Explicit corpus handoffs into existing lineage, event and projection tools."""
from pathlib import Path

from campaignlib.lineage import resolve_source
from .engine import require_approved, require_fresh, run_by_id, selected
from .storage import WorkflowError, digest, now


def memory_scope(engine, state, *, chapters: list[str], notes: list[str]):
    selected(chapters)
    if len(set(notes)) != len(notes):
        raise WorkflowError("duplicate note selection")
    paths = [engine.source(str(engine.campaign / p)) for p in [*chapters, *notes]]
    for path in paths:
        if not path.is_file():
            raise WorkflowError(f"selected corpus file is missing: {path}")
    state.chapters_selected = chapters
    state.notes_selected = notes
    state.events.append({"operation": "memory-scope", "at": now(), "evidence": [engine.store.preserve(p, label="source").model_dump() for p in paths]})


def memory_plan(engine):
    state = engine.store.load()
    selected(state.chapters_selected)
    sources = []
    for relative in state.chapters_selected:
        chapter = engine.source(str(engine.campaign / relative))
        decision = resolve_source(chapter, engine.campaign)
        sources.append({"chapter": relative, "sha256": digest(chapter.read_bytes()), "lineage": decision.as_json(), "scope_review": "Existing lineage suggestions and legacy reviewed markers do not approve a new workflow draft; review these selected inputs."})
    scope_events = [e for e in state.events if e.get("operation") == "memory-scope" and "evidence" in e]
    from .models import Evidence
    stale = [e["path"] for e in scope_events[-1]["evidence"] if not engine.store.fresh(Evidence.model_validate(e))] if scope_events else []
    event_files = sorted(str(p.relative_to(engine.campaign)) for p in (engine.campaign / "docs" / "ensemble").rglob("*_events.json"))
    return {"chapters": sources, "notes": state.notes_selected, "stale_selection": stale, "event_spine": {"available_corpus": event_files, "selected_corpus": [], "prerequisite": "Select event extraction files explicitly; an empty corpus refuses execution."}, "tasks": [
        {"tool": "ensemble_batch", "decision": "Approve selected chapter/source lineage before extraction; use existing cached and batch passes"},
        {"tool": "ensemble_merge", "decision": "Review declarations and merges; transcription garbles are corrections, not aliases"},
        {"tool": "facts_to_state", "decision": "Review changed dossier and grounding drafts before promotion"},
        {"tool": "event_spine", "decision": "Update only explicitly selected new/changed chapter events"},
        {"tool": "thread_registry", "decision": "Record thread proposal rulings before ratification"},
        {"tool": "grounding_sections", "decision": "Review selected projection sections and freshness before prep"},
    ], "freshness": engine.status()["runs"], "guidance": "Narration critiques may enter narration-wiki; guidance changes retain independent human gates."}


def memory_events(engine, state, *, run_id: str, corpus: list[str], previous_store: str | None = None):
    from pipelines.grounding.event_spine import update
    from campaignlib.util import atomic_write_bytes
    run = run_by_id(state, run_id)
    if run.stage != "memory" or run.status != "pending_agent":
        raise WorkflowError("event updates require a pending memory run")
    require_fresh(engine.store, state, run)
    inputs = {e.path for e in run.inputs}
    selected(corpus)
    if not set(corpus) <= inputs or (previous_store and previous_store not in inputs):
        raise WorkflowError("event corpus and previous store must be explicit memory-run inputs")
    root = engine.store.contained(run.task["output_dir"])
    root.mkdir(parents=True, exist_ok=True)
    output = root / "event_spine.json"
    if previous_store:
        atomic_write_bytes(output, engine.source(previous_store).read_bytes())
    count, chapters = update([str(engine.source(p)) for p in corpus], output)
    engine.op_submit(state, run_id=run_id, outputs=[str(output.relative_to(engine.store.session))], generation=run.generation.model_dump())
    run.task["event_update"] = {"events": count, "chapters": chapters, "corpus": corpus}


def promote(engine, state, *, run_id: str):
    from .models import Application
    from .engine import binding
    from .storage import fingerprint
    run = run_by_id(state, run_id)
    if run.stage != "memory":
        raise WorkflowError("campaign promotion requires an approved memory run")
    mappings = run.task.get("promotions", {})
    if not mappings:
        raise WorkflowError("promotion targets must be selected before draft approval")
    key = fingerprint({"promotion": run_id, "binding": binding(run)})
    previous = next((a for a in state.applications if a.id == key), None)
    if previous:
        if not all(engine.store.fresh(e) for e in previous.after.values()):
            raise WorkflowError("promoted output changed")
        return False
    require_approved(engine.store, state, run)
    by_path = {e.path: e for e in run.outputs}
    after = {}
    before = {}
    for output, target in mappings.items():
        if output not in by_path:
            raise WorkflowError("promotion source is not an approved run output")
        logical = "@campaign/" + target
        destination = engine.store.publication_target(logical)
        actual = digest(destination.read_bytes()) if destination.exists() else None
        if actual != run.task["promotion_before"][target]:
            raise WorkflowError(f"live promotion target changed: {target}")
        before[logical] = actual
        after[logical] = engine.store.preserve_bytes(engine.store.bytes(by_path[output]), path=str(destination), label="derived")
    state.applications.append(Application(id=key, run_id=run_id, finding_ids=[], before=before, after=after, at=now()))
    engine.store.publish(state, after, expected_revision=state.revision)
    return False


def promotion_scope(engine, state, *, run_id: str, promotions: dict[str, str]):
    run = run_by_id(state, run_id)
    if run.stage != "memory" or run.approval:
        raise WorkflowError("choose promotion targets on an unapproved memory draft")
    require_fresh(engine.store, state, run)
    if not promotions or len(set(promotions.values())) != len(promotions):
        raise WorkflowError("explicit unique promotion targets required")
    before = {}
    for output, target in promotions.items():
        if output not in {e.path for e in run.outputs}:
            raise WorkflowError("promotion must reference an output of this memory run")
        destination = engine.store.publication_target("@campaign/" + target)
        before[target] = digest(destination.read_bytes()) if destination.exists() else None
    run.task["promotions"] = promotions
    run.task["promotion_before"] = before
