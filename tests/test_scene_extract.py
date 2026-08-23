"""Tests for scene-anchored VTT extraction (campaignlib + scene_extract + session_doc wiring)."""

import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaignlib
import session_doc
from session_doc import scene_extract as se

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── parse_gmassist_scenes ─────────────────────────────────────────────────────

GMASSIST_SAMPLE = """\
# Session 2026-04-28

Date: Apr 28th, 2026

## Scenes
### Farewell to Eldeth
#### The party enjoys the sunlight as Eldeth prepares to depart.
- Glabbagool looks up into the sun with his googly eyes.
- Eldeth declares she and Thorin are "like brothers".

### Shadows at Dusk
#### While traveling toward Candlekeep the party realizes they are stalked.
- Grygum rolls a 9 on insight and concludes the tracker is a deer.
- Thorin asks whether they are on a stone surface.

### A Shadow in the Woods
#### The party moves to intercept the tracker.
- Daz uses Misty Step to teleport into a tree.
- Zalthir teleports and Stunning-Strikes the spy.

## NPCs
### Eldeth
A dwarven warrior.
"""


def test_parse_gmassist_scenes_returns_ordered_scenes():
    scenes = campaignlib.parse_gmassist_scenes(GMASSIST_SAMPLE)
    assert [s["name"] for s in scenes] == [
        "Farewell to Eldeth",
        "Shadows at Dusk",
        "A Shadow in the Woods",
    ]


def test_parse_gmassist_scenes_preserves_body():
    scenes = campaignlib.parse_gmassist_scenes(GMASSIST_SAMPLE)
    assert "Glabbagool looks up into the sun" in scenes[0]["body"]
    assert "Stunning-Strikes the spy" in scenes[2]["body"]


def test_parse_gmassist_scenes_stops_at_next_top_heading():
    scenes = campaignlib.parse_gmassist_scenes(GMASSIST_SAMPLE)
    # No scene should leak content from the ## NPCs section.
    for s in scenes:
        assert "Eldeth\nA dwarven warrior" not in s["body"]


def test_parse_gmassist_scenes_no_scenes_section():
    assert campaignlib.parse_gmassist_scenes("# Session\n\n## Summary\n\nNothing here.") == []


def test_parse_gmassist_scenes_empty_scenes_section():
    text = "## Scenes\n\n## NPCs\n### Eldeth\nA warrior.\n"
    assert campaignlib.parse_gmassist_scenes(text) == []


# ── run_scene_extraction ──────────────────────────────────────────────────────

def test_run_scene_extraction_writes_one_file_per_scene(tmp_path):
    scenes = [
        {"name": "Farewell to Eldeth", "body": "- bullet 1\n- bullet 2"},
        {"name": "Shadows at Dusk", "body": "- bullet 3"},
    ]
    captured = []

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        captured.append({"system": system, "user": user, "cache": cache_system})
        return f"FAKE EXTRACTED MOMENTS for {scenes[len(captured) - 1]['name']}"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        out = campaignlib.run_scene_extraction(
            client=None,
            vtt_text="GM: hello\nThorin: hi",
            scenes=scenes,
            extract_dir=tmp_path / "out",
            model="claude-haiku-4-5-20251001",
            extraction_instruction="Scene: {name}\n\nBullets:\n{body}",
        )

    assert len(out) == 2
    assert out[0].name == "01_farewell_to_eldeth.md"
    assert out[1].name == "02_shadows_at_dusk.md"

    body0 = out[0].read_text(encoding="utf-8")
    assert body0.startswith("---\nscene: Farewell to Eldeth\n")
    assert "## Scene summary (from gm-assist, verbatim)" in body0
    assert "bullet 1" in body0
    assert "FAKE EXTRACTED MOMENTS" in body0


def test_run_scene_extraction_caches_system_by_default(tmp_path):
    scenes = [{"name": "Scene A", "body": "- thing"}]
    captured = []

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        captured.append(cache_system)
        return "moments"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=tmp_path, model="m",
            extraction_instruction="{name} {body}",
        )
    assert captured == [True]


def test_run_scene_extraction_resumes_existing_files(tmp_path):
    scenes = [
        {"name": "Scene A", "body": "- a"},
        {"name": "Scene B", "body": "- b"},
    ]
    (tmp_path / "01_scene_a.md").write_text("ALREADY DONE", encoding="utf-8")

    calls = []

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        calls.append(user)
        return "fresh"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=tmp_path, model="m",
            extraction_instruction="{name} {body}",
        )

    # Scene A was skipped (file existed), Scene B got the only API call.
    assert len(calls) == 1
    assert "Scene B" in calls[0]
    assert (tmp_path / "01_scene_a.md").read_text(encoding="utf-8") == "ALREADY DONE"


def test_run_scene_extraction_force_overwrites_and_snapshots_prev(tmp_path):
    """force=True: existing files are re-extracted; prior content is moved to
    <file>.prev when the new content differs; .reviewed sidecar is cleared."""
    scenes = [{"name": "Scene A", "body": "- a"}]
    (tmp_path / "01_scene_a.md").write_text(
        "OLD CONTENT — to be snapshotted", encoding="utf-8",
    )
    (tmp_path / "01_scene_a.md.reviewed").write_text("", encoding="utf-8")

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        return "FRESH MOMENTS"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=tmp_path, model="m",
            extraction_instruction="{name} {body}",
            force=True,
        )

    assert (tmp_path / "01_scene_a.md.prev").read_text(encoding="utf-8") == \
        "OLD CONTENT — to be snapshotted"
    assert "FRESH MOMENTS" in (tmp_path / "01_scene_a.md").read_text(encoding="utf-8")
    # .reviewed cleared since content changed
    assert not (tmp_path / "01_scene_a.md.reviewed").exists()


def test_run_scene_extraction_force_skips_overwrite_when_identical(tmp_path):
    """force=True: if the LLM returns byte-identical output, don't bump .prev
    or clear .reviewed — there's nothing to diff against."""
    scenes = [{"name": "Scene A", "body": "- a"}]
    # Write a file that exactly matches what format_scene_output will produce.
    expected = campaignlib.format_scene_output("Scene A", "- a", "MOMENTS")
    (tmp_path / "01_scene_a.md").write_text(expected, encoding="utf-8")
    (tmp_path / "01_scene_a.md.reviewed").write_text("", encoding="utf-8")

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        return "MOMENTS"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=tmp_path, model="m",
            extraction_instruction="{name} {body}",
            force=True,
        )

    assert not (tmp_path / "01_scene_a.md.prev").exists()
    assert (tmp_path / "01_scene_a.md.reviewed").exists()


def test_run_scene_extraction_default_still_skips_existing(tmp_path):
    """force=False (the default) preserves the resume-after-crash behavior:
    no API call, no .prev, file untouched."""
    scenes = [{"name": "Scene A", "body": "- a"}]
    (tmp_path / "01_scene_a.md").write_text("STAYS", encoding="utf-8")

    calls = []

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        calls.append(user)
        return "fresh"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=tmp_path, model="m",
            extraction_instruction="{name} {body}",
        )

    assert calls == []
    assert (tmp_path / "01_scene_a.md").read_text(encoding="utf-8") == "STAYS"
    assert not (tmp_path / "01_scene_a.md.prev").exists()


def test_snapshot_scene_for_rerun_no_existing_file(tmp_path):
    """No existing file → caller should write; nothing to snapshot."""
    out = tmp_path / "01_x.md"
    assert campaignlib.snapshot_scene_for_rerun(out, "new") is True
    assert not (tmp_path / "01_x.md.prev").exists()


def test_run_scene_extraction_empty_scenes_exits(tmp_path):
    with pytest.raises(SystemExit):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=[],
            extract_dir=tmp_path, model="m",
            extraction_instruction="x",
        )


# ── session_doc.load_scene_extractions ────────────────────────────────────────

def test_load_scene_extractions_parses_frontmatter_and_splits_body(tmp_path):
    (tmp_path / "01_farewell_to_eldeth.md").write_text(
        "---\n"
        "scene: Farewell to Eldeth\n"
        "source: gmassist\n"
        "---\n\n"
        "# Farewell to Eldeth\n\n"
        "## Scene summary (from gm-assist, verbatim)\n\n"
        "- bullet 1\n- bullet 2\n\n"
        "## Verbatim moments\n\n"
        "**[Glabbagool]**\n"
        "> \"oh!\"\n",
        encoding="utf-8",
    )
    (tmp_path / "02_shadows_at_dusk.md").write_text(
        "---\n"
        "scene: Shadows at Dusk\n"
        "---\n\n"
        "## Scene summary (from gm-assist, verbatim)\n\n"
        "summary text\n\n"
        "## Verbatim moments\n\n"
        "moments text\n",
        encoding="utf-8",
    )
    # Sibling artifacts should be ignored.
    (tmp_path / "plan.md").write_text("plan", encoding="utf-8")
    (tmp_path / "_notes.md").write_text("notes", encoding="utf-8")

    items = session_doc.load_scene_extractions(tmp_path)
    assert [s["name"] for s in items] == ["Farewell to Eldeth", "Shadows at Dusk"]
    assert "bullet 1" in items[0]["summary"]
    assert "Glabbagool" in items[0]["moments"]
    assert items[1]["summary"] == "summary text"
    assert items[1]["moments"] == "moments text"


