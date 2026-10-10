from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipelines.summary_native.claims.extract import extract_candidates
from pipelines.summary_native.claims.imports import bind_candidates, import_candidates
from pipelines.summary_native.claims.check import check_claims
from pipelines.summary_native.claims.packets import assemble_packet
from pipelines.summary_native.claims.selection import (
    confirm_selection,
    mandatory_source_closure,
    select_whole_source_chunks,
)
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.manifest import build_bundle_selection


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("claims_extract_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _inputs(tmp_path: Path):
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    bundle = build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="claims-selection",
        rule_versions=("claims/1",), config_path=root / "config/grounding.yaml",
    )
    proposed = mandatory_source_closure(
        root, bundle, effective_horizon="through-chapter-3", audience="gm",
        rule_versions=("claims/1",),
    )
    proposed = select_whole_source_chunks(
        root, proposed, tuple(source.source_id for source in proposed.sources[:3])
    )
    selection = confirm_selection(proposed, reviewer="gm", confirmed_at=NOW)
    return root, selection, assemble_packet(root, selection)


def _proposal(chunk, occurrence: str = "candidate-1") -> str:
    raw = chunk.text.encode("utf-8")
    end = min(len(raw), 12)
    while end and _invalid_utf8(raw[:end]):
        end -= 1
    span = raw[:end].decode("utf-8")
    return json.dumps({"annotations": [{
        "occurrence_id": occurrence, "chunk_id": chunk.chunk_id,
        "start_byte": 0, "end_byte": end, "original_span": span,
        "subject_id": "subject-1", "predicate": "status",
        "normalized_value": "active", "certainty": "possible", "audience": "gm",
    }]})


def _invalid_utf8(value: bytes) -> bool:
    try:
        value.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def test_unknown_candidate_subject_remains_unresolved_and_nonmechanical(tmp_path: Path) -> None:
    root, selection, packet = _inputs(tmp_path)
    chunk = packet.chunks[0]
    payload = json.loads(_proposal(chunk))
    payload["annotations"][0]["subject_id"] = "does-not-exist"
    payload["annotations"][0]["subject_kind"] = "entity"
    annotations = bind_candidates(selection, packet, payload, origin="human_candidate", campaign_dir=root)
    assert annotations[0].subject_id is None
    assert annotations[0].subject_identity_kind == "entity"
    assert annotations[0].subject_identity_resolved is False
    analysis = check_claims(selection, annotations)
    assert analysis.findings and all(item.basis != "mechanical" for item in analysis.findings)


def test_ambiguous_explicit_alias_never_enters_mechanical_comparison(tmp_path: Path) -> None:
    root, selection, packet = _inputs(tmp_path)
    (root / "docs/entity_registry.yaml").write_text(
        "version: 1\ncampaign: fixture\nentities:\n"
        "  - {name: Alpha, type: npc, aliases: [Shared Name]}\n"
        "  - {name: Beta, type: npc, aliases: [Shared Name]}\n",
        encoding="utf-8",
    )
    chunk = packet.chunks[0]
    payload = json.loads(_proposal(chunk))
    payload["annotations"][0]["subject_id"] = "Shared Name"
    payload["annotations"][0]["subject_kind"] = "entity"
    annotations = bind_candidates(selection, packet, payload, origin="human_candidate", campaign_dir=root)
    assert annotations[0].subject_id is None and not annotations[0].subject_identity_resolved
    assert all(item.basis != "mechanical" for item in check_claims(selection, annotations).findings)


def test_extract_calls_exact_selected_chunks_without_scope_expansion_or_chaining(tmp_path: Path) -> None:
    root, selection, packet = _inputs(tmp_path)
    chosen = (packet.chunks[0], packet.chunks[2])
    prompts: list[str] = []

    def invoke(prompt, chunk):
        prompts.append(prompt)
        assert chunk.text in prompt
        assert all(other.text not in prompt for other in packet.chunks if other.chunk_id != chunk.chunk_id)
        return _proposal(chunk, f"candidate-{len(prompts)}")

    result = extract_candidates(
        root, selection, packet, selected_chunk_ids=tuple(c.chunk_id for c in chosen),
        backend="fake", model="offline", prompt_version="claims-v1", rules="claims/1",
        invoke=invoke, now=lambda: NOW,
    )
    assert len(prompts) == 2
    assert result.run.chunk_ids == tuple(c.chunk_id for c in chosen)
    assert all(outcome.outcome == "completed" for outcome in result.run.outcomes)
    assert all(annotation.interpretation_state == "candidate" for annotation in result.annotations)


