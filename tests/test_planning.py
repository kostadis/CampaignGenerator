"""Tests for planning.py's CLI — focused on the --extract-only checkpoint in both
the standard synthesize flow and --build-dossiers mode. The script-specific
alias resolution in run_synthesize is covered indirectly by tests/test_prep.py
and is intentionally out of scope for this migration."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import campaignlib  # noqa: E402
from pipelines.grounding import planning  # noqa: E402

# planning.py has moved into pipelines/grounding/ and now runs as the
# `planning` console script (pyproject.toml's [project.scripts]). Resolve it
# next to the current interpreter (same venv bin/) rather than relying on
# $PATH, so this test doesn't depend on the venv being "activated" in the
# process running pytest — same rationale as
# server.subprocess_runner.console_script().
PLANNING_BIN = str(Path(sys.executable).parent / "planning")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PLANNING_BIN, *args],
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
        "--output", str(tmp_path / "out.md"),
    )
    assert result.returncode == 1
    assert "--extract-only requires --summaries" in result.stderr


class FakeStreamAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model, "kwargs": kwargs})
        return f"[stub-{len(self.calls)}]"


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(campaignlib.pipelines, "stream_api", fake)
    # planning.py imports stream_api directly; also stub that binding.
    monkeypatch.setattr(planning, "stream_api", fake)
    monkeypatch.setattr(planning, "make_client", lambda: None)
    return fake


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_extract_only_standard_mode_skips_synthesis(monkeypatch, fake_stream_api, tmp_path):
    summaries = _write(tmp_path / "summaries.md", "some session content")
    output = tmp_path / "planning.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--summaries", str(summaries),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--extract-only",
    ])
    planning.main()

    # One extract call, no synthesis call.
    assert len(fake_stream_api.calls) == 1
    assert not output.exists()
    assert any(extract_dir.glob("extract_*.md"))


def test_extract_only_build_dossiers_mode_stops_after_phase_1(monkeypatch, fake_stream_api, tmp_path):
    summaries = _write(tmp_path / "summaries.md", "session content with ## Grundar mentions")
    dossier_dir = tmp_path / "npcs"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--build-dossiers",
        "--summaries", str(summaries),
        "--dossier-dir", str(dossier_dir),
        "--extract-dir", str(extract_dir),
        "--extract-only",
    ])
    planning.main()

    # Phase 1 runs → one extract call. Phase 3 (per-NPC LLM synth) does NOT run.
    assert len(fake_stream_api.calls) == 1
    assert any(extract_dir.glob("dossier_extract_*.md"))
    # No dossier files created — Phase 3 was skipped.
    assert not any(dossier_dir.glob("*.md")) if dossier_dir.exists() else True


# ── Synthesis output-token ceiling (--synth-tokens) ──────────────────────────
# planning.py's Pass 2 synthesis call used to inherit stream_api's own
# default (8096), which silently tail-truncated large planning docs (the
# claude-code backend auto-continues past it in a hidden second turn instead,
# dropping the head). SYNTH_MAX_TOKENS (32000) is now passed explicitly, with
# --synth-tokens as an escape hatch.

def test_synthesis_uses_default_synth_max_tokens(monkeypatch, fake_stream_api, tmp_path):
    """The flat (--npc) path's stream_api call gets max_tokens=SYNTH_MAX_TOKENS
    by default."""
    npc = _write_dossier(tmp_path / "grundar.md", "Grundar")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--npc", str(npc),
        "--output", str(output),
    ])
    planning.main()

    assert len(fake_stream_api.calls) == 1
    assert planning.SYNTH_MAX_TOKENS == 32000
    assert fake_stream_api.calls[0]["kwargs"]["max_tokens"] == planning.SYNTH_MAX_TOKENS


def test_synth_tokens_flag_overrides_default_on_flat_path(monkeypatch, fake_stream_api, tmp_path):
    npc = _write_dossier(tmp_path / "grundar.md", "Grundar")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--npc", str(npc),
        "--output", str(output),
        "--synth-tokens", "5000",
    ])
    planning.main()

    assert fake_stream_api.calls[0]["kwargs"]["max_tokens"] == 5000


def test_synth_tokens_flag_overrides_default_on_planning_config_path(
    monkeypatch, fake_stream_api, tmp_path
):
    """run_synthesize_with_config's stream_api call also honors --synth-tokens."""
    monkeypatch.chdir(tmp_path)
    _write_dossier(tmp_path / "adabra.md", "Adabra")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Adabra
    dossier: adabra.md