def test_load_scene_extractions_skips_files_without_NN_prefix(tmp_path):
    (tmp_path / "session-doc.md").write_text("not a scene", encoding="utf-8")
    (tmp_path / "1_too_short.md").write_text("not NN_ pattern", encoding="utf-8")
    assert session_doc.load_scene_extractions(tmp_path) == []


# ── scene_extract.py --batch (blocking submit+poll+collect) ──────────────────

SINGLE_SCENE_SUMMARY = "## Scenes\n### Scene A\n#### A short scene.\n- bullet one\n"


def _write_vtt(path: Path) -> None:
    path.write_text(
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.000\nGM: hello there\n",
        encoding="utf-8",
    )


def _fake_batches_client(*, results_iter, batch_id="sb1"):
    """Same shape as tests/test_batch_api.py's _fake_client_with_batches,
    duplicated here so this file doesn't depend on that module."""
    client = MagicMock()
    client.messages.batches.create.return_value = SimpleNamespace(id=batch_id)
    client.messages.batches.retrieve.return_value = SimpleNamespace(
        id=batch_id, processing_status="ended",
        request_counts=SimpleNamespace(
            processing=0, succeeded=len(results_iter), errored=0, canceled=0, expired=0),
    )
    client.messages.batches.results.return_value = iter(results_iter)
    return client


def _succeeded_scene_entry(custom_id: str, text: str):
    msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                          stop_reason="end_turn", usage=None)
    return SimpleNamespace(custom_id=custom_id,
                           result=SimpleNamespace(type="succeeded", message=msg))


def _errored_scene_entry(custom_id: str, message: str):
    err = SimpleNamespace(error=SimpleNamespace(message=message))
    return SimpleNamespace(custom_id=custom_id,
                           result=SimpleNamespace(type="errored", error=err))


def test_batch_blocking_mode_submits_polls_collects_and_writes_files(monkeypatch, tmp_path):
    vtt = tmp_path / "session.vtt"
    _write_vtt(vtt)
    summary = tmp_path / "summary.md"
    summary.write_text(SINGLE_SCENE_SUMMARY, encoding="utf-8")
    out_dir = tmp_path / "out"

    entry = _succeeded_scene_entry("01_scene_a", "MOMENTS")
    fake_client = _fake_batches_client(results_iter=[entry])
    monkeypatch.setattr(se, "client_from_args", lambda args: fake_client)

    monkeypatch.setattr(sys, "argv", [
        "scene_extract.py", str(vtt),
        "--summary", str(summary),
        "--output-dir", str(out_dir),
        "--batch", "--poll-interval", "0", "--no-log",
    ])
    se.main()

    out_file = out_dir / "01_scene_a.md"
    assert out_file.exists()
    assert "MOMENTS" in out_file.read_text(encoding="utf-8")
    # The blocking path submits+polls+collects in one call — no detached
    # sidecar is left behind (unlike --submit-only, which does write one).
    assert not (out_dir / ".batch.json").exists()


def test_batch_blocking_mode_exits_nonzero_on_item_failure(monkeypatch, tmp_path):
    vtt = tmp_path / "session.vtt"
    _write_vtt(vtt)
    summary = tmp_path / "summary.md"
    summary.write_text(SINGLE_SCENE_SUMMARY, encoding="utf-8")
    out_dir = tmp_path / "out"

    entry = _errored_scene_entry("01_scene_a", "boom")
    fake_client = _fake_batches_client(results_iter=[entry])
    monkeypatch.setattr(se, "client_from_args", lambda args: fake_client)

    monkeypatch.setattr(sys, "argv", [
        "scene_extract.py", str(vtt),
        "--summary", str(summary),
        "--output-dir", str(out_dir),
        "--batch", "--poll-interval", "0", "--no-log",
    ])
    with pytest.raises(SystemExit) as exc_info:
        se.main()

    assert exc_info.value.code != 0
    assert not (out_dir / "01_scene_a.md").exists()


def test_batch_blocking_mode_skips_submission_when_all_scenes_exist(monkeypatch, tmp_path, capsys):
    vtt = tmp_path / "session.vtt"
    _write_vtt(vtt)
    summary = tmp_path / "summary.md"
    summary.write_text(SINGLE_SCENE_SUMMARY, encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "01_scene_a.md").write_text("ALREADY DONE", encoding="utf-8")

    fake_client = MagicMock()
    monkeypatch.setattr(se, "client_from_args", lambda args: fake_client)

    monkeypatch.setattr(sys, "argv", [
        "scene_extract.py", str(vtt),
        "--summary", str(summary),
        "--output-dir", str(out_dir),
        "--batch", "--no-log",
    ])
    se.main()

    fake_client.messages.batches.create.assert_not_called()
    assert (out_dir / "01_scene_a.md").read_text(encoding="utf-8") == "ALREADY DONE"


def test_submit_only_writes_sidecar_and_does_not_poll_or_write_files(monkeypatch, tmp_path):
    vtt = tmp_path / "session.vtt"
    _write_vtt(vtt)
    summary = tmp_path / "summary.md"
    summary.write_text(SINGLE_SCENE_SUMMARY, encoding="utf-8")
    out_dir = tmp_path / "out"

    fake_client = _fake_batches_client(results_iter=[], batch_id="sb-submit-only")
    monkeypatch.setattr(se, "client_from_args", lambda args: fake_client)

    monkeypatch.setattr(sys, "argv", [
        "scene_extract.py", str(vtt),
        "--summary", str(summary),
        "--output-dir", str(out_dir),
        "--batch", "--submit-only", "--no-log",
    ])
    se.main()

    sidecar = out_dir / ".batch.json"
    assert sidecar.exists()
    payload = campaignlib.read_batch_sidecar(sidecar)
    assert payload["batch_id"] == "sb-submit-only"
    assert payload["kind"] == "scene_extract"
    fake_client.messages.batches.retrieve.assert_not_called()
    assert not (out_dir / "01_scene_a.md").exists()


