"""Tests for party.py's CLI — focused on the --extract-only checkpoint and the
per-group labeling that the shared pipeline needs to support (character sheet
vs session extract vs backstory vs arc score vs context)."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import campaignlib  # noqa: E402
from pipelines.grounding import party  # noqa: E402

# party.py has moved into pipelines/grounding/ and now runs as the `party`
# console script (pyproject.toml's [project.scripts]). Resolve it next to the
# current interpreter (same venv bin/) rather than relying on $PATH, so this
# test doesn't depend on the venv being "activated" in the process running
# pytest — same rationale as server.subprocess_runner.console_script().
PARTY_BIN = str(Path(sys.executable).parent / "party")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PARTY_BIN, *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def test_help_advertises_extract_only():
    result = _run("--help")
    assert result.returncode == 0
    assert "--extract-only" in result.stdout


def test_extract_only_and_synthesize_only_are_mutually_exclusive(tmp_path):
    result = _run(
        "--extract-only", "--synthesize-only",
        "--extract-dir", str(tmp_path),
        "--output", str(tmp_path / "out.md"),
    )
    assert result.returncode == 1
    assert "mutually exclusive" in result.stderr


def test_extract_only_requires_summaries(tmp_path):
    result = _run(
        "--extract-only",
        "--character", str(tmp_path / "soma.md"),
        "--output", str(tmp_path / "out.md"),
    )
    assert result.returncode == 1
    assert "--extract-only requires --summaries" in result.stderr


class FakeStreamAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model})
        return f"[stub-{len(self.calls)}]"


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(campaignlib.pipelines, "stream_api", fake)
    # party.py imports stream_api directly (for the --party-config path);
    # also stub that binding so the direct call is captured.
    monkeypatch.setattr(party, "stream_api", fake)
    monkeypatch.setattr(party, "make_client", lambda: None)
    return fake


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_extract_only_skips_synthesis(monkeypatch, fake_stream_api, tmp_path):
    summaries = _write(tmp_path / "summaries.md", "a session")
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    output = tmp_path / "party.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--summaries", str(summaries),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--extract-only",
    ])
    party.main()

    assert len(fake_stream_api.calls) == 1
    assert not output.exists()
    assert any(extract_dir.glob("extract_*.md"))


def test_default_run_uses_per_group_source_labels(monkeypatch, fake_stream_api, tmp_path):
    summaries = _write(tmp_path / "summaries.md", "session content")
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    backstory = _write(tmp_path / "soma_backstory.md", "backstory prose")
    arc_score = _write(tmp_path / "soma_arc.md", "arc score mechanic")
    context = _write(tmp_path / "campaign_state.md", "grounding context")
    output = tmp_path / "party.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--summaries", str(summaries),
        "--backstory", str(backstory),
        "--arc-scores", str(arc_score),
        "--context", str(context),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
    ])
    party.main()

    synthesize_prompt = fake_stream_api.calls[1]["user"]
    # Each source group carries its own source-comment label.
    assert "<!-- Character sheet: soma.md -->" in synthesize_prompt
    assert "<!-- Session extract: extract_001.md -->" in synthesize_prompt
    assert "<!-- Backstory: soma_backstory.md -->" in synthesize_prompt
    assert "<!-- Arc score mechanic: soma_arc.md -->" in synthesize_prompt
    assert "<!-- Context: campaign_state.md -->" in synthesize_prompt
    # Group headings present.
    assert "# CHARACTER SHEETS" in synthesize_prompt
    assert "# SESSION EXTRACTIONS" in synthesize_prompt
    assert "# BACKSTORY DOCUMENTS" in synthesize_prompt
    assert "# ARC SCORE MECHANICS" in synthesize_prompt
    assert "# ADDITIONAL CONTEXT" in synthesize_prompt
    assert output.exists()


def test_characters_only_skips_extract_pass(monkeypatch, fake_stream_api, tmp_path):
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    output = tmp_path / "party.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--output", str(output),
    ])
    party.main()

    # No summaries → no extract pass; one API call for synthesis only.
    assert len(fake_stream_api.calls) == 1
    synthesize_prompt = fake_stream_api.calls[0]["user"]
    assert "# CHARACTER SHEETS" in synthesize_prompt
    assert "# SESSION EXTRACTIONS" not in synthesize_prompt


# ── Party config ─────────────────────────────────────────────────────────────


def _write_party_config(tmp_path, body: str):
    cfg = tmp_path / "party.yaml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_load_party_config_parses_sheet_backstory_arc(tmp_path):
    _write(tmp_path / "brew.md", "Brewbarry sheet")
    _write(tmp_path / "brew_back.md", "Brewbarry backstory")
    _write(tmp_path / "brew_score.md", "Brewbarry score")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Brewbarry
    sheet: brew.md
    backstory: brew_back.md
    arc_score: brew_score.md
""")
    config = party.load_party_config(cfg, campaign_root=tmp_path)
    assert len(config.characters) == 1
    pc = config.characters[0]
    assert pc.name == "Brewbarry"
    assert pc.sheet.name == "brew.md"
    assert pc.backstory.name == "brew_back.md"
    assert pc.arc_score.name == "brew_score.md"
    assert pc.trackless is False