def test_invalid_and_failed_chunks_are_partial_artifacts_not_empty_success(tmp_path: Path) -> None:
    root, selection, packet = _inputs(tmp_path)
    chosen = packet.chunks[:3]
    calls = 0

    def invoke(_prompt, chunk):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _proposal(chunk, "valid-one")
        if calls == 2:
            return "not-json"
        raise RuntimeError("provider unavailable")

    result = extract_candidates(
        root, selection, packet, selected_chunk_ids=tuple(c.chunk_id for c in chosen),
        backend="fake", model="offline", prompt_version="claims-v1", rules="claims/1",
        invoke=invoke, now=lambda: NOW,
    )
    assert [item.outcome for item in result.run.outcomes] == ["completed", "invalid_output", "failed"]
    assert result.run.completed_at is None
    assert result.run.failure_detail
    assert [item.occurrence_id for item in result.annotations] == ["valid-one"]
    assert (result.path / "run.json").is_file()


def test_cache_identity_and_force_create_explicit_immutable_revision(tmp_path: Path) -> None:
    root, selection, packet = _inputs(tmp_path)
    chunk = packet.chunks[0]
    calls = 0

    def invoke(_prompt, selected):
        nonlocal calls
        calls += 1
        return _proposal(selected)

    kwargs = dict(
        selected_chunk_ids=(chunk.chunk_id,), backend="fake", model="offline",
        prompt_version="claims-v1", rules="claims/1", invoke=invoke, now=lambda: NOW,
    )
    first = extract_candidates(root, selection, packet, **kwargs)
    cached = extract_candidates(root, selection, packet, **kwargs)
    forced = extract_candidates(root, selection, packet, force=True, **kwargs)
    assert calls == 2
    assert cached.cached and cached.path == first.path and cached.run.revision == 1
    assert forced.run.run_id == first.run.run_id and forced.run.revision == 2
    assert forced.path != first.path and first.path.is_dir()


def test_completed_and_failed_cache_replay_preserve_truthful_state(tmp_path: Path) -> None:
    root, selection, packet = _inputs(tmp_path)
    completed_chunk, failed_chunk = packet.chunks[:2]
    base = dict(
        backend="fake", model="offline", prompt_version="claims-v1",
        rules="claims/1", now=lambda: NOW,
    )
    completed = extract_candidates(
        root, selection, packet, selected_chunk_ids=(completed_chunk.chunk_id,),
        invoke=lambda _prompt, chunk: _proposal(chunk, "completed-cache"), **base,
    )
    completed_replay = extract_candidates(
        root, selection, packet, selected_chunk_ids=(completed_chunk.chunk_id,),
        invoke=lambda *_args: pytest.fail("provider called for completed cache"), **base,
    )
    assert completed_replay.cached
    assert completed_replay.run.completed_at == completed.run.completed_at
    assert completed_replay.run.failure_detail is None

    def fail(_prompt, _chunk):
        raise RuntimeError("offline failure")

    failed = extract_candidates(
        root, selection, packet, selected_chunk_ids=(failed_chunk.chunk_id,),
        invoke=fail, **base,
    )
    failed_replay = extract_candidates(
        root, selection, packet, selected_chunk_ids=(failed_chunk.chunk_id,),
        invoke=lambda *_args: pytest.fail("provider called for failed cache"), **base,
    )
    assert failed_replay.cached
    assert failed_replay.run.completed_at is None
    assert failed_replay.run.failure_detail == failed.run.failure_detail
    assert failed_replay.run.outcomes[0].outcome == "failed"