def test_collect_reads_sidecar_and_writes_files(monkeypatch, tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    sidecar = out_dir / ".batch.json"
    campaignlib.write_batch_sidecar(sidecar, {
        "kind": "scene_extract",
        "batch_id": "sb2",
        "model": "m",
        "submitted_at": campaignlib.utc_now_iso(),
        "scenes": [
            {"i": 1, "name": "Scene A", "slug": "scene_a",
             "custom_id": "01_scene_a", "path": str(out_dir / "01_scene_a.md")},
        ],
        "pending_custom_ids": ["01_scene_a"],
    })

    entry = _succeeded_scene_entry("01_scene_a", "MOMENTS FROM COLLECT")
    fake_client = _fake_batches_client(results_iter=[entry], batch_id="sb2")
    monkeypatch.setattr(se, "client_from_args", lambda args: fake_client)

    monkeypatch.setattr(sys, "argv", [
        "scene_extract.py",
        "--output-dir", str(out_dir),
        "--batch", "--collect", "--poll-interval", "0",
    ])
    se.main()

    out_file = out_dir / "01_scene_a.md"
    assert out_file.exists()
    assert "MOMENTS FROM COLLECT" in out_file.read_text(encoding="utf-8")
    assert not sidecar.exists()  # removed after a fully-successful collect


def test_collect_with_failed_scene_exits_nonzero_keeps_successes_and_sidecar(
    monkeypatch, tmp_path, capsys
):
    """T027/FR-008: a --collect with any failed scene exits non-zero; the
    succeeded scene's file is written and the sidecar stays for a retry."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    sidecar = out_dir / ".batch.json"
    campaignlib.write_batch_sidecar(sidecar, {
        "kind": "scene_extract",
        "batch_id": "sb3",
        "model": "m",
        "submitted_at": campaignlib.utc_now_iso(),
        "scenes": [
            {"i": 1, "name": "Scene A", "slug": "scene_a",
             "custom_id": "01_scene_a", "path": str(out_dir / "01_scene_a.md")},
            {"i": 2, "name": "Scene B", "slug": "scene_b",
             "custom_id": "02_scene_b", "path": str(out_dir / "02_scene_b.md")},
        ],
        "pending_custom_ids": ["01_scene_a", "02_scene_b"],
    })

    entries = [
        _succeeded_scene_entry("01_scene_a", "MOMENTS A"),
        _errored_scene_entry("02_scene_b", "overloaded"),
    ]
    fake_client = _fake_batches_client(results_iter=entries, batch_id="sb3")
    monkeypatch.setattr(se, "client_from_args", lambda args: fake_client)

    monkeypatch.setattr(sys, "argv", [
        "scene_extract.py",
        "--output-dir", str(out_dir),
        "--batch", "--collect", "--poll-interval", "0",
    ])
    with pytest.raises(SystemExit) as excinfo:
        se.main()

    assert excinfo.value.code == 1
    assert (out_dir / "01_scene_a.md").exists()
    assert not (out_dir / "02_scene_b.md").exists()
    assert sidecar.exists()  # kept for a retry --collect
    err = capsys.readouterr().err
    assert "FAILED 02_scene_b" in err


# ── group_scenes / project_scene_output ───────────────────────────────────────

def _plan_entry(i: int, body: str) -> dict:
    """A minimal stand-in for one `plan_scene_extraction` dict — group_scenes
    and project_scene_output only ever look at `body`, but the shape mirrors
    the real plan entry (013 data-model §1) so a reader can tell these are
    plan entries, not raw gm-assist scenes."""
    return {
        "i": i,
        "name": f"Scene {i}",
        "body": body,
        "slug": f"scene_{i}",
        "custom_id": f"{i:02d}_scene_{i}",
        "path": Path(f"/tmp/{i:02d}_scene_{i}.md"),
        "exists": False,
    }


def test_project_scene_output_uses_median_multiplier():
    entry = _plan_entry(1, "x" * 100)
    expected = 100 * campaignlib.scenes.OUTPUT_CHARS_PER_BODY_CHAR / campaignlib.scenes.CHARS_PER_TOKEN
    assert campaignlib.scenes.project_scene_output(entry) == expected


def test_project_scene_output_empty_body_is_zero():
    assert campaignlib.scenes.project_scene_output(_plan_entry(1, "")) == 0.0
    assert campaignlib.scenes.project_scene_output({"i": 1}) == 0.0


def test_group_scenes_single_group_when_total_fits_ceiling():
    """DM-7: total projection under the ceiling → exactly one group with
    every entry."""
    entries = [_plan_entry(i, "x" * 50) for i in range(1, 4)]
    groups = campaignlib.scenes.group_scenes(entries, ceiling_tokens=10_000)
    assert len(groups) == 1
    assert groups[0]["index"] == 1
    assert groups[0]["entries"] == entries
    assert groups[0]["projected_tokens"] == sum(
        campaignlib.scenes.project_scene_output(e) for e in entries
    )


def test_group_scenes_splits_when_total_exceeds_ceiling():
    """DM-8: over the ceiling, pack greedily in order; every group here fits
    (no single scene is individually oversized)."""
    entries = [_plan_entry(i, "x" * 100) for i in range(1, 5)]  # 105 tok each
    ceiling = 220  # fits two scenes (210) but not three (315)
    groups = campaignlib.scenes.group_scenes(entries, ceiling_tokens=ceiling)

    assert len(groups) > 1
    assert [g["entries"] for g in groups] == [entries[0:2], entries[2:4]]
    for g in groups:
        assert g["projected_tokens"] <= ceiling


def test_group_scenes_oversized_single_entry_forms_own_group():
    """DM-9: a scene whose own projection exceeds the ceiling is neither
    refused nor merged with a neighbour — it gets a group to itself."""
    small_before = _plan_entry(1, "x" * 10)
    big = _plan_entry(2, "x" * 1000)  # 1050 tokens, far over the ceiling
    small_after = _plan_entry(3, "x" * 10)
    entries = [small_before, big, small_after]
    ceiling = 50

    groups = campaignlib.scenes.group_scenes(entries, ceiling_tokens=ceiling)

    big_groups = [g for g in groups if g["entries"] == [big]]
    assert len(big_groups) == 1
    assert big_groups[0]["projected_tokens"] > ceiling
    # every other scene still made it into some group, none dropped
    all_entries = [e for g in groups for e in g["entries"]]
    assert all_entries == entries


def test_group_scenes_is_deterministic():
    """DM-10: same (entries, ceiling) in → same grouping out, every time."""
    entries = [_plan_entry(i, "x" * (20 * i)) for i in range(1, 6)]
    ceiling = 90

    first = campaignlib.scenes.group_scenes(entries, ceiling_tokens=ceiling)
    second = campaignlib.scenes.group_scenes(entries, ceiling_tokens=ceiling)

    assert first == second


def test_group_scenes_preserves_input_order():
    """DM-11: groups are contiguous slices of plan order — concatenating
    every group's entries reproduces the input list exactly."""
    entries = [_plan_entry(i, "x" * (30 * i)) for i in range(1, 6)]
    ceiling = 80

    groups = campaignlib.scenes.group_scenes(entries, ceiling_tokens=ceiling)

    reconstructed = [e for g in groups for e in g["entries"]]
    assert reconstructed == entries


def test_group_scenes_empty_input_returns_empty_list():
    assert campaignlib.scenes.group_scenes([], ceiling_tokens=1000) == []


# ── run_batched_scene_extraction (013-batched-scene-extraction, T031-T033) ────
#
# Shared fixtures/helpers below drive `run_batched_scene_extraction` for the
# call-count (T031), force/skip matrix (T032), and structural-identity (T033)
# assertions. Every scene in this section is named "Scene {n}" so one generic
# fake `stream_api` (`_echoing_batched_stream`) can build a well-formed
# response for whatever indices a group's own rendered prompt actually names
# — read back out with `_requested_indices` — without hand-maintaining
# per-test wire text.

_BATCHED_USER_TEMPLATE = campaignlib.load_agent_prompt("scene_extract_batched_user")


def _wrap_batched_scene(i: int, name: str, body: str) -> str:
    """One well-formed <<<CG-SCENE ...>>> marker pair — mirrors
    tests/test_batched_split.py's `_wrap` helper, duplicated here so this
    file doesn't depend on that module."""
    return (
        f"<<<CG-SCENE {i:02d} BEGIN: {name}>>>\n"
        f"{body}\n"
        f"<<<CG-SCENE {i:02d} END>>>"
    )


def _requested_indices(user_prompt: str) -> list[int]:
    """Parse the scene indices a rendered batched user prompt actually
    named, from its own '### NN — name' headings
    (`render_batched_user_prompt`'s own format). This reads what was SENT,
    never anything derived from internals."""
    return sorted(int(m) for m in re.findall(r"^### (\d+) — ", user_prompt, re.MULTILINE))


def _echoing_batched_stream(captured: list):
    """A `stream_api` fake that records each call's (system, user) into
    `captured` and replies with a well-formed batched response covering
    exactly the indices that call's own prompt requested — every scene in
    this section is named "Scene {i}", so the echoed name always matches
    and every section comes back `"complete"`."""
    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        captured.append({"system": system, "user": user})
        indices = _requested_indices(user)
        return "\n".join(
            _wrap_batched_scene(i, f"Scene {i}", f"MOMENTS for Scene {i}") for i in indices
        )
    return fake_stream


# ── T031: call count and prompt reuse (also covers SC-009) ─────────────────

def test_run_batched_scene_extraction_single_call_when_projection_fits_ceiling(tmp_path):
    """A batched run over N scenes whose total projection fits the ceiling
    makes exactly ONE stream_api call."""
    scenes = [{"name": f"Scene {n}", "body": f"- bullet {n}"} for n in (1, 2, 3)]
    extract_dir = tmp_path / "out"
    captured: list = []

    with patch.object(campaignlib.scenes, "stream_api", side_effect=_echoing_batched_stream(captured)):
        report = campaignlib.run_batched_scene_extraction(
            client=None,
            vtt_text="GM: hello\nThorin: hi",
            scenes=scenes,
            extract_dir=extract_dir,
            model="claude-haiku-4-5-20251001",
            user_template=_BATCHED_USER_TEMPLATE,
            max_tokens=5000,
        )

    assert len(captured) == 1
    assert report["groups_used"] == 1
    assert report["transcript_transmissions"] == 1
    assert _requested_indices(captured[0]["user"]) == [1, 2, 3]


def test_run_batched_scene_extraction_system_prompt_reused_byte_identical_across_groups(tmp_path):
    """On a fixture forced to split by a deliberately low max_tokens, the
    `system` argument is byte-identical across EVERY group call — the
    transcript is assembled once (T021) and reused, not rebuilt per group."""
    # Each body is 200 chars -> 200*4.2/4.0 = 210 projected tokens. A ceiling
    # of 250 fits exactly one scene per group (two would be 420), so three
    # scenes force a 3-group split.
    scenes = [{"name": f"Scene {n}", "body": "x" * 200} for n in (1, 2, 3)]
    extract_dir = tmp_path / "out"
    captured: list = []

    with patch.object(campaignlib.scenes, "stream_api", side_effect=_echoing_batched_stream(captured)):
        report = campaignlib.run_batched_scene_extraction(
            client=None,
            vtt_text="GM: hello\nThorin: hi",
            scenes=scenes,
            extract_dir=extract_dir,
            model="m",
            user_template=_BATCHED_USER_TEMPLATE,
            max_tokens=250,
        )

    assert report["groups_used"] > 1  # sanity: fixture actually forced a split
    assert len(captured) == report["groups_used"]
    systems = [c["system"] for c in captured]
    assert len(set(systems)) == 1  # every call sent the exact same system string


def test_run_batched_scene_extraction_call_count_scales_with_ceiling_sc009(tmp_path):
    """SC-009: automated coverage that raising the ceiling collapses the run
    to a single call, on a FIXED fixture — not a manual walkthrough. Same
    scenes, two ceilings: a high one that fits everything (1 call) and a low
    one that forces a split (>1 calls)."""
    scenes = [{"name": f"Scene {n}", "body": "x" * 200} for n in (1, 2, 3, 4)]

    def run_with_ceiling(ceiling: float, subdir: str) -> int:
        extract_dir = tmp_path / subdir
        captured: list = []
        with patch.object(campaignlib.scenes, "stream_api",
                          side_effect=_echoing_batched_stream(captured)):
            campaignlib.run_batched_scene_extraction(
                client=None, vtt_text="VTT", scenes=scenes,
                extract_dir=extract_dir, model="m",
                user_template=_BATCHED_USER_TEMPLATE, max_tokens=ceiling,
            )
        return len(captured)

    high_ceiling_calls = run_with_ceiling(5000, "high")  # 4*210=840 tok, fits easily
    low_ceiling_calls = run_with_ceiling(250, "low")     # forces a split (per math above)

    assert high_ceiling_calls == 1
    assert low_ceiling_calls > 1


# ── T032: the force / skip-if-exists matrix (SC-005a-d) ────────────────────
#
# Highest-value tests in the phase: a wrong implementation writes correct
# files while sending everything it was given, so every test here asserts on
# what was SENT (parsed from the recorded prompt's own indices), not only on
# what ended up on disk.

def test_run_batched_scene_extraction_force_false_requests_only_missing_scenes(tmp_path):
    """SC-005a: with K of N scene files already on disk and force=False, the
    request contains exactly the N-K missing scenes and no others. The K
    existing files are byte-unchanged afterwards."""
    scenes = [{"name": f"Scene {n}", "body": f"- bullet {n}"} for n in range(1, 6)]  # N=5
    extract_dir = tmp_path / "out"
    extract_dir.mkdir()
    present = {2, 4}  # K=2
    existing_text = {i: f"PRE-EXISTING scene {i} content — must not change" for i in present}
    for i, text in existing_text.items():
        (extract_dir / f"{i:02d}_scene_{i}.md").write_text(text, encoding="utf-8")

    captured: list = []
    with patch.object(campaignlib.scenes, "stream_api", side_effect=_echoing_batched_stream(captured)):
        report = campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=5000,
        )

    assert len(captured) == 1  # fits in one group at this ceiling
    assert _requested_indices(captured[0]["user"]) == [1, 3, 5]  # N-K missing, no others
    assert report["scenes_requested"] == 3
    assert report["scenes_skipped"] == 2

    for i, text in existing_text.items():
        assert (extract_dir / f"{i:02d}_scene_{i}.md").read_text(encoding="utf-8") == text