def test_load_party_config_parses_dossier(tmp_path):
    _write(tmp_path / "zephyr.md", "Zephyr sheet")
    _write(tmp_path / "npc_zephyr.md", "Zephyr ensemble dossier")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Zephyr
    sheet: zephyr.md
    dossier: npc_zephyr.md
""")
    config = party.load_party_config(cfg, campaign_root=tmp_path)
    pc = config.characters[0]
    assert pc.dossier.name == "npc_zephyr.md"


def test_load_party_config_dossier_absent_is_none(tmp_path):
    _write(tmp_path / "omit.md", "Omit sheet")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Omit
    sheet: omit.md
""")
    config = party.load_party_config(cfg, campaign_root=tmp_path)
    assert config.characters[0].dossier is None


def test_load_party_config_trackless_vs_absent(tmp_path):
    _write(tmp_path / "vuk.md", "Vukradin sheet")
    _write(tmp_path / "omit.md", "Omit sheet")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Vukradin
    sheet: vuk.md
    arc_score: null
  - name: Omit
    sheet: omit.md
""")
    config = party.load_party_config(cfg, campaign_root=tmp_path)
    vuk, omit = config.characters
    assert vuk.arc_score is None and vuk.trackless is True
    assert omit.arc_score is None and omit.trackless is False


def test_load_party_config_missing_file_fails_loud(tmp_path):
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Ghost
    sheet: does_not_exist.md
""")
    with pytest.raises(SystemExit):
        party.load_party_config(cfg, campaign_root=tmp_path)


def test_load_party_config_empty_characters_fails(tmp_path):
    cfg = _write_party_config(tmp_path, "characters: []\n")
    with pytest.raises(SystemExit):
        party.load_party_config(cfg, campaign_root=tmp_path)


def test_party_config_is_mutex_with_flat_flags(tmp_path):
    _write(tmp_path / "any.md", "x")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Any
    sheet: any.md
""")
    result = _run(
        "--party-config", str(cfg),
        "--character", str(tmp_path / "any.md"),
        "--output", str(tmp_path / "out.md"),
    )
    assert result.returncode == 1
    assert "mutually exclusive" in result.stderr


def test_party_config_renders_per_character_block(monkeypatch, fake_stream_api, tmp_path):
    # Paths inside party/planning.yaml resolve against the campaign root,
    # which for a CLI run is the CWD (docs/config/grounding-isolation.md
    # Track A'). Run from the workspace the way a GM actually does.
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "brew.md", "Brewbarry sheet content")
    _write(tmp_path / "brew_back.md", "Brewbarry backstory content")
    _write(tmp_path / "brew_score.md", "Brewbarry arc score content")
    _write(tmp_path / "vuk.md", "Vukradin sheet content")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Brewbarry
    sheet: brew.md
    backstory: brew_back.md
    arc_score: brew_score.md
  - name: Vukradin
    sheet: vuk.md
    arc_score: null
""")
    output = tmp_path / "party.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--party-config", str(cfg),
        "--output", str(output),
    ])
    party.main()

    assert len(fake_stream_api.calls) == 1
    prompt = fake_stream_api.calls[0]["user"]
    # PARTY group with per-character subsections
    assert "# PARTY" in prompt
    assert "## Brewbarry" in prompt
    assert "## Vukradin" in prompt
    # Brewbarry has all three file blocks
    assert "<!-- Character sheet: brew.md -->" in prompt
    assert "<!-- Backstory: brew_back.md -->" in prompt
    assert "<!-- Arc score mechanic: brew_score.md -->" in prompt
    # Vukradin has only the sheet + the trackless marker (no arc file)
    assert "<!-- Character sheet: vuk.md -->" in prompt
    assert "INTENTIONALLY TRACKLESS" in prompt
    # Flat group headers should NOT appear — party-config path uses # PARTY
    assert "# CHARACTER SHEETS" not in prompt
    assert "# ARC SCORE MECHANICS" not in prompt
    assert output.exists()