def test_every_extraction_setting_invalidates_cache_and_chunk_bound_refuses_before_call(
    tmp_path: Path,
) -> None:
    root, selection, packet = _inputs(tmp_path)
    chunk = packet.chunks[0]
    calls = 0

    def invoke(_prompt, selected):
        nonlocal calls
        calls += 1
        return _proposal(selected)

    base = dict(
        selected_chunk_ids=(chunk.chunk_id,), backend="fake", model="offline",
        prompt_version="claims-v1", rules="claims/1", invoke=invoke, now=lambda: NOW,
    )
    first = extract_candidates(root, selection, packet, max_tokens=100, chunk_chars=100000, **base)
    changed = extract_candidates(
        root, selection, packet, max_tokens=101, chunk_chars=100000,
        system_prompt="changed exact system", output_schema="schema-v2",
        settings={"temperature": 0}, **base,
    )
    assert first.run.run_id != changed.run.run_id
    assert calls == 2
    with pytest.raises(PromotionError) as error:
        extract_candidates(root, selection, packet, chunk_chars=1, **base)
    assert error.value.code == "CLAIMS_CHUNK_TOO_LARGE"
    assert calls == 2


def test_malformed_partial_cache_is_refused_and_duplicate_ids_persist_failure(
    tmp_path: Path,
) -> None:
    root, selection, packet = _inputs(tmp_path)
    chosen = packet.chunks[:2]

    result = extract_candidates(
        root, selection, packet, selected_chunk_ids=tuple(item.chunk_id for item in chosen),
        backend="fake", model="offline", prompt_version="claims-v1", rules="claims/1",
        invoke=lambda _prompt, chunk: _proposal(chunk, "duplicate-id"), now=lambda: NOW,
    )
    assert result.run.completed_at is None
    assert all(item.outcome == "invalid_output" for item in result.run.outcomes)
    assert (result.path / "run.json").is_file() and (result.path / "annotations.json").is_file()

    # The persisted evidence is deliberately diagnosable, but cannot be
    # trusted as a reusable completed cache revision.
    with pytest.raises(PromotionError) as error:
        extract_candidates(
            root, selection, packet, selected_chunk_ids=tuple(item.chunk_id for item in chosen),
            backend="fake", model="offline", prompt_version="claims-v1", rules="claims/1",
            invoke=lambda *_args: pytest.fail("provider invoked for corrupt cache"), now=lambda: NOW,
        )
    assert error.value.code == "CLAIMS_EXTRACT_CACHE_INVALID"

    # A partial run whose annotation artifact disappears is also an explicit
    # cache-integrity refusal, never silently treated as a miss or success.
    (result.path / "annotations.json").unlink()
    with pytest.raises(PromotionError, match="malformed"):
        extract_candidates(
            root, selection, packet, selected_chunk_ids=tuple(item.chunk_id for item in chosen),
            backend="fake", model="offline", prompt_version="claims-v1", rules="claims/1",
            invoke=lambda *_args: pytest.fail("provider invoked for malformed cache"), now=lambda: NOW,
        )


def test_human_import_binds_exact_excerpt_and_never_creates_authority(tmp_path: Path) -> None:
    root, selection, packet = _inputs(tmp_path)
    chunk = packet.chunks[0]
    path = import_candidates(root, selection, packet, _proposal(chunk, "human-one"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    annotation = payload["annotations"][0]
    assert payload["approved"] is False
    assert annotation["origin"] == "human_candidate"
    assert annotation["interpretation_state"] == "candidate"
    assert "mapping_event_id" not in annotation
    bad = json.loads(_proposal(chunk, "bad-span"))
    bad["annotations"][0]["original_span"] = "invented"
    with pytest.raises(PromotionError, match="excerpt"):
        import_candidates(root, selection, packet, bad)


def test_import_rejects_unselected_chunk_and_model_free_imports_do_not_load_extractor(tmp_path: Path) -> None:
    root, selection, packet = _inputs(tmp_path)
    raw = json.loads(_proposal(packet.chunks[0]))
    raw["annotations"][0]["chunk_id"] = "not-selected"
    with pytest.raises(PromotionError) as error:
        import_candidates(root, selection, packet, raw)
    assert error.value.code == "CLAIMS_SCOPE_EXPANSION"

    code = (
        "import sys; import pipelines.summary_native.claims.models; "
        "import pipelines.summary_native.claims.imports; "
        "assert 'pipelines.summary_native.claims.extract' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parents[1], check=True)