def test_run_batched_scene_extraction_force_false_all_present_makes_zero_calls(tmp_path):
    """SC-005b: with ALL N on disk and force=False, ZERO stream_api calls
    are made, and the returned report says scenes_requested == 0 and
    transcript_transmissions == 0."""
    scenes = [{"name": f"Scene {n}", "body": f"- bullet {n}"} for n in (1, 2, 3)]
    extract_dir = tmp_path / "out"
    extract_dir.mkdir()
    for n in (1, 2, 3):
        (extract_dir / f"{n:02d}_scene_{n}.md").write_text(f"DONE {n}", encoding="utf-8")

    def fake_stream(*args, **kwargs):
        raise AssertionError("stream_api must not be called when nothing is missing")

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        report = campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE,
        )

    assert report["scenes_requested"] == 0
    assert report["transcript_transmissions"] == 0


def test_run_batched_scene_extraction_force_true_requests_all_and_snapshots_changed_only(tmp_path):
    """SC-005c: with force=True, all N are requested regardless of what's on
    disk, and `.prev` snapshots exist only for the files whose content
    actually changed. Sibling case (FR-014, snapshot_scene_for_rerun's own
    contract): when the new content is byte-identical to the old, NO `.prev`
    is written and the file is not rewritten."""
    scenes = [{"name": f"Scene {n}", "body": f"- bullet {n}"} for n in (1, 2)]
    extract_dir = tmp_path / "out"
    extract_dir.mkdir()

    # Scene 1: existing content differs from what the fake model returns.
    (extract_dir / "01_scene_1.md").write_text("OLD scene 1 content", encoding="utf-8")

    # Scene 2: existing content is byte-identical to what format_scene_output
    # will produce for the fake model's response — the sibling case.
    identical_text = campaignlib.format_scene_output(
        "Scene 2", "- bullet 2", "MOMENTS for Scene 2",
    )
    scene2_path = extract_dir / "02_scene_2.md"
    scene2_path.write_text(identical_text, encoding="utf-8")
    mtime_before = scene2_path.stat().st_mtime_ns

    captured: list = []
    with patch.object(campaignlib.scenes, "stream_api", side_effect=_echoing_batched_stream(captured)):
        report = campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=5000,
            force=True,
        )

    assert _requested_indices(captured[0]["user"]) == [1, 2]  # both requested, present or not
    assert report["scenes_requested"] == 2

    # Scene 1's content changed -> snapshotted, file rewritten.
    assert (extract_dir / "01_scene_1.md.prev").read_text(encoding="utf-8") == "OLD scene 1 content"
    assert "MOMENTS for Scene 1" in (extract_dir / "01_scene_1.md").read_text(encoding="utf-8")

    # Scene 2's content is identical -> no .prev, file not rewritten.
    assert not (extract_dir / "02_scene_2.md.prev").exists()
    assert scene2_path.read_text(encoding="utf-8") == identical_text
    assert scene2_path.stat().st_mtime_ns == mtime_before


def test_scene_extraction_converges_on_same_files_regardless_of_mode_order(tmp_path):
    """SC-005d: a session extracted half by run_scene_extraction and
    finished by run_batched_scene_extraction (and the reverse) ends with the
    same N files — both modes read the same on-disk evidence of what is
    done."""
    scenes = [{"name": f"Scene {n}", "body": f"- bullet {n}"} for n in (1, 2, 3, 4)]
    expected_files = ["01_scene_1.md", "02_scene_2.md", "03_scene_3.md", "04_scene_4.md"]

    # ── per-scene first, batched finishes ──
    per_scene_dir = tmp_path / "per_scene_then_batched"

    def fake_stream_per_scene(client, system, user, model, max_tokens=8096, silent=False,
                              verbose=False, cache_system=False):
        return "PER-SCENE MOMENTS"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream_per_scene):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes[:2],
            extract_dir=per_scene_dir, model="m",
            extraction_instruction="{name} {body}",
        )
    assert sorted(p.name for p in per_scene_dir.glob("*.md")) == expected_files[:2]

    captured: list = []
    with patch.object(campaignlib.scenes, "stream_api", side_effect=_echoing_batched_stream(captured)):
        campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=per_scene_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=5000,
        )
    assert _requested_indices(captured[0]["user"]) == [3, 4]
    assert sorted(p.name for p in per_scene_dir.glob("*.md")) == expected_files

    # ── reverse: batched first, per-scene finishes ──
    batched_dir = tmp_path / "batched_then_per_scene"
    captured2: list = []
    with patch.object(campaignlib.scenes, "stream_api", side_effect=_echoing_batched_stream(captured2)):
        campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes[:2],
            extract_dir=batched_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=5000,
        )
    assert sorted(p.name for p in batched_dir.glob("*.md")) == expected_files[:2]

    calls: list = []

    def fake_stream_per_scene2(client, system, user, model, max_tokens=8096, silent=False,
                               verbose=False, cache_system=False):
        calls.append(user)
        return "PER-SCENE MOMENTS"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream_per_scene2):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=batched_dir, model="m",
            extraction_instruction="{name} {body}",
        )
    assert len(calls) == 2  # only scenes 3-4 got a per-scene call
    assert sorted(p.name for p in batched_dir.glob("*.md")) == expected_files


# ── T033: structural identity and no cross-contamination ───────────────────

def test_batched_and_per_scene_paths_write_byte_identical_files(tmp_path):
    """SC-006: for the same scene name/bullets/model-output, a file written
    by the batched path is byte-identical to one written by the per-scene
    path. Both go through format_scene_output — assert the actual bytes so
    a future bespoke writer would break this."""
    scene = {"name": "Scene 1", "body": "- bullet 1"}
    model_output = "MOMENTS for Scene 1"

    per_scene_dir = tmp_path / "per_scene"

    def fake_stream_single(client, system, user, model, max_tokens=8096, silent=False,
                           verbose=False, cache_system=False):
        return model_output

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream_single):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=[scene],
            extract_dir=per_scene_dir, model="m",
            extraction_instruction="{name} {body}",
        )

    batched_dir = tmp_path / "batched"

    def fake_stream_batched(client, system, user, model, max_tokens=8096, silent=False,
                            verbose=False, cache_system=False):
        return _wrap_batched_scene(1, "Scene 1", model_output)

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream_batched):
        campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=[scene],
            extract_dir=batched_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE,
        )

    per_scene_bytes = (per_scene_dir / "01_scene_1.md").read_bytes()
    batched_bytes = (batched_dir / "01_scene_1.md").read_bytes()
    assert batched_bytes == per_scene_bytes


def test_batched_no_cross_contamination_between_scene_files(tmp_path):
    """SC-007: no scene's content is written under another scene's path.
    Each scene gets a distinctive marker, checked against every OTHER
    scene's file too, not just its own."""
    scenes = [{"name": f"Scene {n}", "body": f"- bullet {n}"} for n in (1, 2, 3)]
    extract_dir = tmp_path / "out"
    markers = {
        1: "ALPHA-ONLY moments, marker AAA111",
        2: "BETA-ONLY moments, marker BBB222",
        3: "GAMMA-ONLY moments, marker CCC333",
    }

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        indices = _requested_indices(user)
        return "\n".join(_wrap_batched_scene(i, f"Scene {i}", markers[i]) for i in indices)

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE,
        )

    contents = {
        i: (extract_dir / f"{i:02d}_scene_{i}.md").read_text(encoding="utf-8")
        for i in (1, 2, 3)
    }
    for i, marker in markers.items():
        assert marker in contents[i]
        for j, other_marker in markers.items():
            if j != i:
                assert other_marker not in contents[i]