""")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--planning-config", str(cfg),
        "--output", str(output),
        "--synth-tokens", "9000",
    ])
    planning.main()

    assert fake_stream_api.calls[0]["kwargs"]["max_tokens"] == 9000


# ── parse/write dossier frontmatter round-trip ───────────────────────────────

def test_parse_write_dossier_roundtrip(tmp_path):
    p = tmp_path / "grundar.md"
    planning.write_dossier(
        p, "Grundar Quartzvein", ["Grundar", "G."], [3, 1, 2, 1], "# Grundar\n\nBody text.\n"
    )
    name, aliases, source_extracts, body = planning.parse_dossier(p)
    assert name == "Grundar Quartzvein"
    assert aliases == ["Grundar", "G."]
    assert source_extracts == [1, 2, 3]  # sorted + deduped
    assert body.strip().startswith("# Grundar")


def test_parse_dossier_missing_source_extracts_returns_empty(tmp_path):
    p = tmp_path / "legacy.md"
    p.write_text("---\nname: Legacy\naliases: []\n---\n\nBody\n", encoding="utf-8")
    name, aliases, source_extracts, body = planning.parse_dossier(p)
    assert name == "Legacy"
    assert source_extracts == []


# ── build-dossiers sidecar dedup ─────────────────────────────────────────────

def _prewrite_extract(extract_dir: Path, num: int, npc_sections: dict[str, str]) -> Path:
    """Seed an extract_dir with a dossier_extract_NNN.md file so Phase 1's cache
    check skips the chunk and Phase 2 reads our pre-written content directly."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    body_parts = [f"## {npc}\n{text}".strip() for npc, text in npc_sections.items()]
    content = "\n\n".join(body_parts) + "\n"
    out = extract_dir / f"dossier_extract_{num:03d}.md"
    out.write_text(content, encoding="utf-8")
    return out


def test_build_dossiers_writes_source_extracts_on_new_dossier(monkeypatch, fake_stream_api, tmp_path):
    """A freshly synthesized dossier records which extracts contributed to it."""
    summaries = _write(tmp_path / "summaries.md", "doesn't matter — extracts are pre-seeded")
    dossier_dir = tmp_path / "npcs"
    extract_dir = tmp_path / "extractions"
    _prewrite_extract(extract_dir, 1, {"Grundar": "First mention of Grundar."})
    _prewrite_extract(extract_dir, 3, {"Grundar": "Third mention of Grundar."})

    monkeypatch.setattr(sys, "argv", [
        "planning.py", "--build-dossiers",
        "--summaries", str(summaries),
        "--dossier-dir", str(dossier_dir),
        "--extract-dir", str(extract_dir),
    ])
    planning.main()

    grundar = dossier_dir / "grundar.md"
    assert grundar.exists()
    name, _aliases, source_extracts, _body = planning.parse_dossier(grundar)
    assert name == "Grundar"
    assert source_extracts == [1, 3]