def test_party_config_renders_dossier_block(monkeypatch, fake_stream_api, tmp_path):
    # Paths inside party/planning.yaml resolve against the campaign root,
    # which for a CLI run is the CWD (docs/config/grounding-isolation.md
    # Track A'). Run from the workspace the way a GM actually does.
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "zephyr.md", "Zephyr sheet content")
    _write(tmp_path / "npc_zephyr.md", "Zephyr ensemble dossier content")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Zephyr
    sheet: zephyr.md
    dossier: npc_zephyr.md
""")
    output = tmp_path / "party.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--party-config", str(cfg),
        "--output", str(output),
    ])
    party.main()

    prompt = fake_stream_api.calls[0]["user"]
    assert "<!-- Ensemble dossier: npc_zephyr.md -->" in prompt
    assert "Zephyr ensemble dossier content" in prompt


def test_party_config_no_dossier_omits_block(monkeypatch, fake_stream_api, tmp_path):
    # Paths inside party/planning.yaml resolve against the campaign root,
    # which for a CLI run is the CWD (docs/config/grounding-isolation.md
    # Track A'). Run from the workspace the way a GM actually does.
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "soma.md", "Tortle Druid")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Soma
    sheet: soma.md
""")

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--party-config", str(cfg),
        "--output", str(tmp_path / "party.md"),
    ])
    party.main()

    prompt = fake_stream_api.calls[0]["user"]
    assert "<!-- Ensemble dossier:" not in prompt


def test_party_config_trackless_character_gets_no_arc_file_block(monkeypatch, fake_stream_api, tmp_path):
    # Paths inside party/planning.yaml resolve against the campaign root,
    # which for a CLI run is the CWD (docs/config/grounding-isolation.md
    # Track A'). Run from the workspace the way a GM actually does.
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "vuk.md", "Vukradin sheet")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Vukradin
    sheet: vuk.md
    arc_score: null