def test_batched_scene_summary_holds_bullets_and_verbatim_moments_holds_model_output(tmp_path):
    """`format_scene_output(name, body, result)` takes bullets as `body` and
    model text as `result` — assert run_batched_scene_extraction passes them
    in that order and never swapped, which would silently write the
    gm-assist bullets as the extraction."""
    scene = {"name": "Scene 1", "body": "- these are the gm-assist BULLETS"}
    model_output = "these are the MODEL-EXTRACTED verbatim moments"
    extract_dir = tmp_path / "out"

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        return _wrap_batched_scene(1, "Scene 1", model_output)

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=[scene],
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE,
        )

    text = (extract_dir / "01_scene_1.md").read_text(encoding="utf-8")
    summary_idx = text.index("## Scene summary")
    bullets_idx = text.index("gm-assist BULLETS")
    moments_idx = text.index("## Verbatim moments")
    model_idx = text.index("MODEL-EXTRACTED")

    assert summary_idx < bullets_idx < moments_idx < model_idx


# ── T041/T042 (013-batched-scene-extraction Phase 4, US2) ──────────────────
#
# T041: the partial-response path (SC-005) — some scenes complete, some
# not, and a re-run without --force requests ONLY what's still missing.
# T042: reconciliation failure (DM-14) — a group that can't be trusted
# writes nothing from itself, and a failure in one group must not discard
# another group's successes.
#
# Reuses this file's existing batched helpers: _BATCHED_USER_TEMPLATE,
# _wrap_batched_scene, _requested_indices (all defined above, T031-T033).

def _eight_scene_gmassist_summary() -> str:
    """8 scenes named "Scene 1".."Scene 8", matching the naming convention
    _echoing_batched_stream and friends already rely on."""
    parts = ["## Scenes"]
    for n in range(1, 9):
        parts.append(f"### Scene {n}")
        parts.append(f"#### Scene {n} description.")
        parts.append(f"- bullet {n}")
    return "\n".join(parts) + "\n"


def _two_big_scene_gmassist_summary() -> str:
    """2 scenes with large bodies, for CLI-level tests that need a real
    --batch-max-tokens split into exactly two groups (one scene each) —
    mirrors the sizing already proven by
    test_run_batched_scene_extraction_system_prompt_reused_byte_identical_across_groups,
    scaled up with margin so the '#### description' line's extra chars
    can't accidentally change how many groups the projection produces."""
    parts = ["## Scenes"]
    for n in (1, 2):
        parts.append(f"### Scene {n}")
        parts.append(f"#### Scene {n} description.")
        parts.append(f"- {'x' * 400}")
    return "\n".join(parts) + "\n"


def _fake_stream_partial_5_1_2(client, system, user, model, max_tokens=8096,
                               silent=False, verbose=False, cache_system=False):
    """SC-005 shape: scenes 1-5 complete, scene 6 incomplete (BEGIN, no
    END), scenes 7-8 absent (no BEGIN at all)."""
    indices = _requested_indices(user)
    parts = []
    for i in indices:
        if i <= 5:
            parts.append(_wrap_batched_scene(i, f"Scene {i}", f"MOMENTS for Scene {i}"))
        elif i == 6:
            parts.append(f"<<<CG-SCENE {i:02d} BEGIN: Scene {i}>>>\ncut off, no closing marker")
        # 7, 8: absent — emit nothing.
    return "\n".join(parts)


# ── T041a: engine-level partial response (SC-005, points 1-2) ──────────────

def test_run_batched_scene_extraction_partial_response_writes_5_names_3_missing(tmp_path):
    """5 complete + 1 incomplete + 2 absent: exactly 5 files land, none for
    the other 3, and the report says so."""
    scenes = [{"name": f"Scene {n}", "body": f"- bullet {n}"} for n in range(1, 9)]
    extract_dir = tmp_path / "out"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=_fake_stream_partial_5_1_2):
        report = campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=32000,
        )

    written_files = sorted(p.name for p in extract_dir.glob("*.md"))
    assert written_files == [f"{n:02d}_scene_{n}.md" for n in range(1, 6)]
    for n in (6, 7, 8):
        assert not (extract_dir / f"{n:02d}_scene_{n}.md").exists()

    assert report["scenes_written"] == 5
    assert set(report["scenes_missing"]) == {"Scene 6", "Scene 7", "Scene 8"}


# ── T041b: the re-run IS the point — requests only the 3 missing ───────────

def test_run_batched_scene_extraction_rerun_requests_only_the_missing_scenes(tmp_path):
    """After a partial run leaves 5 files on disk, a second call without
    --force must request EXACTLY the 3 missing scenes — not all 8 and
    discard 5, which would look identical on disk but burn the transcript
    for scenes that were never actually re-needed."""
    scenes = [{"name": f"Scene {n}", "body": f"- bullet {n}"} for n in range(1, 9)]
    extract_dir = tmp_path / "out"

    with patch.object(campaignlib.scenes, "stream_api", side_effect=_fake_stream_partial_5_1_2):
        campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=32000,
        )

    captured: list = []
    with patch.object(campaignlib.scenes, "stream_api", side_effect=_echoing_batched_stream(captured)):
        report2 = campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=32000,
        )

    assert report2["scenes_requested"] == 3
    assert report2["scenes_skipped"] == 5
    assert len(captured) == 1  # 3 small scenes fit one group
    assert _requested_indices(captured[0]["user"]) == [6, 7, 8]

    written_files = sorted(p.name for p in extract_dir.glob("*.md"))
    assert written_files == [f"{n:02d}_scene_{n}.md" for n in range(1, 9)]


# ── T041c: the CLI layer — exit 3, then a second CLI run resumes correctly ─

def test_scene_extract_cli_batch_scenes_partial_then_rerun_sc005(monkeypatch, tmp_path, capsys):
    """The exit code and the resumability are the CLI's own contract, not
    the engine's — this drives session_doc/scene_extract.py's main()
    directly, twice, over the same --output-dir."""
    vtt = tmp_path / "session.vtt"
    _write_vtt(vtt)
    summary = tmp_path / "summary.md"
    summary.write_text(_eight_scene_gmassist_summary(), encoding="utf-8")
    out_dir = tmp_path / "out"

    fake_client = MagicMock()
    monkeypatch.setattr(se, "client_from_args", lambda args: fake_client)

    # ── First run: partial response ──
    with patch.object(campaignlib.scenes, "stream_api", side_effect=_fake_stream_partial_5_1_2):
        monkeypatch.setattr(sys, "argv", [
            "scene_extract.py", str(vtt),
            "--summary", str(summary),
            "--output-dir", str(out_dir),
            "--batch-scenes", "--no-log",
        ])
        with pytest.raises(SystemExit) as exc_info:
            se.main()

    assert exc_info.value.code == 3

    written_files = sorted(p.name for p in out_dir.glob("*.md"))
    assert written_files == [f"{n:02d}_scene_{n}.md" for n in range(1, 6)]
    for n in (6, 7, 8):
        assert not (out_dir / f"{n:02d}_scene_{n}.md").exists()

    err = capsys.readouterr().err
    assert "NOT extracted" in err
    assert "Scene 6" in err and "Scene 7" in err and "Scene 8" in err
    assert "Re-run without --force" in err

    # ── Second run: no --force. Must request ONLY the 3 missing scenes. ──
    captured: list = []
    with patch.object(campaignlib.scenes, "stream_api", side_effect=_echoing_batched_stream(captured)):
        monkeypatch.setattr(sys, "argv", [
            "scene_extract.py", str(vtt),
            "--summary", str(summary),
            "--output-dir", str(out_dir),
            "--batch-scenes", "--no-log",
        ])
        se.main()  # all 3 now come back complete -> no exit raised (exit 0 path)

    assert len(captured) == 1
    assert _requested_indices(captured[0]["user"]) == [6, 7, 8]

    written_files = sorted(p.name for p in out_dir.glob("*.md"))
    assert written_files == [f"{n:02d}_scene_{n}.md" for n in range(1, 9)]


# ── T042a: a single failing group writes nothing from itself ───────────────

def test_run_batched_scene_extraction_group_failure_writes_nothing(tmp_path):
    """DM-14: a group that can't be reconciled (here: a NAME_MISMATCH on
    one of its scenes) fails as a WHOLE — nothing from ANY scene in that
    group is written, even the ones whose own section looked fine."""
    scenes = [{"name": f"Scene {n}", "body": f"- bullet {n}"} for n in (1, 2, 3)]
    extract_dir = tmp_path / "out"

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        # Scenes 1 and 3 echoed correctly; scene 2's name is wrong ->
        # NAME_MISMATCH fails the whole group (DM-14).
        return "\n".join([
            _wrap_batched_scene(1, "Scene 1", "MOMENTS for Scene 1"),
            _wrap_batched_scene(2, "Not The Right Name", "MOMENTS for Scene 2"),
            _wrap_batched_scene(3, "Scene 3", "MOMENTS for Scene 3"),
        ])

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        report = campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=32000,
        )

    assert list(extract_dir.glob("*.md")) == []
    assert report["scenes_written"] == 0
    assert len(report["group_failures"]) == 1
    assert report["group_failures"][0]["reason"] == campaignlib.scenes.BATCHED_NAME_MISMATCH
    assert set(report["scenes_missing"]) == {"Scene 1", "Scene 2", "Scene 3"}


# ── T042b: a failing group does not discard another group's successes ─────