def test_build_dossiers_seeds_registry_aliases_into_new_dossier(
    monkeypatch, fake_stream_api, tmp_path
):
    """A freshly synthesized dossier is seeded with the registry's known aliases,
    so new dossiers start life consistent with the single-authority registry."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "entity_registry.yaml").write_text(
        "version: 1\n"
        "entities:\n"
        "  - name: Grundar\n"
        "    type: npc\n"
        "    aliases: [Grundar Ironfist, The Smith]\n",
        encoding="utf-8",
    )
    summaries = _write(tmp_path / "summaries.md", "pre-seeded")
    dossier_dir = tmp_path / "npcs"
    extract_dir = tmp_path / "extractions"
    _prewrite_extract(extract_dir, 1, {"Grundar": "First mention of Grundar."})

    # find_alias_registry auto-discovers docs/entity_registry.yaml from CWD.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "planning.py", "--build-dossiers",
        "--summaries", str(summaries),
        "--dossier-dir", str(dossier_dir),
        "--extract-dir", str(extract_dir),
    ])
    planning.main()

    grundar = dossier_dir / "grundar.md"
    assert grundar.exists()
    name, aliases, _src, _body = planning.parse_dossier(grundar)
    assert name == "Grundar"
    assert aliases == ["Grundar Ironfist", "The Smith"]


def test_build_dossiers_skips_sidecar_for_already_absorbed_extract(
    monkeypatch, fake_stream_api, tmp_path
):
    """If canonical.source_extracts already contains N, don't write a sidecar for N."""
    summaries = _write(tmp_path / "summaries.md", "stub")
    dossier_dir = tmp_path / "npcs"
    extract_dir = tmp_path / "extractions"
    _prewrite_extract(extract_dir, 1, {"Grundar": "Extract 1 facts."})

    dossier_dir.mkdir()
    planning.write_dossier(
        dossier_dir / "grundar.md",
        "Grundar", [], [1], "# Grundar\n\nCanonical body.\n",
    )

    monkeypatch.setattr(sys, "argv", [
        "planning.py", "--build-dossiers",
        "--summaries", str(summaries),
        "--dossier-dir", str(dossier_dir),
        "--extract-dir", str(extract_dir),
    ])
    planning.main()

    sidecars = list(dossier_dir.glob("*.new_notes.*.md"))
    assert sidecars == []
    # No synthesize call either — the canonical already exists.
    # (Phase 1 made one extract call; it was cached, so zero stream_api calls.)
    assert len(fake_stream_api.calls) == 0


def test_build_dossiers_writes_sidecar_only_for_new_extract(
    monkeypatch, fake_stream_api, tmp_path
):
    """Mix of absorbed + new: sidecar for the new extract only."""
    summaries = _write(tmp_path / "summaries.md", "stub")
    dossier_dir = tmp_path / "npcs"
    extract_dir = tmp_path / "extractions"
    _prewrite_extract(extract_dir, 1, {"Grundar": "Extract 1 facts."})
    _prewrite_extract(extract_dir, 2, {"Grundar": "Extract 2 — NEW facts."})

    dossier_dir.mkdir()
    planning.write_dossier(
        dossier_dir / "grundar.md",
        "Grundar", [], [1], "# Grundar\n\nCanonical.\n",
    )

    monkeypatch.setattr(sys, "argv", [
        "planning.py", "--build-dossiers",
        "--summaries", str(summaries),
        "--dossier-dir", str(dossier_dir),
        "--extract-dir", str(extract_dir),
    ])
    planning.main()

    sidecars = sorted(p.name for p in dossier_dir.glob("*.new_notes.*.md"))
    assert sidecars == ["grundar.new_notes.002.md"]


def test_build_dossiers_legacy_dossier_without_source_extracts_still_writes_sidecar(
    monkeypatch, fake_stream_api, tmp_path
):
    """Backward compat: dossier without source_extracts frontmatter = unknown
    absorbed state, so every matching extract still gets a sidecar (prior behavior)."""
    summaries = _write(tmp_path / "summaries.md", "stub")
    dossier_dir = tmp_path / "npcs"
    extract_dir = tmp_path / "extractions"
    _prewrite_extract(extract_dir, 1, {"Grundar": "Extract 1 facts."})

    dossier_dir.mkdir()
    # No source_extracts field — legacy dossier.
    (dossier_dir / "grundar.md").write_text(
        "---\nname: Grundar\naliases: []\n---\n\n# Grundar\n\nLegacy body.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "argv", [
        "planning.py", "--build-dossiers",
        "--summaries", str(summaries),
        "--dossier-dir", str(dossier_dir),
        "--extract-dir", str(extract_dir),
    ])
    planning.main()

    sidecars = sorted(p.name for p in dossier_dir.glob("*.new_notes.*.md"))
    assert sidecars == ["grundar.new_notes.001.md"]


