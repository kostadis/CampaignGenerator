from __future__ import annotations

import importlib
import os
import sys
import threading
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from campaignlib.config import assemble_docs, load_file, load_files_snapshot
from campaignlib.grounding_bundle import (
    MANAGED_FILES,
    open_grounding_snapshot,
    refuse_managed_write,
    write_managed_member,
)
from pipelines.summary_native.authority_apply import authority_lock
from pipelines.summary_native.promotion.errors import PromotionPathError, PromotionRecoveryRequired
from pipelines.summary_native.promotion.models import ActivationRecord, BaselineKind, ContentIdentity, GenerationKind, GenerationManifest
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest


def _campaign(tmp_path: Path) -> Path:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "docs/authority").mkdir(parents=True)
    (root / "docs/authority/.lock").write_bytes(b"")
    grounding = root / "docs/grounding"
    for generation in ("g-old", "g-new"):
        for state in ("live", "published"):
            tree = grounding / "generations" / generation / state
            (tree / "reference/nested").mkdir(parents=True)
            for name in MANAGED_FILES:
                (tree / name).write_text(f"{generation}:{name}\n", encoding="utf-8")
            (tree / "reference/nested/item.md").write_text(
                f"{generation}:reference\n", encoding="utf-8"
            )
    os.symlink("generations/g-old/live", grounding / "current")
    for name in MANAGED_FILES:
        os.symlink(f"grounding/current/{name}", root / "docs" / name)
    os.symlink("grounding/current/reference", root / "docs/reference")
    published = grounding / "generations/g-old/published"
    members = tuple(ContentIdentity(path=p.relative_to(published).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest(), size=p.stat().st_size) for p in sorted(published.rglob("*")) if p.is_file())
    values = dict(generation_id="g-old", operation_id="fixture-op", campaign_id="fixture", selected_range=None,
                  kind=GenerationKind.LEGACY_ADOPTION, members=members, retained_records=(), external_dependencies=(),
                  published_path="docs/grounding/generations/g-old/published", live_path="docs/grounding/generations/g-old/live",
                  created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), manifest_sha256="0" * 64)
    provisional = GenerationManifest.model_validate(values)
    values["manifest_sha256"] = canonical_digest(provisional, exclude_fields=frozenset({"manifest_sha256"}))
    manifest_bytes = canonical_bytes(GenerationManifest.model_validate(values))
    (grounding / "generations/g-old/manifest.json").write_bytes(manifest_bytes)
    activation = ActivationRecord(activation_id="baseline-fixture", operation_id="fixture-op", generation_id="g-old",
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(), migration_receipt_sha256=canonical_digest({
            "version": 1, "state": "committed", "operation_id": "fixture-op", "baseline": "legacy_adoption", "generation_id": "g-old"}),
        baseline_kind=BaselineKind.LEGACY_BASELINE, actor="fixture", completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    (grounding / "activations").mkdir()
    (grounding / "activations/baseline-fixture.json").write_bytes(canonical_bytes(activation))
    receipt_base = {"version": 1, "state": "committed", "operation_id": "fixture-op", "baseline": "legacy_adoption", "generation_id": "g-old"}
    (grounding / "migrations/fixture-op").mkdir(parents=True)
    (grounding / "migrations/fixture-op/receipt.json").write_text(__import__('json').dumps({**receipt_base, "receipt_sha256": canonical_digest(receipt_base)}))
    (grounding / "layout.json").write_text('{"generation_id":"g-old","state":"active","version":1}\n')
    documents = "\n".join(
        f"  - label: {Path(name).stem}\n    path: ../docs/{name}"
        for name in sorted(MANAGED_FILES)
    )
    (root / "config/config.yaml").write_text(f"documents:\n{documents}\n", encoding="utf-8")
    return root


def _switch(root: Path, generation: str) -> None:
    current = root / "docs/grounding/current"
    replacement = current.with_name("current.next")
    replacement.unlink(missing_ok=True)
    os.symlink(f"generations/{generation}/live", replacement)
    os.replace(replacement, current)


def test_snapshot_captures_one_generation_and_manual_live_drift(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    live_party = root / "docs/grounding/generations/g-old/live/party.md"
    live_party.write_text("g-old:manual-edit\n", encoding="utf-8")

    with open_grounding_snapshot(root) as snapshot:
        _switch(root, "g-new")
        assert snapshot.generation_id == "g-old"
        assert snapshot.edited_since_publication is True
        assert {data.decode().split(":", 1)[0] for data in snapshot.members.values()} == {"g-old"}


def test_exclusive_writer_waits_for_shared_reader(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    started = threading.Event()
    finished = threading.Event()

    def write() -> None:
        started.set()
        write_managed_member(root, "party.md", b"human edit\n")
        finished.set()

    # The reader API holds this same shared lock while it captures bytes.  It
    # deliberately releases it before yielding the immutable snapshot.
    with authority_lock(root, exclusive=False, create=False):
        worker = threading.Thread(target=write, daemon=True)
        worker.start()
        assert started.wait(1)
        time.sleep(0.05)
        assert not finished.is_set()
    worker.join(2)
    assert finished.is_set()
    assert (root / "docs/party.md").read_bytes() == b"human edit\n"


@pytest.mark.parametrize(
    ("marker", "payload"),
    [
        ("migration-pending.json", '{"state":"pending"}\n'),
        ("operations/op-1/state.json", '{"state":"activation_pending"}\n'),
    ],
)
def test_pending_migration_or_activation_refuses_reads(
    tmp_path: Path, marker: str, payload: str
) -> None:
    root = _campaign(tmp_path)
    path = root / "docs/grounding" / marker
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(PromotionRecoveryRequired):
        with open_grounding_snapshot(root):
            pass


def test_detached_alias_refuses_actual_config_reader(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    alias = root / "docs/world_state.md"
    alias.unlink()
    alias.write_text("detached\n", encoding="utf-8")
    with pytest.raises(PromotionPathError, match="detached"):
        load_file(str(alias), root / "config")


@pytest.mark.parametrize(
    "target",
    [
        "docs/world_state.md",
        "docs/grounding/current/planning.md",
        "docs/grounding/generations/g-old/live/party.md",
    ],
)
def test_generated_writer_guard_recognizes_every_managed_spelling_from_any_cwd(
    tmp_path: Path, target: str
) -> None:
    root = _campaign(tmp_path)
    with pytest.raises(PromotionPathError, match="write a draft"):
        refuse_managed_write(
            root / target,
            tmp_path,
            draft_hint="docs/generated.md",
        )


def test_config_assembly_reads_all_selected_members_from_one_snapshot(tmp_path: Path) -> None:
    root = _campaign(tmp_path)
    config = {
        "documents": [
            {"label": "world_state", "path": "../docs/world_state.md"},
            {"label": "party", "path": "../docs/party.md"},
            {"label": "planning", "path": "../docs/planning.md"},
        ]
    }
    text = assemble_docs(config, ["world_state", "party", "planning"], root / "config")
    assert "g-old:world_state.md" in text
    assert "g-old:party.md" in text
    assert "g-old:planning.md" in text


def test_grouped_session_inputs_open_exactly_one_managed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _campaign(tmp_path)
    import campaignlib.grounding_bundle as bundle

    actual = bundle.open_grounding_snapshot
    calls: list[tuple[str, ...]] = []

    def counted(campaign_dir: Path, requested=None):
        calls.append(tuple(requested or ()))
        return actual(campaign_dir, requested)

    monkeypatch.setattr(bundle, "open_grounding_snapshot", counted)
    values = load_files_snapshot(
        [root / "docs/world_state.md", root / "docs/party.md", root / "docs/planning.md"],
        root,
    )
    assert len(calls) == 1
    assert set(calls[0]) == {"world_state.md", "party.md", "planning.md"}
    assert all(value.startswith("g-old:") for value in values)


def test_grouped_reader_infers_external_campaign_and_refuses_multiple_roots(
    tmp_path: Path
) -> None:
    first = _campaign(tmp_path / "first")
    second = _campaign(tmp_path / "second")
    live = first / "docs/grounding/generations/g-old/live/world_state.md"
    assert load_files_snapshot([live], tmp_path) == ["g-old:world_state.md\n"]
    with pytest.raises(PromotionPathError, match="multiple campaigns"):
        load_files_snapshot([first / "docs/party.md", second / "docs/party.md"], tmp_path)


def test_non_config_party_invocation_snapshots_resolved_generation_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _campaign(tmp_path)
    character = tmp_path / "character.md"
    character.write_text("# Character\n", encoding="utf-8")
    dump = tmp_path / "prompt.md"
    output = tmp_path / "party.generated.md"
    from pipelines.grounding import party

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "party",
            "--character",
            str(character),
            "--context",
            str(root / "docs/grounding/generations/g-old/live/world_state.md"),
            "--output",
            str(output),
            "--dump-input",
            str(dump),
            "--dump-only",
        ],
    )
    monkeypatch.setattr(
        party,
        "resolve_cli_model",
        lambda *_args, **_kwargs: SimpleNamespace(effective_model="test-model"),
    )
    monkeypatch.setattr(party, "client_from_args", lambda _args: object())
    monkeypatch.setattr(party, "load_alias_map_or_exit", lambda *_args, **_kwargs: {})
    party.main()
    assert "g-old:world_state.md" in dump.read_text(encoding="utf-8")


def test_mcp_config_label_and_party_fallback_refuse_pending_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _campaign(tmp_path)
    (root / "docs/grounding/migration-pending.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("CAMPAIGN_DIR", str(root))
    monkeypatch.setattr(sys, "argv", ["campaign-mcp"])
    sys.modules.pop("pipelines.rlm.mcp_server", None)
    module = importlib.import_module("pipelines.rlm.mcp_server")

    with pytest.raises(PromotionRecoveryRequired):
        module._read_doc("world_state")
    module._doc_index["party"] = None
    with pytest.raises(PromotionRecoveryRequired):
        module.get_party()


def test_session_context_entrypoint_refuses_before_model_or_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _campaign(tmp_path)
    (root / "docs/grounding/migration-pending.json").write_text("{}\n", encoding="utf-8")
    recap = root / "recap.md"
    recap.write_text("recap\n", encoding="utf-8")
    output = root / "report.md"
    from session_doc import sd_consistency

    # The command may run from a session/tool directory outside the campaign;
    # absolute managed selections still inherit the selected campaign's state.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sd-consistency",
            str(recap),
            "--context",
            str(root / "docs/world_state.md"),
            str(root / "docs/party.md"),
            "--out",
            str(output),
        ],
    )
    monkeypatch.setattr(
        sd_consistency,
        "resolve_cli_model",
        lambda *_args, **_kwargs: SimpleNamespace(effective_model="test-model"),
    )
    monkeypatch.setattr(sd_consistency, "canonical_context_section", lambda _root: "")
    monkeypatch.setattr(sd_consistency, "client_from_args", lambda _args: pytest.fail("model invoked"))

    with pytest.raises(PromotionRecoveryRequired):
        sd_consistency.main()
    assert not output.exists()


def test_narration_absolute_party_refuses_external_pending_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _campaign(tmp_path / "managed")
    (root / "docs/grounding/operations/op/state.json").parent.mkdir(parents=True)
    (root / "docs/grounding/operations/op/state.json").write_text(
        '{"state":"activation_pending"}\n', encoding="utf-8"
    )
    work = tmp_path / "session"
    scenes = work / "scenes"
    scenes.mkdir(parents=True)
    recap = work / "recap.md"
    recap.write_text("recap\n", encoding="utf-8")
    plan = work / "plan.md"
    plan.write_text(
        "## Section 1\nnarrator: Alice\nchunks: 1-1\nscene: Arrival\nfocus: arrival\n",
        encoding="utf-8",
    )
    (scenes / "01_arrival.md").write_text("- Alice arrives.\n", encoding="utf-8")
    from session_doc import sd_narrate

    monkeypatch.chdir(work)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sd-narrate",
            str(recap),
            "--plan",
            str(plan),
            "--scene-extractions",
            str(scenes),
            "--per-scene-output",
            str(work / "output"),
            "--party",
            str(root / "docs/party.md"),
        ],
    )
    monkeypatch.setattr(sd_narrate, "client_from_args", lambda _args: pytest.fail("model invoked"))
    with pytest.raises(PromotionRecoveryRequired):
        sd_narrate.main()


def test_platform_discovery_and_ensemble_fallback_surface_pending_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _campaign(tmp_path)
    session = root / "sessions/one"
    session.mkdir(parents=True)
    (root / "docs/grounding/migration-pending.json").write_text("{}\n", encoding="utf-8")

    from server.platform_config_service import PlatformConfigService
    from server.routers import ensemble

    with pytest.raises(PromotionRecoveryRequired):
        PlatformConfigService.discover_campaign_paths(str(root), str(session))
    monkeypatch.chdir(root)
    with pytest.raises(PromotionRecoveryRequired):
        ensemble._default_party_context("docs/ensemble/drafts")