def test_run_batched_scene_extraction_group_failure_does_not_discard_other_groups(tmp_path):
    """Two scenes, forced into two separate groups by a low ceiling (same
    sizing as test_run_batched_scene_extraction_system_prompt_reused_byte_identical_across_groups:
    a 200-char body projects to 210 tokens, and a 250-token ceiling packs
    one scene per group). Group 1 (scene 1) succeeds; group 2 (scene 2)
    fails reconciliation. Scene 1's file must exist and be correct
    regardless of what happened to group 2."""
    scenes = [{"name": "Scene 1", "body": "x" * 200}, {"name": "Scene 2", "body": "x" * 200}]
    extract_dir = tmp_path / "out"

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        indices = _requested_indices(user)
        if indices == [1]:
            return _wrap_batched_scene(1, "Scene 1", "MOMENTS for Scene 1")
        if indices == [2]:
            return _wrap_batched_scene(2, "Wrong Echoed Name", "MOMENTS for Scene 2")
        raise AssertionError(f"unexpected request indices {indices}")

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        report = campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=250,
        )

    assert report["groups_used"] == 2  # sanity: the fixture actually forced a split
    assert len(report["group_failures"]) == 1

    assert (extract_dir / "01_scene_1.md").exists()
    assert "MOMENTS for Scene 1" in (extract_dir / "01_scene_1.md").read_text(encoding="utf-8")
    assert not (extract_dir / "02_scene_2.md").exists()

    assert report["scenes_written"] == 1
    assert "Scene 2" in report["scenes_missing"]


# ── T042c: the CLI layer — exit 4, group 1's file survives group 2's failure ─

def test_scene_extract_cli_batch_scenes_group_failure_exits_4(monkeypatch, tmp_path):
    vtt = tmp_path / "session.vtt"
    _write_vtt(vtt)
    summary = tmp_path / "summary.md"
    summary.write_text(_two_big_scene_gmassist_summary(), encoding="utf-8")
    out_dir = tmp_path / "out"

    fake_client = MagicMock()
    monkeypatch.setattr(se, "client_from_args", lambda args: fake_client)

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        indices = _requested_indices(user)
        if indices == [1]:
            return _wrap_batched_scene(1, "Scene 1", "MOMENTS for Scene 1")
        if indices == [2]:
            return _wrap_batched_scene(2, "Wrong Echoed Name", "MOMENTS for Scene 2")
        raise AssertionError(f"unexpected request indices {indices}")

    with patch.object(campaignlib.scenes, "stream_api", side_effect=fake_stream):
        monkeypatch.setattr(sys, "argv", [
            "scene_extract.py", str(vtt),
            "--summary", str(summary),
            "--output-dir", str(out_dir),
            "--batch-scenes", "--batch-max-tokens", "500", "--no-log",
        ])
        with pytest.raises(SystemExit) as exc_info:
            se.main()

    assert exc_info.value.code == 4
    assert (out_dir / "01_scene_1.md").exists()
    assert "MOMENTS for Scene 1" in (out_dir / "01_scene_1.md").read_text(encoding="utf-8")
    assert not (out_dir / "02_scene_2.md").exists()


# ── T053 (013 Phase 6, US4): the RunReport's counts ─────────────────────────
#
# data-model.md §6 lists the required fields: scenes_total / scenes_skipped /
# scenes_requested / scenes_written, scenes_empty, scenes_missing,
# groups_used, transcript_transmissions, ceiling_exceeded — plus
# projected_tokens_total (T050, new in this phase). The two tests below drive
# a fixture with a KNOWN mix of skipped/written/empty/missing scenes and
# assert every one of those fields, then assert ceiling_exceeded and
# projected_tokens_total specifically across both states (fits in one group;
# forced split by a small --batch-max-tokens).

def _fake_stream_mixed_outcomes(client, system, user, model, max_tokens=8096,
                                silent=False, verbose=False, cache_system=False):
    """T053 fixture stream fake: whichever of scenes 1,3,5,6,7,8 the group's
    own prompt actually requested, reply with scenes 1/3/5 complete, 6 empty
    (BEGIN/END present, blank body), 7 incomplete (BEGIN, no matching END),
    and 8 absent (no BEGIN at all) — scenes 2 and 4 are never requested
    because the test pre-seeds them on disk (skip-if-exists)."""
    indices = _requested_indices(user)
    parts = []
    for i in indices:
        if i in (1, 3, 5):
            parts.append(_wrap_batched_scene(i, f"Scene {i}", f"MOMENTS for Scene {i}"))
        elif i == 6:
            parts.append(f"<<<CG-SCENE {i:02d} BEGIN: Scene {i}>>>\n   \n<<<CG-SCENE {i:02d} END>>>")
        elif i == 7:
            parts.append(f"<<<CG-SCENE {i:02d} BEGIN: Scene {i}>>>\ncut off, no closing marker")
        elif i == 8:
            pass  # absent -- emit nothing for it.
        else:
            raise AssertionError(f"unexpected requested index {i}")
    return "\n".join(parts)


def test_run_batched_scene_extraction_report_counts_full_fixture(tmp_path):
    """Every RunReport field against a fixture with a KNOWN mix: 8 scenes
    total, 2 already on disk (skipped), so 6 requested — of those, 3 land
    complete (written), 1 comes back empty, 2 are missing (one incomplete,
    one absent) — all within a single group (ceiling not exceeded)."""
    scenes = [{"name": f"Scene {n}", "body": f"- bullet {n}"} for n in range(1, 9)]
    extract_dir = tmp_path / "out"
    extract_dir.mkdir()
    for n in (2, 4):  # pre-seed as already-extracted -> skip-if-exists
        (extract_dir / f"{n:02d}_scene_{n}.md").write_text(f"DONE {n}", encoding="utf-8")

    with patch.object(campaignlib.scenes, "stream_api", side_effect=_fake_stream_mixed_outcomes):
        report = campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=extract_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=5000,
        )

    # Independently derived expectation, from the engine's own pure
    # projection function — not a hand-computed constant that could drift
    # from OUTPUT_CHARS_PER_BODY_CHAR silently.
    expected_total = sum(
        campaignlib.scenes.project_scene_output({"body": f"- bullet {n}"})
        for n in (1, 3, 5, 6, 7, 8)
    )

    assert report["scenes_total"] == 8
    assert report["scenes_skipped"] == 2
    assert report["scenes_requested"] == 6
    assert report["projected_tokens_total"] == pytest.approx(expected_total)
    assert report["scenes_written"] == 3
    assert report["scenes_empty"] == ["Scene 6"]
    assert report["scenes_missing"] == ["Scene 7", "Scene 8"]
    assert report["groups_used"] == 1
    assert report["transcript_transmissions"] == 1
    assert report["ceiling_exceeded"] is False
    assert report["group_failures"] == []
    assert len(report["saved"]) == 3

    written = sorted(p.name for p in extract_dir.glob("*.md"))
    # 2, 4 pre-seeded + 1, 3, 5 newly written; 6 (empty) / 7, 8 (missing)
    # never touch disk.
    assert written == [
        "01_scene_1.md", "02_scene_2.md", "03_scene_3.md",
        "04_scene_4.md", "05_scene_5.md",
    ]


def test_run_batched_scene_extraction_report_ceiling_exceeded_both_states(tmp_path):
    """FR-006d: `ceiling_exceeded` and `projected_tokens_total` across BOTH
    states on the identical scene set — a high ceiling that fits everything
    in one group (`ceiling_exceeded=False`), and a low one that forces a
    real split (`ceiling_exceeded=True`, `groups_used>1`). Same sizing as
    `test_run_batched_scene_extraction_call_count_scales_with_ceiling_sc009`.
    `projected_tokens_total` must come out IDENTICAL in both runs: it is the
    sum over the entries' own projections, independent of how many groups
    `group_scenes` happens to pack them into."""
    scenes = [{"name": f"Scene {n}", "body": "x" * 200} for n in (1, 2, 3, 4)]

    def run_with_ceiling(ceiling: float, subdir: str) -> dict:
        extract_dir = tmp_path / subdir
        with patch.object(campaignlib.scenes, "stream_api",
                          side_effect=_echoing_batched_stream([])):
            return campaignlib.run_batched_scene_extraction(
                client=None, vtt_text="VTT", scenes=scenes,
                extract_dir=extract_dir, model="m",
                user_template=_BATCHED_USER_TEMPLATE, max_tokens=ceiling,
            )

    report_fits = run_with_ceiling(5000, "fits")   # 4*210=840 tok, fits easily
    report_split = run_with_ceiling(250, "split")  # forces a split (per math above)

    expected_total = sum(
        campaignlib.scenes.project_scene_output({"body": "x" * 200}) for _ in range(4)
    )

    assert report_fits["ceiling_exceeded"] is False
    assert report_fits["groups_used"] == 1
    assert report_fits["projected_tokens_total"] == pytest.approx(expected_total)

    assert report_split["ceiling_exceeded"] is True
    assert report_split["groups_used"] > 1
    assert report_split["projected_tokens_total"] == pytest.approx(expected_total)