def test_build_dossiers_slug_collision_skips_absorbed_extract(
    monkeypatch, fake_stream_api, tmp_path
):
    """Slug-collision branch honors source_extracts too."""
    summaries = _write(tmp_path / "summaries.md", "stub")
    dossier_dir = tmp_path / "npcs"
    extract_dir = tmp_path / "extractions"
    _prewrite_extract(extract_dir, 1, {"Newperson Variant": "Variant says hi."})

    # The existing dossier has a DIFFERENT canonical name (so it's not found via
    # alias resolution) but its filename slug collides with the extraction heading.
    dossier_dir.mkdir()
    planning.write_dossier(
        dossier_dir / "newperson_variant.md",
        "Totally Different Name", [], [1], "# Different\n\nBody.\n",
    )

    monkeypatch.setattr(sys, "argv", [
        "planning.py", "--build-dossiers",
        "--summaries", str(summaries),
        "--dossier-dir", str(dossier_dir),
        "--extract-dir", str(extract_dir),
    ])
    planning.main()

    sidecars = list(dossier_dir.glob("*.new_notes.*.md"))
    assert sidecars == []


# ── Planning config (per-NPC / per-faction arc-score binding) ────────────────

def _write_planning_config(tmp_path, body: str):
    cfg = tmp_path / "planning.yaml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def _write_dossier(path: Path, name: str, body: str = "Dossier body.") -> Path:
    planning.write_dossier(path, name, [], [], f"# {name}\n\n{body}\n")
    return path


def test_load_planning_config_parses_npcs_and_factions(tmp_path):
    _write_dossier(tmp_path / "adabra.md", "Adabra")
    _write(tmp_path / "adabra_arc.md", "Fury of the Wild track")
    _write(tmp_path / "kraken_score.md", "Kraken Society Echoes track")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Adabra
    dossier: adabra.md
    arc_score: adabra_arc.md
factions:
  - name: Kraken Society
    arc_score: kraken_score.md
""")
    config = planning.load_planning_config(cfg, campaign_root=tmp_path)
    assert len(config.npcs) == 1
    assert config.npcs[0].name == "Adabra"
    assert config.npcs[0].dossier.name == "adabra.md"
    assert config.npcs[0].arc_score.name == "adabra_arc.md"
    assert config.npcs[0].trackless is False
    assert len(config.factions) == 1
    assert config.factions[0].name == "Kraken Society"
    assert config.factions[0].dossier is None
    assert config.factions[0].arc_score.name == "kraken_score.md"


def test_load_planning_config_trackless_vs_absent(tmp_path):
    _write_dossier(tmp_path / "lyra.md", "Lyra")
    _write_dossier(tmp_path / "omit.md", "Omit")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Lyra
    dossier: lyra.md
    arc_score: null
  - name: Omit
    dossier: omit.md
""")
    config = planning.load_planning_config(cfg, campaign_root=tmp_path)
    lyra, omit = config.npcs
    assert lyra.arc_score is None and lyra.trackless is True
    assert omit.arc_score is None and omit.trackless is False


def test_load_planning_config_missing_file_fails_loud(tmp_path):
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Ghost
    dossier: missing.md
""")
    with pytest.raises(SystemExit):
        planning.load_planning_config(cfg, campaign_root=tmp_path)


def test_load_planning_config_npc_without_dossier_fails(tmp_path):
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: NoDossier
""")
    with pytest.raises(SystemExit):
        planning.load_planning_config(cfg, campaign_root=tmp_path)


