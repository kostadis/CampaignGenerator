"""The per-scene render record, and who writes which half — #454 (US4).

`session_doc_scene_NN_<slug>.knobs.json` says what produced a scene. Before
this feature only `server/routers/scene_editor.py` wrote it, so a render
launched from a terminal recorded nothing — the engine's own state living in
the face (Principle VI).

Ownership is now split, and the split is the risky part of the feature
(research D8):

- `sd_narrate` writes **render identity** — model, backend, the modes, and each
  document's content digest. It built the prompt, so it is what knows.
- the server merges **run outcome** — status and counts, computed after the
  subprocess exits, which the CLI cannot know.

Two writers of one file is the shape of a Split-Brain. It is admitted only
because the writes are strictly sequential and because two files per render
would guarantee the disagreement rather than risk it. These tests are what hold
that line: the merge must not erase identity, and a pre-feature sidecar must
still read.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.routers.scene_editor import _write_knobs_sidecar  # noqa: E402
from session_doc.narrate import GM_ATTRIBUTION_GAP  # noqa: E402
from session_doc.sd_narrate import _digest, _write_render_record  # noqa: E402


def _args(**over):
    base = dict(prose_mode=False, gap_marking=False, reflections=False,
                narrate_tokens=16000, narration_genre_file="voice/_genre.md")
    base.update(over)
    return SimpleNamespace(**base)


def _record(path: Path) -> dict:
    sidecar = path.with_name(path.stem + ".knobs.json")
    return json.loads(sidecar.read_text(encoding="utf-8"))


# ── The CLI half ────────────────────────────────────────────────────────────

def test_a_cli_render_records_the_mode_and_the_contract_digest(tmp_path):
    """SC-007 for a terminal render — the case that recorded nothing before."""
    narration = tmp_path / "session_doc_scene_01_arrival.md"
    narration.write_text("prose", encoding="utf-8")
    _write_render_record(narration, args=_args(gap_marking=True),
                         genre_text="Noir.", model="claude-fable-5-1",
                         backend="anthropic")
    rec = _record(narration)
    assert rec["gap_marking"] is True
    assert rec["gap_contract"].endswith("gm_attribution_gap.md")
    assert rec["gap_contract_sha256"] == _digest(GM_ATTRIBUTION_GAP)
    assert rec["model"] == "claude-fable-5-1"


def test_the_contract_is_named_by_digest_not_copied(tmp_path):
    """#276's ruling generalised: a run records a document's *identity*.

    The genre paste that motivated it was 16,303 characters; duplicating a
    document into every sidecar is what made two copies drift with nothing
    noticing.
    """
    narration = tmp_path / "session_doc_scene_01_arrival.md"
    narration.write_text("prose", encoding="utf-8")
    _write_render_record(narration, args=_args(gap_marking=True),
                         genre_text="Noir.", model="m", backend="anthropic")
    raw = (narration.with_name(narration.stem + ".knobs.json")
           .read_text(encoding="utf-8"))
    assert "Where the source attributes a passage to the GM" not in raw
    assert _digest(GM_ATTRIBUTION_GAP) in raw


def test_a_mid_session_edit_to_a_document_is_visible(tmp_path):
    """#418 promises two scenes can be compared and an edit noticed. Shown on
    the genre file, whose text this test controls."""
    a = tmp_path / "session_doc_scene_01_a.md"
    b = tmp_path / "session_doc_scene_02_b.md"
    for p in (a, b):
        p.write_text("prose", encoding="utf-8")
    _write_render_record(a, args=_args(), genre_text="Noir.", model="m", backend="x")
    _write_render_record(b, args=_args(), genre_text="Noir, revised.",
                         model="m", backend="x")
    assert _record(a)["narration_genre_sha256"] != _record(b)["narration_genre_sha256"]


def test_no_document_means_no_digest_rather_than_a_digest_of_nothing(tmp_path):
    """`sha256("")` is a real hash and would read as "a document was used"."""
    narration = tmp_path / "session_doc_scene_01_arrival.md"
    narration.write_text("prose", encoding="utf-8")
    _write_render_record(narration, args=_args(), genre_text=None,
                         model="m", backend="x")
    rec = _record(narration)
    assert rec["narration_genre_sha256"] is None
    assert "gap_contract_sha256" not in rec  # mode off: no contract was used


def test_gap_off_records_the_mode_as_off_rather_than_omitting_it(tmp_path):
    """An absent key reads as "an old sidecar"; `false` reads as "asked for and
    not used". The Review screen shows a chip for one and nothing for the
    other, so they must not be the same thing on disk."""
    narration = tmp_path / "session_doc_scene_01_arrival.md"
    narration.write_text("prose", encoding="utf-8")
    _write_render_record(narration, args=_args(), genre_text=None,
                         model="m", backend="x")
    assert _record(narration)["gap_marking"] is False


# ── The split ───────────────────────────────────────────────────────────────

def test_the_server_merges_outcome_without_erasing_identity(tmp_path):
    """The load-bearing assertion of research D8.

    A replace would leave the sidecar describing a run whose prompt it can no
    longer name — the record would survive and stop meaning anything, which is
    worse than not having one.
    """
    narration = tmp_path / "session_doc_scene_01_arrival.md"
    narration.write_text("prose", encoding="utf-8")
    _write_render_record(narration, args=_args(gap_marking=True),
                         genre_text="Noir.", model="claude-fable-5-1",
                         backend="anthropic")

    _write_knobs_sidecar(narration, {"status": "success", "exchange_count": 1,
                                     "written_count": 1})
    rec = _record(narration)
    assert rec["status"] == "success"          # outcome merged in
    assert rec["gap_marking"] is True          # identity survived
    assert rec["gap_contract_sha256"] == _digest(GM_ATTRIBUTION_GAP)
    assert rec["model"] == "claude-fable-5-1"


def test_the_server_still_writes_a_record_when_the_cli_left_none(tmp_path):
    """An older `sd_narrate`, or a render that failed before writing one. The
    outcome is still worth keeping, and the merge must not require a file it
    may not find."""
    narration = tmp_path / "session_doc_scene_01_arrival.md"
    narration.write_text("prose", encoding="utf-8")
    _write_knobs_sidecar(narration, {"status": "audit_failure"})
    assert _record(narration)["status"] == "audit_failure"


def test_a_pre_feature_sidecar_still_reads(tmp_path):
    """T030 — the Review screen's `applied_knobs` must tolerate a record
    written before this feature, which carries none of the new keys."""
    from server.routers.scene_editor import _read_knobs_sidecar

    narration = tmp_path / "session_doc_scene_01_arrival.md"
    narration.write_text("prose", encoding="utf-8")
    sidecar = narration.with_name(narration.stem + ".knobs.json")
    sidecar.write_text(json.dumps({
        "narrate_tokens": 16000, "prose_mode": False,
        "reflections": False, "backend": "anthropic",
    }) + "\n", encoding="utf-8")

    knobs = _read_knobs_sidecar(narration)
    assert knobs is not None
    assert knobs.get("gap_marking") is None      # absent, not a crash
    assert knobs["backend"] == "anthropic"


def test_an_unwritable_location_does_not_fail_the_render(tmp_path):
    """The narration is the artifact. A render that succeeded must not be
    reported as failed because its provenance file could not be written."""
    missing = tmp_path / "no-such-dir" / "session_doc_scene_01_arrival.md"
    _write_render_record(missing, args=_args(), genre_text=None,
                         model="m", backend="x")   # must not raise
    _write_knobs_sidecar(missing, {"status": "success"})  # must not raise