def test_scene_extract_cli_prints_projected_output_line_with_ceiling_note(monkeypatch, tmp_path, capsys):
    """T051/T052 at the CLI layer: `main()` prints 'Projected output: N tok
    -> M groups', and appends the FR-006d note naming the lever
    (--batch-max-tokens) only because this run's projection forced a split.
    Same 2-scene/500-token sizing as
    test_scene_extract_cli_batch_scenes_group_failure_exits_4 (a real forced
    split, not a contrived flag)."""
    vtt = tmp_path / "session.vtt"
    _write_vtt(vtt)
    summary = tmp_path / "summary.md"
    summary.write_text(_two_big_scene_gmassist_summary(), encoding="utf-8")
    out_dir = tmp_path / "out"

    fake_client = MagicMock()
    monkeypatch.setattr(se, "client_from_args", lambda args: fake_client)

    with patch.object(campaignlib.scenes, "stream_api",
                      side_effect=_echoing_batched_stream([])):
        monkeypatch.setattr(sys, "argv", [
            "scene_extract.py", str(vtt),
            "--summary", str(summary),
            "--output-dir", str(out_dir),
            "--batch-scenes", "--batch-max-tokens", "500", "--no-log",
        ])
        se.main()

    out = capsys.readouterr().out
    assert "Projected output:" in out
    assert "-> 2 groups" in out
    assert "projection exceeds ceiling; raise --batch-max-tokens for one call" in out


# ── T048: batched prompt must not drift from the per-scene prompt (FR-016) ────
#
# `config/agents/scene_extract.md` (per-scene) and
# `config/agents/scene_extract_batched.md` (batched) are two independent
# files; nothing enforces that an edit to one propagates to the other. This
# guards the load-bearing verbatim ground rules specifically — not the whole
# prompt, which legitimately differs (multi-scene scoping language, the
# sentinel/marker protocol, anti-rationing guidance) — so a genuine batching-
# specific change never trips this test.
#
# Each rule's expected text is extracted from the CURRENT per-scene prompt at
# test time (never hardcoded here), then checked as a verbatim substring of
# the batched prompt. A rewording of a rule in scene_extract.md is compared
# against ITS OWN new wording, so a cosmetic copy-edit doesn't make this test
# stale — but if the rule is tightened (or loosened) in scene_extract.md
# without the same edit landing in scene_extract_batched.md, the extracted
# text won't be found there and the parametrised id names exactly which rule
# went missing.

PER_SCENE_PROMPT_PATH = REPO_ROOT / "config" / "agents" / "scene_extract.md"
BATCHED_PROMPT_PATH = REPO_ROOT / "config" / "agents" / "scene_extract_batched.md"

#: (rule_id, anchor) — `anchor` is the distinctive leading phrase of one
#: "- " bullet in scene_extract.md's GROUND RULES / "THE TRANSCRIPT OWNS ITS
#: OWN MISTAKES" sections. Deliberately excludes the "use the summary as
#: scope" bullet, which the batched prompt legitimately rewords for the
#: multi-scene case ("that scene's ... not whichever scene you are currently
#: writing") rather than copying verbatim.
VERBATIM_GROUND_RULES = [
    ("no_paraphrase_verbatim_quoting",
     "Quote dialogue VERBATIM. Do not paraphrase."),
    ("no_invention",
     "Do NOT invent anything."),
    ("capture_full_texture",
     "The summary is the structural spec but may still miss detail."),
    ("preserve_transcript_garbles",
     'If the tape says "the strength of the pandemic"'),
    ("preserve_misheard_names",
     'The same holds for names. If the tape says "Vucherdin"'),
    ("no_editorial_insertion_in_quotes",
     'Never put an editorial insertion inside a `> "…"` span.'),
    ("marker_must_not_carry_a_guess",
     "A bare (truncated) / (paraphrase) / [inaudible] marker is fine"),
    ("no_joining_utterances",
     "Never join two utterances into one quote."),
    ("no_folding_narration_into_quote",
     "Never fold your own narration into a quote."),
]


def _extract_bullet(source_text: str, anchor: str, rule_id: str) -> str:
    """Return the full "- "-bulleted rule in `source_text` that starts with
    `anchor`, including its indented continuation lines, exactly as
    currently written — never a value frozen into this test."""
    anchor_pos = source_text.find(anchor)
    assert anchor_pos != -1, (
        f"could not locate rule '{rule_id}' (anchor {anchor!r}) in "
        f"{PER_SCENE_PROMPT_PATH} — has the per-scene prompt been reworded "
        "past recognition? Update this test's anchor for this rule."
    )
    bullet_start = source_text.rfind("\n- ", 0, anchor_pos + 1)
    assert bullet_start != -1, (
        f"anchor for rule '{rule_id}' is not inside a '- ' bullet in "
        f"{PER_SCENE_PROMPT_PATH}"
    )
    bullet_start += 1  # skip the leading newline, keep the "- "

    lines = source_text[bullet_start:].splitlines(keepends=True)
    bullet_lines = [lines[0]]
    for line in lines[1:]:
        # A bullet's continuation is indented two spaces; a blank line or the
        # next "- " bullet ends it.
        if line.startswith("  ") and not line.startswith("- "):
            bullet_lines.append(line)
        else:
            break
    return "".join(bullet_lines).rstrip("\n")


@pytest.mark.parametrize("rule_id,anchor", VERBATIM_GROUND_RULES, ids=[r[0] for r in VERBATIM_GROUND_RULES])
def test_batched_prompt_preserves_verbatim_ground_rules(rule_id, anchor):
    """FR-016: every load-bearing verbatim rule in the per-scene prompt must
    still be present, word for word, in the batched prompt. A failing
    parametrisation id names exactly which rule went missing."""
    per_scene_text = PER_SCENE_PROMPT_PATH.read_text(encoding="utf-8")
    batched_text = BATCHED_PROMPT_PATH.read_text(encoding="utf-8")

    rule_text = _extract_bullet(per_scene_text, anchor, rule_id)

    assert rule_text in batched_text, (
        f"load-bearing verbatim rule '{rule_id}' from "
        f"{PER_SCENE_PROMPT_PATH.name} is missing (or was weakened) in "
        f"{BATCHED_PROMPT_PATH.name}:\n\n{rule_text}\n\n"
        "The batched prompt must carry every verbatim ground rule the "
        "per-scene prompt has, or batched output quietly degrades while the "
        "per-scene path improves (FR-016)."
    )


# ── T049: no alias-map-derived normalizer reaches the batched path (FR-015) ───
#
# An alias is an identity assertion, never a text transform (PR #231; see
# tests/test_no_prefix_identity.py for the sibling guard over voice/example
# routing). This is a STATIC check over the actual call site in
# session_doc/scene_extract.py, in the same spirit as
# tests/test_retrieve_render_isolation.py's AST walk: it does not run the
# CLI, it inspects the source for the shape of the call that would let the
# defect back in.
#
# Deliberately NOT a byte-identity check against the VTT file on disk:
# `normalize_vtt_speakers` (scene_extract.py:427-ish, FR-015a) is a
# deterministic, declared player→character speaker-label rewrite and
# legitimately runs before the batched call — asserting byte-identity would
# fail on correct code. What's actually asserted is narrower and more
# precise: the `input_normalizer` argument passed to
# `run_batched_scene_extraction`, if any, must not be sourced from
# `build_alias_normalizer` — directly, or via a variable assigned from it
# (including the `x, _ = build_alias_normalizer(...)` unpacking form used at
# every other `build_alias_normalizer` call site in this repo) — and the
# `system_suffix` argument it DOES pass must be traceably sourced from
# `format_npc_roster`, the declared "aliases as roster knowledge" path.

SCENE_EXTRACT_CLI_PATH = REPO_ROOT / "session_doc" / "scene_extract.py"


def _calls_to(tree: ast.AST, name: str) -> list[ast.Call]:
    """Every ast.Call in `tree` whose function resolves to bare name or
    attribute `name` (e.g. matches both `run_batched_scene_extraction(...)`
    and `module.run_batched_scene_extraction(...)`)."""
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Name) and f.id == name) or (
                isinstance(f, ast.Attribute) and f.attr == name
            ):
                calls.append(node)
    return calls


def _contains_call_to(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Name) and n.func.id == name)
            or (isinstance(n.func, ast.Attribute) and n.func.attr == name)
        )
        for n in ast.walk(node)
    )


def _enclosing_function(tree: ast.AST, target: ast.AST) -> ast.AST:
    """The innermost def containing `target`, or `tree` itself if none does."""
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(n is target for n in ast.walk(node)):
                if best is None or (node.end_lineno - node.lineno) < (best.end_lineno - best.lineno):
                    best = node
    return best if best is not None else tree


def _value_derives_from(value_node: ast.AST, scope: ast.AST, call_name: str) -> bool:
    """True if `value_node` (an argument expression) contains a call to
    `call_name` directly, or is a bare Name assigned — anywhere in `scope`,
    single-target or tuple-unpacked — from an expression that contains a
    call to `call_name`."""
    if _contains_call_to(value_node, call_name):
        return True
    if not isinstance(value_node, ast.Name):
        return False
    target_name = value_node.id
    for node in ast.walk(scope):
        if not isinstance(node, ast.Assign):
            continue
        if not _contains_call_to(node.value, call_name):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == target_name:
                return True
            if isinstance(t, ast.Tuple) and any(
                isinstance(elt, ast.Name) and elt.id == target_name for elt in t.elts
            ):
                return True
    return False


def _the_batched_call() -> tuple[ast.Call, ast.AST]:
    source = SCENE_EXTRACT_CLI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SCENE_EXTRACT_CLI_PATH))
    calls = _calls_to(tree, "run_batched_scene_extraction")
    assert calls, (
        f"no call to run_batched_scene_extraction found in "
        f"{SCENE_EXTRACT_CLI_PATH} — has the batched entry point moved? "
        "Update this test's target."
    )
    assert len(calls) == 1, (
        f"expected exactly one call to run_batched_scene_extraction in "
        f"{SCENE_EXTRACT_CLI_PATH}, found {len(calls)} — update this test "
        "if a second call site is now intentional."
    )
    call = calls[0]
    return call, _enclosing_function(tree, call)