""")

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--party-config", str(cfg),
        "--output", str(tmp_path / "party.md"),
    ])
    party.main()

    prompt = fake_stream_api.calls[0]["user"]
    # No "Arc score mechanic" source comment, but the trackless marker is there.
    assert "<!-- Arc score mechanic:" not in prompt
    assert "<!-- Arc score: INTENTIONALLY TRACKLESS -->" in prompt


def test_existing_output_is_preserved_and_candidate_is_written(monkeypatch, fake_stream_api, tmp_path, capsys):
    # Hand-edited party.md must survive a re-run; the regenerated draft
    # should land in a sibling .candidate.md instead.
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    output = _write(tmp_path / "party.md", "HAND EDITED PARTY DOC — keep me")
    candidate = tmp_path / "party.candidate.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--output", str(output),
    ])
    party.main()

    assert output.read_text(encoding="utf-8") == "HAND EDITED PARTY DOC — keep me"
    assert candidate.exists()
    assert "[stub-" in candidate.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "Candidate party document saved to" in out
    assert "diff -u" in out


def test_overwrite_flag_replaces_existing_output(monkeypatch, fake_stream_api, tmp_path):
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    output = _write(tmp_path / "party.md", "OLD CONTENT")
    candidate = tmp_path / "party.candidate.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--output", str(output),
        "--overwrite",
    ])
    party.main()

    assert "[stub-" in output.read_text(encoding="utf-8")
    assert not candidate.exists()


def test_bootstrap_writes_directly_when_output_missing(monkeypatch, fake_stream_api, tmp_path):
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    output = tmp_path / "party.md"
    candidate = tmp_path / "party.candidate.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--output", str(output),
    ])
    party.main()

    assert output.exists()
    assert "[stub-" in output.read_text(encoding="utf-8")
    assert not candidate.exists()


# ── Citation grounding ───────────────────────────────────────────────────────
# Extract-phase `[cite: "..."]` tags get numbered before reaching synthesis
# (CitationIdAssigner), and whatever the model cites back gets verified and
# rendered into a `## Sources` section on the text that actually gets
# written to disk — whichever path (--output or the candidate sibling) that
# turns out to be.


class CitingStreamAPI:
    """Like FakeStreamAPI, but the synthesis response cites citation ID 1 —
    lets tests exercise the whole grounding chain (extract-file
    `[cite: "..."]` tag -> numbered `[cite:1 "..."]` shown to the model ->
    model's `[1]` reference -> `## Sources` rendered with the real quote),
    not just that the wiring is a silent no-op against an uncited stub."""

    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model})
        return "- Test claim drawn from the session. [1]\n"


@pytest.fixture
def citing_stream_api(monkeypatch):
    fake = CitingStreamAPI()
    monkeypatch.setattr(campaignlib.pipelines, "stream_api", fake)
    monkeypatch.setattr(party, "stream_api", fake)
    monkeypatch.setattr(party, "make_client", lambda: None)
    return fake


def _write_tagged_extract(extract_dir: Path, quote: str) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)
    return _write(
        extract_dir / "extract_001.md",
        f'- Test claim drawn from the session. [cite: "{quote}"]\n',
    )


def test_synthesis_numbers_extract_citation_tags(monkeypatch, citing_stream_api, tmp_path):
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    extract_dir = tmp_path / "extractions"
    _write_tagged_extract(extract_dir, "Soma made a pact with the fey lord")
    output = tmp_path / "party.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--synthesize-only",
        "--extract-dir", str(extract_dir),
        "--output", str(output),
    ])
    party.main()

    synthesize_prompt = citing_stream_api.calls[0]["user"]
    # The extract pass's un-numbered [cite: "..."] tag is assigned a stable
    # numeric ID before the synthesis prompt reaches the model.
    assert '[cite:1 "Soma made a pact with the fey lord"]' in synthesize_prompt


def test_final_document_gets_sources_section(monkeypatch, citing_stream_api, tmp_path):
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    extract_dir = tmp_path / "extractions"
    _write_tagged_extract(extract_dir, "Soma made a pact with the fey lord")
    output = tmp_path / "party.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--synthesize-only",
        "--extract-dir", str(extract_dir),
        "--output", str(output),
    ])
    party.main()

    written = output.read_text(encoding="utf-8")
    assert "## Sources" in written
    assert '[1] "Soma made a pact with the fey lord"' in written


def test_candidate_file_receives_sources_augmented_text(monkeypatch, citing_stream_api, tmp_path):
    # The candidate-file write path (--output already exists) must receive
    # the post-check_synthesis_citations text — Sources appended — not the
    # raw party_doc the model returned before the citation check ran.
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    extract_dir = tmp_path / "extractions"
    _write_tagged_extract(extract_dir, "Soma made a pact with the fey lord")
    output = _write(tmp_path / "party.md", "HAND EDITED PARTY DOC — keep me")
    candidate = tmp_path / "party.candidate.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--synthesize-only",
        "--extract-dir", str(extract_dir),
        "--output", str(output),
    ])
    party.main()

    assert output.read_text(encoding="utf-8") == "HAND EDITED PARTY DOC — keep me"
    assert candidate.exists()
    candidate_text = candidate.read_text(encoding="utf-8")
    assert "## Sources" in candidate_text
    assert '[1] "Soma made a pact with the fey lord"' in candidate_text


def test_party_config_synthesis_also_numbers_extract_citation_tags(monkeypatch, citing_stream_api, tmp_path):
    # Paths inside party/planning.yaml resolve against the campaign root,
    # which for a CLI run is the CWD (docs/config/grounding-isolation.md
    # Track A'). Run from the workspace the way a GM actually does.
    monkeypatch.chdir(tmp_path)
    # Same grounding chain, but through the --party-config branch's own
    # _render_source_group("SESSION EXTRACTIONS", ...) call rather than
    # run_synthesize_pipeline's input_normalizer — both branches must share
    # the one CitationIdAssigner instance built before the branch split.
    _write(tmp_path / "brew.md", "Brewbarry sheet content")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Brewbarry
    sheet: brew.md
""")
    extract_dir = tmp_path / "extractions"
    _write_tagged_extract(extract_dir, "Brewbarry swore an oath to the crown")
    output = tmp_path / "party.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--party-config", str(cfg),
        "--synthesize-only",
        "--extract-dir", str(extract_dir),
        "--output", str(output),
    ])
    party.main()

    prompt = citing_stream_api.calls[0]["user"]
    assert '[cite:1 "Brewbarry swore an oath to the crown"]' in prompt