def test_load_planning_config_empty_fails(tmp_path):
    cfg = _write_planning_config(tmp_path, "npcs: []\nfactions: []\n")
    with pytest.raises(SystemExit):
        planning.load_planning_config(cfg, campaign_root=tmp_path)


def test_planning_config_rejects_arc_scores_flag(tmp_path):
    """--planning-config replaces --arc-scores; passing both is an error."""
    _write_dossier(tmp_path / "any.md", "Any")
    _write(tmp_path / "score.md", "score body")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Any
    dossier: any.md
""")
    result = _run(
        "--planning-config", str(cfg),
        "--arc-scores", str(tmp_path / "score.md"),
        "--output", str(tmp_path / "out.md"),
    )
    assert result.returncode == 1
    assert "replaces --arc-scores" in result.stderr


def test_planning_config_coexists_with_unbound_npc_flag(monkeypatch, fake_stream_api, tmp_path):
    # Paths inside planning.yaml resolve against the campaign root, which
    # for a CLI run is the CWD (docs/config/grounding-isolation.md Track
    # A'). Run from the workspace the way a GM actually does.
    monkeypatch.chdir(tmp_path)
    """--planning-config + --npc renders bound entities (with score nested)
    AND unbound NPCs (plain dossier blocks) in one # NPC DOSSIERS section."""
    _write_dossier(tmp_path / "adabra.md", "Adabra", "Adabra dossier prose")
    _write(tmp_path / "adabra_arc.md", "Fury of the Wild")
    _write_dossier(tmp_path / "harbin.md", "Harbin", "Harbin dossier prose")
    _write_dossier(tmp_path / "toblen.md", "Toblen", "Toblen dossier prose")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Adabra
    dossier: adabra.md
    arc_score: adabra_arc.md
""")

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--planning-config", str(cfg),
        "--npc", str(tmp_path / "harbin.md"), str(tmp_path / "toblen.md"),
        "--output", str(tmp_path / "planning.md"),
    ])
    planning.main()

    prompt = fake_stream_api.calls[0]["user"]
    # All three NPCs appear under # NPC DOSSIERS
    assert "# NPC DOSSIERS" in prompt
    assert "## Adabra" in prompt
    assert "## Harbin" in prompt
    assert "## Toblen" in prompt
    # Adabra has the bound arc-score nested in her block
    adabra_idx = prompt.index("## Adabra")
    next_sep = prompt.index("\n---\n", adabra_idx)
    adabra_block = prompt[adabra_idx:next_sep]
    assert "<!-- Threat arc score: adabra_arc.md -->" in adabra_block
    assert "Adabra dossier prose" in adabra_block
    assert "Fury of the Wild" in adabra_block
    # Harbin and Toblen have NO arc-score block (they're unbound dossiers)
    harbin_idx = prompt.index("## Harbin")
    toblen_idx = prompt.index("## Toblen")
    # Find the slice between Harbin's start and Toblen's start.
    harbin_block = prompt[harbin_idx:toblen_idx]
    assert "<!-- NPC dossier: harbin.md -->" in harbin_block
    assert "<!-- Threat arc score:" not in harbin_block
    assert "INTENTIONALLY TRACKLESS" not in harbin_block


def test_planning_config_overlap_with_npc_fails(monkeypatch, fake_stream_api, tmp_path):
    """Same NPC can't appear in both --planning-config and --npc."""
    _write_dossier(tmp_path / "adabra.md", "Adabra")
    _write(tmp_path / "adabra_arc.md", "score")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Adabra
    dossier: adabra.md
    arc_score: adabra_arc.md
