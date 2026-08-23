"""Guardrails that the metered/per-scene extraction path (`run_scene_extraction`)
is untouched by the batched engine (`run_batched_scene_extraction`) landing
alongside it — specs/013-batched-scene-extraction, T034, SC-008.

Research D1 chose `run_batched_scene_extraction` as a SIBLING function rather
than a `batched=` flag bolted onto `run_scene_extraction` precisely so the
per-scene loop could stay byte-for-byte unchanged. This file is the automated
check on that promise: call count, default caching behaviour, and the
`ExtractKnobs.tokens` default all stay exactly what they were before 013.

It also adds the one FR-019 assertion the phase was missing: the batched path
honours the same Stage 1 -> Stage 2 human gate as the per-scene path — a
gm-assist summary with no `## Scenes` section yields no scenes to extract,
and the engine must refuse (`SystemExit`) rather than silently no-op.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import campaignlib  # noqa: E402
from server.session_editor_config_shared import ExtractKnobs  # noqa: E402


# ── SC-008: the metered/per-scene path is untouched ─────────────────────────

def test_run_scene_extraction_still_makes_exactly_one_call_per_scene(tmp_path):
    """SC-008: `run_batched_scene_extraction` landing alongside it must not
    change `run_scene_extraction`'s call count — one `stream_api` call per
    scene, no more, no fewer."""
    scenes = [
        {"name": "Scene A", "body": "- a"},
        {"name": "Scene B", "body": "- b"},
        {"name": "Scene C", "body": "- c"},
    ]
    calls: list = []

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        calls.append(user)
        return "moments"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        out = campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=tmp_path, model="m",
            extraction_instruction="{name} {body}",
        )

    assert len(calls) == len(scenes)
    assert len(out) == len(scenes)


def test_run_scene_extraction_still_caches_system_by_default(tmp_path):
    """SC-008: `run_scene_extraction`'s default `cache_system=True` (passed
    to `stream_api` as `cache_system=cache_vtt`, `cache_vtt` defaulting to
    True) is unchanged by the batched engine landing."""
    scenes = [{"name": "Scene A", "body": "- a"}, {"name": "Scene B", "body": "- b"}]
    cache_flags: list = []

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        cache_flags.append(cache_system)
        return "moments"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=tmp_path, model="m",
            extraction_instruction="{name} {body}",
        )

    assert cache_flags == [True, True]


def test_extract_knobs_tokens_default_still_8192():
    """SC-008: `ExtractKnobs.tokens` — Stage 2's per-scene `--max-tokens`
    default, exposed to the Session Doc Editor — stays 8192, matching
    `scene_extract.py`'s own per-scene default exactly, so a campaign that
    has never touched this field sees no behaviour change from the batched
    engine landing. (`batch_tokens`, the separate per-GROUP ceiling, is
    independent — see `ExtractKnobs`'s own docstring.)"""
    knobs = ExtractKnobs()
    assert knobs.tokens == 8192


# ── FR-019: the Stage 1 -> Stage 2 human gate applies to the batched path too ──

def test_run_batched_scene_extraction_refuses_a_summary_with_no_scenes_section(tmp_path):
    """FR-019: `parse_gmassist_scenes` returns `[]` for a gm-assist summary
    with no `## Scenes` section — the signal that no human-verified scene
    structure exists yet. `run_scene_extraction` already refuses that input
    with `SystemExit` rather than silently no-op'ing (see
    `test_run_scene_extraction_empty_scenes_exits` in test_scene_extract.py);
    `run_batched_scene_extraction` must refuse the same way. This is the
    Stage 1 -> Stage 2 human gate, and until this test it had no coverage."""
    summary_without_scenes = "# Session\n\n## Summary\n\nNothing here.\n"
    scenes = campaignlib.parse_gmassist_scenes(summary_without_scenes)
    assert scenes == []

    with pytest.raises(SystemExit):
        campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=tmp_path / "out", model="m",
            user_template="{scene_blocks}",
        )