def test_batched_call_carries_no_alias_derived_normalizer():
    """FR-015 / PR #231: `input_normalizer`, if passed at all to the batched
    engine call, must not be sourced from `build_alias_normalizer` — an
    alias map applied as a rewrite over the transcript is exactly the defect
    PR #231 fixed once in scene_extract, and it must not come back on the
    batched path specifically."""
    call, scope = _the_batched_call()
    kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}

    if "input_normalizer" not in kwargs:
        return  # not passed at all -> defaults to None -> nothing to check

    offending = _value_derives_from(kwargs["input_normalizer"], scope, "build_alias_normalizer")
    assert not offending, (
        "run_batched_scene_extraction's input_normalizer is sourced from "
        "build_alias_normalizer — an alias map has become a text transform "
        "applied to the transcript. Aliases may reach the model only as "
        "roster knowledge via format_npc_roster, passed as system_suffix — "
        "never as a rewrite. This is the exact defect PR #231 fixed in "
        "scene_extract once; see docs/config/players-isolation.md and "
        "tests/test_no_prefix_identity.py for the sibling guard."
    )


def test_batched_call_passes_aliases_only_as_roster_knowledge():
    """The positive half of FR-015: if the batched call passes
    `system_suffix` at all, it must be traceably built from
    `format_npc_roster` — aliases arrive as roster knowledge, not as some
    other unvetted transform."""
    call, scope = _the_batched_call()
    kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}

    assert "system_suffix" in kwargs, (
        "run_batched_scene_extraction call no longer passes system_suffix — "
        "if aliases still need to reach the model, they must arrive as "
        "roster knowledge via format_npc_roster(), passed as system_suffix."
    )
    is_roster = _value_derives_from(kwargs["system_suffix"], scope, "format_npc_roster")
    assert is_roster, (
        "system_suffix passed to run_batched_scene_extraction is not "
        "traceably built from format_npc_roster() — aliases must reach the "
        "model as roster knowledge specifically, not some other transform."
    )


# ── FR-006 / DM-4: an empty scene is never written, in EITHER mode ──────────
#
# DM-4 says `exists` is the sole skip criterion and is the same one both
# modes use, "so a session started in one mode and finished in the other
# converges on the same set". The per-scene loop used to write a file for an
# empty response, which retired that scene permanently on the strength of one
# empty reply — and made the two modes disagree.

def _scene_dicts(*names):
    return [{"name": n, "body": f"- bullet for {n}"} for n in names]


def _per_scene_stream(empty_for):
    def _fake(client, system, user, model, **kwargs):
        return "" if empty_for in user else '> "a line that was spoken"'
    return _fake


def test_per_scene_empty_response_writes_no_file(tmp_path):
    scenes = _scene_dicts("Loud Scene", "Quiet Scene")
    with patch.object(campaignlib.scenes, "stream_api",
                      side_effect=_per_scene_stream("Quiet Scene")):
        saved = campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes, extract_dir=tmp_path,
            model="m", extraction_instruction="{name}\n{body}",
        )
    assert sorted(p.name for p in tmp_path.glob("*.md")) == ["01_loud_scene.md"]
    assert [p.name for p in saved] == ["01_loud_scene.md"]


def test_per_scene_empty_response_is_requested_again_next_run(tmp_path):
    """Not writing it is only useful if the next run actually asks again."""
    scenes = _scene_dicts("Loud Scene", "Quiet Scene")
    with patch.object(campaignlib.scenes, "stream_api",
                      side_effect=_per_scene_stream("Quiet Scene")):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes, extract_dir=tmp_path,
            model="m", extraction_instruction="{name}\n{body}",
        )

    asked: list[str] = []

    def _second(client, system, user, model, **kwargs):
        asked.append(user)
        return '> "found something this time"'

    with patch.object(campaignlib.scenes, "stream_api", side_effect=_second):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes, extract_dir=tmp_path,
            model="m", extraction_instruction="{name}\n{body}",
        )
    assert len(asked) == 1 and "Quiet Scene" in asked[0], \
        "the already-extracted scene must stay skipped, the empty one re-asked"
    assert sorted(p.name for p in tmp_path.glob("*.md")) == [
        "01_loud_scene.md", "02_quiet_scene.md"]


def test_per_scene_empty_response_under_force_keeps_the_prior_file(tmp_path):
    """--force must not trade a good extraction for an empty response."""
    scenes = _scene_dicts("Only Scene")
    with patch.object(campaignlib.scenes, "stream_api",
                      side_effect=_per_scene_stream("nothing matches")):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes, extract_dir=tmp_path,
            model="m", extraction_instruction="{name}\n{body}",
        )
    out_file = tmp_path / "01_only_scene.md"
    before = out_file.read_text(encoding="utf-8")

    with patch.object(campaignlib.scenes, "stream_api",
                      side_effect=lambda *a, **k: "   \n"):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes, extract_dir=tmp_path,
            model="m", extraction_instruction="{name}\n{body}", force=True,
        )
    assert out_file.read_text(encoding="utf-8") == before


def test_both_modes_agree_about_an_empty_scene(tmp_path):
    """DM-4 convergence, asserted directly: same scenes, same empty reply,
    same set of files on disk whichever mode produced them."""
    scenes = _scene_dicts("Scene 1", "Scene 2")

    per_scene_dir = tmp_path / "per_scene"
    with patch.object(campaignlib.scenes, "stream_api",
                      side_effect=_per_scene_stream("Scene 2")):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=per_scene_dir, model="m",
            extraction_instruction="{name}\n{body}",
        )

    batched_dir = tmp_path / "batched"

    def _batched(client, system, user, model, **kwargs):
        return ("<<<CG-SCENE 01 BEGIN: Scene 1>>>\n"
                '> "a line that was spoken"\n'
                "<<<CG-SCENE 01 END>>>\n"
                "<<<CG-SCENE 02 BEGIN: Scene 2>>>\n"
                "\n"
                "<<<CG-SCENE 02 END>>>\n")

    with patch.object(campaignlib.scenes, "stream_api", side_effect=_batched):
        report = campaignlib.run_batched_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=batched_dir, model="m",
            user_template=_BATCHED_USER_TEMPLATE, max_tokens=32000,
        )

    assert report["scenes_empty"] == ["Scene 2"]
    assert (sorted(p.name for p in per_scene_dir.glob("*.md"))
            == sorted(p.name for p in batched_dir.glob("*.md"))
            == ["01_scene_1.md"])


# ── A batched run leaves a log, exactly as the per-scene run does ───────────
#
# The batched branch returned before the shared `save_log` block, so the one
# path whose grouping, transmission count and group failures are worth
# recording was the one path that recorded nothing — and --no-log was inert.

def _batched_cli_argv(vtt, summary, out_dir, *extra):
    return ["scene_extract.py", str(vtt), "--summary", str(summary),
            "--output-dir", str(out_dir), "--batch-scenes", *extra]


def test_batched_run_writes_a_log(monkeypatch, tmp_path):
    vtt = tmp_path / "session.vtt"
    _write_vtt(vtt)
    summary = tmp_path / "summary.md"
    summary.write_text(_eight_scene_gmassist_summary(), encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(se, "client_from_args", lambda args: MagicMock())

    with patch.object(campaignlib.scenes, "stream_api",
                      side_effect=_echoing_batched_stream([])):
        monkeypatch.setattr(sys, "argv", _batched_cli_argv(vtt, summary, out_dir))
        se.main()

    logs = list((out_dir / "logs").glob("*.md"))
    assert len(logs) == 1, "a batched run must leave a log, like the per-scene run"
    text = logs[0].read_text(encoding="utf-8")
    assert "Batching" in text
    assert "transcript transmissions" in text


def test_batched_run_honours_no_log(monkeypatch, tmp_path):
    vtt = tmp_path / "session.vtt"
    _write_vtt(vtt)
    summary = tmp_path / "summary.md"
    summary.write_text(_eight_scene_gmassist_summary(), encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(se, "client_from_args", lambda args: MagicMock())

    with patch.object(campaignlib.scenes, "stream_api",
                      side_effect=_echoing_batched_stream([])):
        monkeypatch.setattr(sys, "argv",
                            _batched_cli_argv(vtt, summary, out_dir, "--no-log"))
        se.main()

    assert not (out_dir / "logs").exists()


def test_a_partial_batched_run_still_writes_its_log(monkeypatch, tmp_path):
    """Exit 3 must not jump over the log — a partial run is exactly when the
    record of what was requested and what landed is worth having."""
    vtt = tmp_path / "session.vtt"
    _write_vtt(vtt)
    summary = tmp_path / "summary.md"
    summary.write_text(_eight_scene_gmassist_summary(), encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(se, "client_from_args", lambda args: MagicMock())

    with patch.object(campaignlib.scenes, "stream_api",
                      side_effect=_fake_stream_partial_5_1_2):
        monkeypatch.setattr(sys, "argv", _batched_cli_argv(vtt, summary, out_dir))
        with pytest.raises(SystemExit) as exc_info:
            se.main()

    assert exc_info.value.code == 3
    logs = list((out_dir / "logs").glob("*.md"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert "Scene 6" in text and "Scene 7" in text and "Scene 8" in text
