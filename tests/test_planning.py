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
import planning  # noqa: E402


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "planning.py"), *args],
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
        self.calls.append({"system": system, "user": user, "model": model})
        return f"[stub-{len(self.calls)}]"


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(campaignlib, "stream_api", fake)
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
    config = planning.load_planning_config(cfg)
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
    config = planning.load_planning_config(cfg)
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
        planning.load_planning_config(cfg)


def test_load_planning_config_npc_without_dossier_fails(tmp_path):
    cfg = _write_planning_config(tmp_path, """
npcs:
  - name: NoDossier
""")
    with pytest.raises(SystemExit):
        planning.load_planning_config(cfg)


def test_load_planning_config_empty_fails(tmp_path):
    cfg = _write_planning_config(tmp_path, "npcs: []\nfactions: []\n")
    with pytest.raises(SystemExit):
        planning.load_planning_config(cfg)


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