""")

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--planning-config", str(cfg),
        "--npc", str(tmp_path / "adabra.md"),
        "--output", str(tmp_path / "planning.md"),
    ])
    with pytest.raises(SystemExit):
        planning.main()


def test_planning_config_renders_per_entity_block(monkeypatch, fake_stream_api, tmp_path):
    # Paths inside planning.yaml resolve against the campaign root, which
    # for a CLI run is the CWD (docs/config/grounding-isolation.md Track
    # A'). Run from the workspace the way a GM actually does.
    monkeypatch.chdir(tmp_path)
    _write_dossier(tmp_path / "adabra.md", "Adabra", "Adabra dossier prose")
    _write(tmp_path / "adabra_arc.md", "Fury of the Wild track mechanics")
    _write_dossier(tmp_path / "lyra.md", "Lyra", "Lyra dossier prose")
    _write(tmp_path / "kraken_score.md", "Kraken Society Echoes track")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Adabra
    dossier: adabra.md
    arc_score: adabra_arc.md
  - name: Lyra
    dossier: lyra.md
    arc_score: null
factions:
  - name: Kraken Society
    arc_score: kraken_score.md
""")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--planning-config", str(cfg),
        "--output", str(output),
    ])
    planning.main()

    assert len(fake_stream_api.calls) == 1
    prompt = fake_stream_api.calls[0]["user"]
    # Per-entity sections
    assert "# NPC DOSSIERS" in prompt
    assert "# FACTIONS" in prompt
    assert "## Adabra" in prompt
    assert "## Lyra" in prompt
    assert "## Kraken Society" in prompt
    # Adabra has dossier + arc-score together
    assert "<!-- NPC dossier: adabra.md -->" in prompt
    assert "<!-- Threat arc score: adabra_arc.md -->" in prompt
    # Adabra body and arc-score body co-occur within ~one block (tight binding)
    adabra_idx = prompt.index("## Adabra")
    next_block_idx = prompt.index("\n---\n", adabra_idx)
    adabra_block = prompt[adabra_idx:next_block_idx]
    assert "Adabra dossier prose" in adabra_block
    assert "Fury of the Wild track mechanics" in adabra_block
    # Lyra trackless: no arc-score file, but explicit marker
    lyra_idx = prompt.index("## Lyra")
    lyra_block = prompt[lyra_idx:]
    assert "INTENTIONALLY TRACKLESS" in lyra_block
    # Faction has no dossier comment, only arc-score
    faction_idx = prompt.index("## Kraken Society")
    faction_block = prompt[faction_idx:]
    assert "<!-- Threat arc score: kraken_score.md -->" in faction_block
    assert "<!-- NPC dossier:" not in faction_block
    # Legacy flat group must NOT appear when planning-config is in use
    assert "# THREAT ARC SCORE MECHANICS" not in prompt
    assert output.exists()


def test_planning_config_synthesize_only_works_without_summaries(
    monkeypatch, fake_stream_api, tmp_path
):
    # Paths inside planning.yaml resolve against the campaign root, which
    # for a CLI run is the CWD (docs/config/grounding-isolation.md Track
    # A'). Run from the workspace the way a GM actually does.
    monkeypatch.chdir(tmp_path)
    """A planning-config-only invocation (no --summaries) should succeed and
    produce planning.md from just the bound entity blocks."""
    _write_dossier(tmp_path / "adabra.md", "Adabra")
    _write(tmp_path / "adabra_arc.md", "Adabra arc")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Adabra
    dossier: adabra.md
    arc_score: adabra_arc.md