# ── --batch: routes through the batch entry points ───────────────────────────
# party.py's extract fan-out routes through campaignlib.pipelines (patch
# run_batch there). The non-config synthesis path also routes through
# campaignlib.pipelines (run_synthesize_pipeline); the --party-config path
# calls run_single_batch directly via party.py's own _party_config_synthesize
# helper, so that binding needs patching too — mirrors the existing
# fake_stream_api fixture's two-binding pattern above.

class FakeRunBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, requests, **kwargs):
        self.calls.append({"requests": requests, "kwargs": kwargs})
        return {
            r["custom_id"]: {"status": "succeeded", "text": f"[batch-{r['custom_id']}]",
                             "stop_reason": "end_turn", "error": None, "usage": None}
            for r in requests
        }


class FakeRunSingleBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        return "[batch-synth-result]"


@pytest.fixture
def fake_batch_entry_points(monkeypatch):
    run_batch = FakeRunBatch()
    run_single_batch = FakeRunSingleBatch()
    monkeypatch.setattr(campaignlib.pipelines, "run_batch", run_batch)
    monkeypatch.setattr(campaignlib.pipelines, "run_single_batch", run_single_batch)
    monkeypatch.setattr(party, "run_single_batch", run_single_batch)
    monkeypatch.setattr(party, "make_client", lambda: None)
    return run_batch, run_single_batch


def test_batch_flag_routes_flat_synthesis_through_batch_entry_points(
    monkeypatch, fake_batch_entry_points, tmp_path
):
    """The non-config (--character) path goes through run_synthesize_pipeline,
    which itself routes to run_single_batch when batch=True."""
    run_batch, run_single_batch = fake_batch_entry_points
    summaries = _write(tmp_path / "summaries.md", "a session")
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    output = tmp_path / "party.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--summaries", str(summaries),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--batch",
    ])
    party.main()

    assert len(run_batch.calls) == 1  # extract fan-out
    assert len(run_single_batch.calls) == 1  # synthesis
    assert output.exists()


def test_batch_flag_routes_config_synthesis_through_run_single_batch(
    monkeypatch, fake_batch_entry_points, tmp_path
):
    """The --party-config path calls run_single_batch directly via
    _party_config_synthesize."""
    monkeypatch.chdir(tmp_path)
    _run_batch, run_single_batch = fake_batch_entry_points
    _write(tmp_path / "brew.md", "Brewbarry sheet content")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Brewbarry
    sheet: brew.md
""")
    output = tmp_path / "party.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--party-config", str(cfg),
        "--output", str(output),
        "--batch",
    ])
    party.main()

    assert len(run_single_batch.calls) == 1
    assert run_single_batch.calls[0]["max_tokens"] == 8096
    assert output.exists()


def test_default_no_batch_path_unaffected_by_batch_wiring(monkeypatch, fake_stream_api, tmp_path):
    """FR-011 regression guard — re-asserts test_default_run_uses_per_group_
    source_labels' call count after the batch wiring landed."""
    summaries = _write(tmp_path / "summaries.md", "session content")
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    output = tmp_path / "party.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--summaries", str(summaries),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
    ])
    party.main()

    assert len(fake_stream_api.calls) == 2
    assert output.exists()
