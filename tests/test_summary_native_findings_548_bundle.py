"""Regression tests for the #548 review findings on the managed grounding
bundle's readers and migration.

Each test names the defect it pins. Every one of them failed on the code the
review was run against (origin/main at ffeb8ec).
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest
import yaml

from campaignlib.config import assemble_docs, load_config, load_file
import campaignlib.grounding_bundle as grounding_bundle
from campaignlib.grounding_bundle import refuse_managed_write
from pipelines.summary_native.promotion.errors import PromotionPathError
from server import migrate_grounding_bundle as migration


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
_SPEC = importlib.util.spec_from_file_location("findings_548_factory", FACTORY_PATH)
assert _SPEC and _SPEC.loader
FACTORY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(FACTORY)


def _campaign(tmp_path: Path, baseline: str = "legacy", *, migrate: bool = True) -> Path:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline=baseline)
    (root / "docs/authority/.lock").touch()
    if migrate:
        plan = migration.plan_migration(root)
        migration.apply_migration(root, plan["plan_sha256"])
    return root


def _live(root: Path) -> Path:
    return root / "docs/grounding" / os.readlink(root / "docs/grounding/current")


# ── 1. /promote bypassed the whole-bundle gate ───────────────────────────────

def test_ensemble_promote_cannot_write_into_the_managed_live_generation(tmp_path, monkeypatch):
    """Defect: POST /api/ensemble/promote copied an unreviewed draft straight
    into generations/<id>/live for any managed member — including the timeline
    and an arbitrary new docs/reference/<anything> — bypassing the reviewed
    whole-bundle gate (spec US1 #6). It must refuse with the whole-bundle
    instructions and leave the live generation untouched."""
    from fastapi.testclient import TestClient
    from server.main import app

    root = _campaign(tmp_path)
    monkeypatch.chdir(root)
    (root / "draft.md").write_text("UNREVIEWED DRAFT\n", encoding="utf-8")
    live = _live(root)
    before = {path: path.read_bytes() for path in live.rglob("*") if path.is_file()}

    client = TestClient(app)
    for target in ("docs/world_state.md", "docs/canon_events_timeline.md", "docs/reference/injected.md"):
        response = client.post("/api/ensemble/promote", json={"draft": "draft.md", "live": target})
        assert response.status_code == 409, target
        body = response.json()
        assert body["ok"] is False
        assert body["code"] == "PROMOTION_WHOLE_BUNDLE_REQUIRED"
        assert "summary_native promote" in body["message"]

    after = {path: path.read_bytes() for path in live.rglob("*") if path.is_file()}
    assert after == before
    assert not (live / "reference/injected.md").exists()


# ── 2. A completed absent migration is a valid layout ────────────────────────

def test_absent_baseline_lets_unrelated_documents_load(tmp_path):
    """Defect: after a completed ``absent`` migration, inspect_layout raised
    PROMOTION_MIGRATION_REQUIRED, so assemble_docs of an unrelated document
    (mechanics) failed although nothing about it is managed."""
    root = _campaign(tmp_path, "pristine")
    (root / "docs/mechanics.md").write_text("# Mechanics\n\nArc scores.\n", encoding="utf-8")
    config, base = load_config(str(root / "config/config.yaml"))
    config["documents"].append({"label": "mechanics", "path": "../docs/mechanics.md"})
    assert "Arc scores." in assemble_docs(config, ["mechanics"], base)


def test_absent_baseline_refuses_a_managed_read_with_a_clear_code(tmp_path):
    """Defect: a managed read on an absent baseline reported
    PROMOTION_MIGRATION_REQUIRED for a campaign that had already migrated.
    It must say no generation is published yet and how to publish one."""
    root = _campaign(tmp_path, "pristine")
    config, base = load_config(str(root / "config/config.yaml"))
    not_published = getattr(grounding_bundle, "GroundingNotPublished", None)
    assert not_published is not None, "no distinct not-published refusal exists"
    with pytest.raises(not_published) as caught:
        assemble_docs(config, ["world_state"], base)
    assert caught.value.code == "PROMOTION_NO_GENERATION"
    assert "summary_native promote" in str(caught.value)
    with pytest.raises(not_published):
        load_file("../docs/grounding/current/party.md", root / "config")


def test_absent_baseline_campaign_paths_do_not_500(tmp_path):
    """Defect: GET /api/config/campaign-paths raised from inspect_layout on an
    absent baseline and returned 500."""
    from fastapi.testclient import TestClient
    from server.main import app

    root = _campaign(tmp_path, "pristine")
    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/config/campaign-paths", params={"campaign_dir": str(root), "session_dir": str(root)},
    )
    assert response.status_code == 200
    assert response.json()["world_state"] == ""


@pytest.mark.parametrize("baseline", ["pristine", "legacy"])
def test_rerunning_the_migrator_reports_the_completed_migration(tmp_path, capsys, baseline):
    """Defect: re-running --dry-run on a migrated campaign planned a new
    migration (absent: a new plan sha whose apply created a second migration
    operation) or refused with PROMOTION_MIGRATION_REQUIRED (active)."""
    root = _campaign(tmp_path, baseline)
    operations = sorted(path.name for path in (root / "docs/grounding/migrations").iterdir())
    first = json.loads((root / "docs/grounding/layout.json").read_text())["migration_operation_id"]

    assert migration.main(["--campaign-dir", str(root), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["code"] == "PROMOTION_MIGRATION_COMPLETE"
    assert payload["data"]["operation_id"] == first

    replanned = migration.plan_migration(root)
    applied = migration.apply_migration(root, replanned["plan_sha256"])
    assert applied["operation_id"] == first
    assert sorted(path.name for path in (root / "docs/grounding/migrations").iterdir()) == operations


def test_absent_baseline_refuses_generated_writes_to_managed_paths(tmp_path):
    """Defect: refuse_managed_write swallowed PROMOTION_MIGRATION_REQUIRED on an
    absent baseline, so grounding generators could write a loose
    docs/world_state.md where the managed alias belongs."""
    root = _campaign(tmp_path, "pristine")
    for target in ("docs/world_state.md", "docs/grounding/current/world_state.md", "docs/reference/npcs.md"):
        with pytest.raises(PromotionPathError, match="cannot be replaced individually"):
            refuse_managed_write(root / target, root, draft_hint="docs/world_state.generated.md")
    refuse_managed_write(root / "docs/notes.md", root, draft_hint="unused")


# ── 3. load_file rejected every `..` path once docs/grounding existed ────────

def test_load_file_accepts_config_relative_and_session_relative_paths(tmp_path):
    """Defect: load_file raised "path traversal is not allowed" for any path
    containing `..` once docs/grounding existed — the documented
    load_file("../docs/x.md", config_dir) form for unrelated and managed docs,
    and `sd_plan --party ../../docs/party.md` from a session directory."""
    root = _campaign(tmp_path)
    (root / "docs/unrelated-notes.md").write_text("plain notes\n", encoding="utf-8")
    session = root / "summaries/session-01"
    session.mkdir(parents=True)
    party = (_live(root) / "party.md").read_text(encoding="utf-8")

    assert load_file("../docs/unrelated-notes.md", root / "config") == "plain notes\n"
    assert load_file("../docs/party.md", root / "config") == party
    assert load_file("../../docs/party.md", session) == party


# ── 4. Migration crash window between moving a path aside and linking it ─────

def test_crash_after_reference_tree_is_moved_aside_recovers_forward(tmp_path, monkeypatch):
    """Defect: each alias was unlinked/rmtree'd and only then linked; a crash
    in between left the path absent and recovery refused forever with
    "managed path changed during migration". The reference tree is now moved
    into the operation journal (never deleted) and recovery completes."""
    root = _campaign(tmp_path, migrate=False)
    plan = migration.plan_migration(root)

    def crash(phase: str) -> None:
        if phase == "reference_displaced":
            raise KeyboardInterrupt("simulated crash")

    monkeypatch.setattr(migration, "_failpoint", crash)
    with pytest.raises(KeyboardInterrupt):
        migration.apply_migration(root, plan["plan_sha256"])
    assert not os.path.lexists(root / "docs/reference")
    monkeypatch.setattr(migration, "_failpoint", lambda _phase: None)

    receipt = migration.recover_migration(root, plan["operation_id"])
    assert receipt["state"] == "committed"
    assert migration.verify_migration(root)["valid"] is True
    operation = root / "docs/grounding/migrations" / plan["operation_id"]
    assert (operation / "displaced/docs/reference").is_dir()
    assert (operation / "originals/docs/reference").is_dir()


def test_file_alias_never_has_a_gap_and_a_removed_file_still_recovers(tmp_path, monkeypatch):
    """Defect (same window, file aliases): the loose file was unlinked before
    the link existed. A link now replaces the file in one rename; and a
    campaign interrupted in the old gap (file already gone, original retained
    in originals/) recovers instead of refusing."""
    root = _campaign(tmp_path, migrate=False)
    plan = migration.plan_migration(root)
    original_link = migration._symlink_atomic

    def crash_on_world_state(path: Path, target: str) -> None:
        if path.name == "world_state.md" and path.parent.name == "docs":
            raise KeyboardInterrupt("simulated crash before linking")
        original_link(path, target)

    monkeypatch.setattr(migration, "_symlink_atomic", crash_on_world_state)
    with pytest.raises(KeyboardInterrupt):
        migration.apply_migration(root, plan["plan_sha256"])
    assert (root / "docs/world_state.md").is_file()  # no gap: still the loose file
    monkeypatch.setattr(migration, "_symlink_atomic", original_link)

    # Reproduce the old code's interrupted state: file gone, original retained.
    (root / "docs/world_state.md").unlink()
    receipt = migration.recover_migration(root, plan["operation_id"])
    assert receipt["state"] == "committed"
    assert migration.verify_migration(root)["valid"] is True


# ── 5. Path resolution pinned a generation ───────────────────────────────────

def test_platform_paths_keep_managed_aliases_lexical(tmp_path):
    """Defect: resolve_path / relativize_path used Path.resolve(), following
    docs/party.md into generations/<id>/live; saving session_doc.yaml then
    stored a generation-pinned path that kept reading a retired generation
    after the next promotion."""
    from server.platform_config_service import PlatformConfigService

    root = _campaign(tmp_path)
    service = PlatformConfigService(root)
    assert service.relativize_path(str(root / "docs/party.md"), base="campaign") == "docs/party.md"
    assert service.resolve_path("docs/party.md") == str(root / "docs/party.md")
    assert service.resolve_path("docs/reference/npcs.md") == str(root / "docs/reference/npcs.md")
    assert "generations" not in service.resolve_path("docs/grounding/current/party.md")


def test_polish_captures_party_and_context_before_the_agent_loop(tmp_path, monkeypatch):
    """Defect: polish read --party with read_text on a resolve()d path (pinned
    to one generation) and read each --context lazily per agent turn, so a
    change to the bundle during the loop reached the model mid-run. Both are
    now captured once, through the managed snapshot, before the loop."""
    from pipelines.ensemble import polish

    root = _campaign(tmp_path)
    monkeypatch.chdir(root)
    live = _live(root)
    captured_context = (live / "world_state.md").read_text(encoding="utf-8")
    doc = root / "session.md"
    doc.write_text("# Session\n\n---\n\n## Mara Vale\n\nWe walked the road.\n", encoding="utf-8")
    (root / "voice").mkdir()
    seen: dict[str, object] = {}

    def fake_loop(client, *, system, ctx, model, max_iterations, trace, verbose):
        (live / "world_state.md").write_text("CHANGED DURING THE RUN\n", encoding="utf-8")
        seen["context"] = polish.tool_read_context_doc({"name": "world_state"}, ctx)
        return True, "done"

    monkeypatch.setattr(polish, "load_party_config_arg", lambda _value: object())
    monkeypatch.setattr(polish, "require_from_config", lambda *_args, **_kwargs: "- Mara Vale: human fighter")
    monkeypatch.setattr(polish, "roster_from_config", lambda _cfg: "- Mara Vale: human fighter")
    monkeypatch.setattr(polish, "load_declared_voices", lambda _cfg: {})
    monkeypatch.setattr(polish, "client_from_args", lambda _args: object())
    monkeypatch.setattr(polish, "run_agent_loop", fake_loop)
    monkeypatch.setattr(sys, "argv", [
        "polish", str(doc), "--recap", str(doc), "--voice-dir", str(root / "voice"),
        "--party", "docs/party.md", "--party-config", "config/party.yaml",
        "--context", "docs/world_state.md",
        "--output", str(root / "out.md"), "--changelog", str(root / "changes.json"),
        "--no-log", "--config", str(root / "config/config.yaml"),
    ])
    polish.main()
    assert seen["context"] == {"name": "world_state", "text": captured_context}


# ── 6. The migrator rewrote config.yaml destructively ────────────────────────

def test_migration_preserves_config_text_and_file_modes(tmp_path):
    """Defect: the migrator re-dumped config.yaml with yaml.safe_dump
    (sort_keys=True), dropping comments and re-sorting keys, and
    atomic_write_bytes created 0600 files, so the config and every copied
    member lost their 0644 mode."""
    root = _campaign(tmp_path, migrate=False)
    config = root / "config/config.yaml"
    original = config.read_text(encoding="utf-8")
    config.write_text("# GM: hand note, keep me\nzz_last: 1\n" + original, encoding="utf-8")
    os.chmod(config, 0o644)
    os.chmod(root / "docs/world_state.md", 0o644)

    plan = migration.plan_migration(root)
    migration.apply_migration(root, plan["plan_sha256"])

    text = config.read_text(encoding="utf-8")
    expected = ("# GM: hand note, keep me\nzz_last: 1\n" + original).replace(
        "../docs/world_state.md", "../docs/grounding/current/world_state.md",
    ).replace("../docs/campaign_state.md", "../docs/grounding/current/campaign_state.md").replace(
        "../docs/party.md", "../docs/grounding/current/party.md",
    ).replace("../docs/planning.md", "../docs/grounding/current/planning.md")
    assert text == expected
    assert stat.S_IMODE(config.stat().st_mode) == 0o644
    assert stat.S_IMODE((_live(root) / "world_state.md").stat().st_mode) == 0o644
    assert {change["where"] for change in plan["config"]["changes"]} == {
        "documents[0].path", "documents[1].path", "documents[2].path", "documents[3].path",
    }


def test_dry_run_with_a_yaml_date_in_config_returns_an_envelope(tmp_path, capsys):
    """Defect: a YAML date anywhere in config.yaml crashed --dry-run with
    TypeError from json.dumps instead of returning the JSON envelope."""
    root = _campaign(tmp_path, migrate=False)
    config = root / "config/config.yaml"
    config.write_text("session_date: 2024-05-01\n" + config.read_text(encoding="utf-8"), encoding="utf-8")
    assert migration.main(["--campaign-dir", str(root), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["config"]["after"]["session_date"] == "2024-05-01"
    migration.apply_migration(root, payload["data"]["plan_sha256"])
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["session_date"].isoformat() == "2024-05-01"


# ── 7. Migrator refusals escaped as tracebacks; new_workspace's note was wrong ─

def test_missing_authority_lock_is_an_envelope_with_the_prerequisite_commands(tmp_path, capsys):
    """Defect: main caught only MigrationError, so AUTH_LOCK_MISSING on a fresh
    workspace escaped as a traceback instead of the JSON envelope."""
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    lock = root / "docs/authority/.lock"
    if lock.exists():
        lock.unlink()
    plan = migration.plan_migration(root)
    code = migration.main(["--campaign-dir", str(root), "--plan-sha256", plan["plan_sha256"], "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code != 0
    assert payload["ok"] is False
    assert payload["code"] == "AUTH_LOCK_MISSING"
    assert "summary_native review init" in payload["message"]

    # Following the named command really does unblock the apply.
    from pipelines.summary_native import cli as summary_native
    assert summary_native.main(["review", "init", "--campaign-dir", str(root), "--json"]) == 0
    capsys.readouterr()
    assert migration.main(["--campaign-dir", str(root), "--plan-sha256", plan["plan_sha256"], "--json"]) == 0


def test_new_workspace_note_names_a_sequence_that_actually_migrates(tmp_path, monkeypatch, capsys):
    """Defect: new_workspace told the GM to run
    `migrate_grounding_bundle plan --campaign-dir .`, an argparse error, and
    omitted the authority/review initialization the migrator needs. Every
    command in the note is run here, in order, on a fresh workspace."""
    from pipelines.summary_native import cli as summary_native
    from pipelines.workspace import new_workspace

    workspace = tmp_path / "ws"
    monkeypatch.setattr(sys, "argv", ["new_workspace", str(workspace)])
    new_workspace.main()
    note = (workspace / "docs/grounding-migration-required.md").read_text(encoding="utf-8")
    block = note.split("```bash\n", 1)[1].split("```", 1)[0]
    commands = [line.split() for line in block.splitlines() if line and not line.startswith("#")]
    assert [command[0] for command in commands] == [
        "summary_native", "summary_native",
        "migrate_grounding_bundle", "migrate_grounding_bundle", "migrate_grounding_bundle",
    ]
    monkeypatch.chdir(workspace)
    capsys.readouterr()
    plan_sha = None
    for command in commands:
        argv = command[1:]
        if "--plan-sha256" in argv:
            # the note's placeholder is the dry run's data.plan_sha256
            argv = argv[:argv.index("--plan-sha256") + 1] + [plan_sha, "--json"]
        runner = summary_native.main if command[0] == "summary_native" else migration.main
        assert runner(argv) == 0, (command, capsys.readouterr().out)
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True, payload
        if "--dry-run" in argv:
            plan_sha = payload["data"]["plan_sha256"]
    assert migration.verify_migration(workspace)["valid"] is True


# ── 8. sd_narrate relabelled a --context failure as PARTY_UNREADABLE ────────

def test_unreadable_context_refuses_as_context_unreadable(tmp_path, monkeypatch):
    """Defect: grouping --party, --context and --known-lore into one snapshot
    put all three in the --party try block, so an unreadable --context refused
    as PARTY_UNREADABLE."""
    import test_narration_bundle_cli as bundle
    from session_doc import sd_narrate

    import shutil

    monkeypatch.chdir(tmp_path)
    plan = tmp_path / "plan.md"
    shutil.copyfile(bundle.CORPUS / "plan.md", plan)
    recap = tmp_path / "recap.md"
    recap.write_text("# Recap\n", encoding="utf-8")
    shutil.copytree(bundle.CORPUS / "raw", tmp_path / "raw")
    campaign = {"plan": plan, "recap": recap, "raw": tmp_path / "raw",
                "out": tmp_path / "narration", "report": tmp_path / "reports/test-run.json"}
    bad = tmp_path / "context.md"
    bad.write_bytes(b"\xff\xfe not utf-8")
    recorder, clients = bundle._run(monkeypatch, campaign, "unused", "--context", str(bad))
    with pytest.raises(SystemExit):
        sd_narrate.main()
    report = json.loads(campaign["report"].read_text(encoding="utf-8"))
    assert report["rejected"][0]["code"] == "CONTEXT_UNREADABLE"
    assert recorder.calls == [] and clients == []


# ── 9. prep re-read grounding per beat ───────────────────────────────────────

def test_prep_session_captures_grounding_once_for_every_beat(tmp_path, monkeypatch):
    """Defect: run_session called assemble_docs once per beat with model calls
    in between, so a promotion mid-run handed later beats a different
    generation. The grounding is captured once before the first model call."""
    from pipelines.session_prep import prep

    root = _campaign(tmp_path)
    live = _live(root)
    config, base = load_config(str(root / "config/config.yaml"))
    config["system_prompt"] = "config/system_prompt.md"
    prompts: list[str] = []

    def fake_llm(client, system, user, model, batch=False):
        prompts.append(user)
        (live / "world_state.md").write_text(f"CHANGED AFTER BEAT {len(prompts)}\n", encoding="utf-8")
        return "encounter"

    monkeypatch.setattr(prep, "_call_llm", fake_llm)
    prep.run_session(object(), config, "1. Travel\n2. Climb\n", "single", "model",
                     clipboard=False, no_log=True, base_dir=base)
    assert len(prompts) == 2
    grounding = [prompt.split("## Session Beat")[0] for prompt in prompts]
    assert grounding[0] == grounding[1]
    assert "CHANGED AFTER BEAT" not in grounding[1]