""")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--planning-config", str(cfg),
        "--output", str(output),
    ])
    planning.main()

    assert len(fake_stream_api.calls) == 1
    assert output.exists()


# ── Citation grounding ───────────────────────────────────────────────────────
# Extract-phase `[cite: "..."]` tags get numbered before reaching synthesis
# (CitationIdAssigner), and whatever the model cites back gets verified and
# rendered into a `## Sources` section on the final planning.md. Unlike
# party.py, planning.py has no top-level `normalize` — run_synthesize() and
# run_synthesize_with_config() each build their own alias normalizer
# internally and compose it with the one CitationIdAssigner main() builds
# before the config/flat branch split, so both paths need their own coverage.


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
    monkeypatch.setattr(planning, "stream_api", fake)
    monkeypatch.setattr(planning, "make_client", lambda: None)
    return fake


def _write_tagged_extract(extract_dir: Path, quote: str) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)
    return _write(
        extract_dir / "extract_001.md",
        f'- Test claim drawn from the session. [cite: "{quote}"]\n',
    )


def test_synthesis_numbers_extract_citation_tags(monkeypatch, citing_stream_api, tmp_path):
    """Flat path (--npc, no --planning-config) goes through run_synthesize()."""
    npc = _write_dossier(tmp_path / "grundar.md", "Grundar")
    extract_dir = tmp_path / "extractions"
    _write_tagged_extract(extract_dir, "Grundar swore vengeance against the cult")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--npc", str(npc),
        "--synthesize-only",
        "--extract-dir", str(extract_dir),
        "--output", str(output),
    ])
    planning.main()

    synthesize_prompt = citing_stream_api.calls[0]["user"]
    # The extract pass's un-numbered [cite: "..."] tag is assigned a stable
    # numeric ID before the synthesis prompt reaches the model.
    assert '[cite:1 "Grundar swore vengeance against the cult"]' in synthesize_prompt


def test_final_document_gets_sources_section(monkeypatch, citing_stream_api, tmp_path):
    npc = _write_dossier(tmp_path / "grundar.md", "Grundar")
    extract_dir = tmp_path / "extractions"
    _write_tagged_extract(extract_dir, "Grundar swore vengeance against the cult")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--npc", str(npc),
        "--synthesize-only",
        "--extract-dir", str(extract_dir),
        "--output", str(output),
    ])
    planning.main()

    written = output.read_text(encoding="utf-8")
    assert "## Sources" in written
    assert '[1] "Grundar swore vengeance against the cult"' in written


def test_planning_config_synthesis_also_numbers_extract_citation_tags(
    monkeypatch, citing_stream_api, tmp_path
):
    # Paths inside planning.yaml resolve against the campaign root, which
    # for a CLI run is the CWD (docs/config/grounding-isolation.md Track
    # A'). Run from the workspace the way a GM actually does.
    monkeypatch.chdir(tmp_path)
    # Same grounding chain, but through run_synthesize_with_config's own
    # _render_flat_section("SESSION EXTRACTIONS", ...) call rather than
    # run_synthesize's inline loop — both branches must share the one
    # CitationIdAssigner instance main() builds before the config/flat
    # branch split.
    _write_dossier(tmp_path / "adabra.md", "Adabra")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Adabra
    dossier: adabra.md
""")
    extract_dir = tmp_path / "extractions"
    _write_tagged_extract(extract_dir, "Adabra sealed the rift with the last shard")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--planning-config", str(cfg),
        "--synthesize-only",
        "--extract-dir", str(extract_dir),
        "--output", str(output),
    ])
    planning.main()

    prompt = citing_stream_api.calls[0]["user"]
    assert '[cite:1 "Adabra sealed the rift with the last shard"]' in prompt

    written = output.read_text(encoding="utf-8")
    assert "## Sources" in written
    assert '[1] "Adabra sealed the rift with the last shard"' in written


def test_run_synthesize_and_run_synthesize_with_config_share_one_id_assigner(
    monkeypatch, tmp_path
):
    """planning.py's main() constructs exactly one CitationIdAssigner and
    passes it into whichever of the two hand-rolled synthesis functions
    actually runs (a single invocation only ever exercises one branch).
    Call both functions directly against the same instance to confirm IDs
    stay sequential across them — if a future refactor gave each branch its
    own assigner, both would independently start at [cite:1 ...] and the
    numbers in a real run would never collide, silently masking the bug."""
    captured: list[str] = []

    def _capture(client, system, user, model, *args, **kwargs):
        captured.append(user)
        return "stub"

    monkeypatch.setattr(planning, "stream_api", _capture)

    id_assigner = campaignlib.CitationIdAssigner()

    _write_dossier(tmp_path / "adabra.md", "Adabra")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Adabra
    dossier: adabra.md
""")
    config = planning.load_planning_config(cfg, campaign_root=tmp_path)
    extract_dir1 = tmp_path / "extractions1"
    extract1 = _write_tagged_extract(extract_dir1, "Adabra sealed the rift")
    planning.run_synthesize_with_config(
        None, config, [], [extract1], [], "model", id_assigner,
    )

    npc = _write_dossier(tmp_path / "grundar.md", "Grundar")
    extract_dir2 = tmp_path / "extractions2"
    extract2 = _write_tagged_extract(extract_dir2, "Grundar swore vengeance")
    planning.run_synthesize(
        None, [npc], [], [extract2], [], "model", id_assigner,
    )

    assert id_assigner.id_to_quote == {
        1: "Adabra sealed the rift",
        2: "Grundar swore vengeance",
    }
    assert '[cite:1 "Adabra sealed the rift"]' in captured[0]
    assert '[cite:2 "Grundar swore vengeance"]' in captured[1]


# ── --batch: routes through the batch entry points ───────────────────────────
# planning.py's extract fan-out routes through campaignlib.pipelines (patch
# run_batch there), but BOTH synthesis functions (run_synthesize and
# run_synthesize_with_config) call run_single_batch directly — planning.py
# imports it into its own namespace, so that binding needs patching too
# (mirrors the existing fake_stream_api fixture's two-binding pattern above).

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
    monkeypatch.setattr(planning, "run_single_batch", run_single_batch)
    monkeypatch.setattr(planning, "make_client", lambda: None)
    return run_batch, run_single_batch


def test_batch_flag_routes_extract_fan_out_through_run_batch(
    monkeypatch, fake_batch_entry_points, tmp_path
):
    run_batch, _run_single_batch = fake_batch_entry_points
    summaries = _write(tmp_path / "summaries.md", "some session content")
    output = tmp_path / "planning.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--summaries", str(summaries),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--extract-only",
        "--batch",
    ])
    planning.main()

    assert len(run_batch.calls) == 1
    assert any(extract_dir.glob("extract_*.md"))


def test_batch_flag_routes_flat_synthesis_through_run_single_batch(
    monkeypatch, fake_batch_entry_points, tmp_path
):
    """The --npc (no --planning-config) path goes through run_synthesize()."""
    _run_batch, run_single_batch = fake_batch_entry_points
    npc = _write_dossier(tmp_path / "grundar.md", "Grundar")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--npc", str(npc),
        "--output", str(output),
        "--batch",
    ])
    planning.main()

    assert len(run_single_batch.calls) == 1
    assert run_single_batch.calls[0]["max_tokens"] == planning.SYNTH_MAX_TOKENS
    assert output.exists()


def test_batch_flag_routes_config_synthesis_through_run_single_batch(
    monkeypatch, fake_batch_entry_points, tmp_path
):
    """The --planning-config path goes through run_synthesize_with_config()."""
    monkeypatch.chdir(tmp_path)
    _run_batch, run_single_batch = fake_batch_entry_points
    _write_dossier(tmp_path / "adabra.md", "Adabra")
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: Adabra
    dossier: adabra.md
""")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--planning-config", str(cfg),
        "--output", str(output),
        "--batch",
    ])
    planning.main()

    assert len(run_single_batch.calls) == 1
    assert output.exists()


def test_default_no_batch_path_unaffected_by_batch_wiring(monkeypatch, fake_stream_api, tmp_path):
    """FR-011 regression guard — the default (no --batch) flat-path flow is
    unchanged after the batch wiring landed (same shape as
    test_synthesis_uses_default_synth_max_tokens above)."""
    npc = _write_dossier(tmp_path / "grundar.md", "Grundar")
    output = tmp_path / "planning.md"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--npc", str(npc),
        "--output", str(output),
    ])
    planning.main()

    assert len(fake_stream_api.calls) == 1
    assert output.exists()
