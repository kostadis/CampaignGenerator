"""CLI tests for summary_native validate/build (T012): exit codes and writes."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from pipelines.summary_native import schema
from pipelines.summary_native.cli import main

FIX = Path(__file__).parent / "fixtures" / "summary_native"


@pytest.fixture
def camp(tmp_path, monkeypatch):
    root = tmp_path / "camp"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("paths: {}\n")
    monkeypatch.chdir(root)
    return root


def _corpus(camp, name="clean", dest="summaries"):
    shutil.copytree(FIX / name, camp / dest)
    return camp / dest


def _tree(root: Path):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_validate_writes_only_report_in_range_dir(camp, capsys):
    _corpus(camp)
    rc = main(["validate", "--summaries-dir", "summaries", "--since", "2", "--until", "5"])
    assert rc == 0
    rd = camp / "docs" / "summary_native" / "ch002-005"
    assert _tree(rd) == ["validation_report.json", "validation_report.md"]
    assert _tree(camp / "docs") == [
        "summary_native/ch002-005/validation_report.json",
        "summary_native/ch002-005/validation_report.md",
    ]
    out = capsys.readouterr().out
    assert "# Validation report" in out and "range-gap" in out
    assert json.loads((rd / "validation_report.json").read_text())["blocking_count"] == 0


def test_validate_exit_1_on_blocking(camp, capsys):
    _corpus(camp, "multi_error")
    assert main(["validate", "--summaries-dir", "summaries"]) == 1
    assert (camp / "docs/summary_native/ch010-012/validation_report.md").exists()


def test_unset_range_uses_first_and_last(camp):
    _corpus(camp)
    assert main(["validate", "--summaries-dir", "summaries"]) == 0
    assert (camp / "docs/summary_native/ch002-005").is_dir()


def test_refusals_exit_2_and_write_nothing(camp, capsys):
    _corpus(camp)
    (camp / "empty").mkdir()
    assert main(["validate", "--summaries-dir", "empty"]) == 2
    assert main(["validate", "--summaries-dir", "missing"]) == 2
    assert main(["validate", "--summaries-dir", "summaries", "--since", "1"]) == 2
    assert "2, 3, 5" in capsys.readouterr().err
    assert main(["validate", "--summaries-dir", "summaries", "--since", "5", "--until", "2"]) == 2
    assert not (camp / "docs").exists()


def test_no_summaries_dir_is_error(camp, capsys):
    assert main(["validate"]) == 2
    assert "no summaries directory" in capsys.readouterr().err


def test_summaries_dir_from_grounding_yaml(camp):
    _corpus(camp)
    (camp / "config" / "grounding.yaml").write_text(
        "summary_native:\n  summaries_dir: summaries\n  out_root: out/sn\n  dup_threshold: 0.9\n"
    )
    assert main(["build"]) == 0
    assert (camp / "out/sn/ch002-005/manifest.json").exists()


def test_ensemble_input_refused(camp):
    d = camp / "docs" / "ensemble" / "s"
    d.parent.mkdir(parents=True)
    shutil.copytree(FIX / "clean", d)
    assert main(["validate", "--summaries-dir", "docs/ensemble/s"]) == 2


def test_build_ok_then_exists_needs_force(camp):
    _corpus(camp)
    base = ["build", "--summaries-dir", "summaries"]
    assert main(base) == 0
    rd = camp / "docs/summary_native/ch002-005"
    assert {"manifest.json", "chronology.md", "memorable_moments.md", "validation_report.md"} <= set(
        _tree(rd)
    )
    assert main(base) == 2
    assert main([*base, "--force"]) == 0


def test_validate_then_build_same_range_dir(camp):
    _corpus(camp)
    assert main(["validate", "--summaries-dir", "summaries"]) == 0
    assert main(["build", "--summaries-dir", "summaries"]) == 0


def test_build_blocked_writes_report_only(camp):
    _corpus(camp, "multi_error")
    assert main(["build", "--summaries-dir", "summaries"]) == 1
    assert _tree(camp / "docs/summary_native/ch010-012") == [
        "validation_report.json",
        "validation_report.md",
    ]


def test_build_refuses_ensemble_out_root(camp):
    _corpus(camp)
    rd = camp / "docs/summary_native/ch002-005"
    rd.mkdir(parents=True)
    (rd / "merged.json").write_text("{}")
    assert main(["build", "--summaries-dir", "summaries"]) == 2
    assert main(["validate", "--summaries-dir", "summaries"]) == 2


def test_manifest_records_registry_and_canon_digests(camp):
    _corpus(camp)
    (camp / "docs").mkdir()
    (camp / "docs" / "entity_registry.yaml").write_text("version: 1\nentities: []\n")
    (camp / "docs" / "summary_native").mkdir()
    (camp / "docs" / "summary_native" / "canon.yaml").write_text("not_duplicates: []\n")
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    m = json.loads((camp / "docs/summary_native/ch002-005/manifest.json").read_text())
    assert len(m["canon"]["registry_sha256"]) == 64 and len(m["canon"]["canon_sha256"]) == 64


def test_unreadable_file_reported_with_other_findings_exit_1(camp, capsys):
    d = camp / "summaries"
    d.mkdir()
    (d / "002-bad.md").write_bytes(b"\xff\xfe\x00bad")
    (d / "003-m.md").write_text("# Chapter 4\n\n## Scenes\n\n### 003.01 X\nS.\n")
    assert main(["validate", "--summaries-dir", "summaries"]) == 1
    md = (camp / "docs/summary_native/ch002-003/validation_report.md").read_text()
    assert "unreadable-file" in md and "title-chapter-mismatch" in md


# ── review-finding regressions ──────────────────────────────────────────────


def _rd(camp):
    return camp / "docs/summary_native/ch002-005"


def test_build_ignores_out_of_range_unreadable_and_dir_named_md(camp):
    d = _corpus(camp)
    (d / "001-x.md").write_bytes(b"\xff\xfe\x00bad")
    (d / "zzz.md").mkdir()
    assert main(["build", "--summaries-dir", "summaries", "--since", "2"]) == 0
    m = json.loads((_rd(camp) / "manifest.json").read_text())
    assert all("001-x" not in f["path"] for f in m["files"])
    assert m["complete"] is True


def test_interrupted_build_recovers_with_force(camp, monkeypatch, capsys):
    from pipelines.summary_native import corpus

    _corpus(camp)
    base = ["build", "--summaries-dir", "summaries"]
    real = corpus.render_memorable_moments

    def boom(files):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(corpus, "render_memorable_moments", boom)
    with pytest.raises(RuntimeError):
        main(base)
    monkeypatch.setattr(corpus, "render_memorable_moments", real)
    assert json.loads((_rd(camp) / "manifest.json").read_text())["complete"] is False
    assert main(["validate", "--summaries-dir", "summaries"]) == 1 - 1
    capsys.readouterr()
    assert main(base) == 2
    assert "did not finish" in capsys.readouterr().err
    assert main([*base, "--force"]) == 0
    assert json.loads((_rd(camp) / "manifest.json").read_text())["complete"] is True


def test_load_manifest_requires_complete(camp):
    from pipelines.summary_native import corpus

    _corpus(camp)
    main(["build", "--summaries-dir", "summaries"])
    assert corpus.load_manifest(_rd(camp))["complete"] is True
    (_rd(camp) / "manifest.json").write_text('{"kind": "summary_native", "complete": false}')
    with pytest.raises(corpus.CorpusError):
        corpus.load_manifest(_rd(camp))
    assert corpus.load_manifest(_rd(camp), require_complete=False)


def test_force_with_stray_file_keeps_it(camp):
    _corpus(camp)
    base = ["build", "--summaries-dir", "summaries"]
    assert main(base) == 0
    notes = _rd(camp) / "notes.md"
    notes.write_text("mine")
    assert main([*base, "--force"]) == 0
    assert notes.read_text() == "mine"
    assert (_rd(camp) / "manifest.json").is_file()


def test_report_notes_existing_corpus_state(camp):
    d = _corpus(camp)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    assert main(["validate", "--summaries-dir", "summaries"]) == 0
    md = (_rd(camp) / "validation_report.md").read_text()
    assert "Existing corpus: matches current input" in md
    assert json.loads((_rd(camp) / "validation_report.json").read_text())["existing_corpus"]["state"] == "matches"
    f = sorted(d.glob("00[2-5]*.md"))[0]
    f.write_text(f.read_text() + "\nextra\n")
    assert main(["validate", "--summaries-dir", "summaries"]) == 0
    md = (_rd(camp) / "validation_report.md").read_text()
    assert "differ from current input" in md and "build --force" in md and f.name in md
    ec = json.loads((_rd(camp) / "validation_report.json").read_text())["existing_corpus"]
    assert ec["differ"] == 1 and ec["changed"]


# ── synth / compare argument contract (T021) ───────────────────────────────


def test_synth_has_backend_flags_and_rejects_unknown_doc(camp, capsys):
    from pipelines.summary_native.cli import build_parser

    p = build_parser()
    ns = p.parse_args(["synth", "world_state", "--backend", "dgx", "--endpoint", "http://x", "--model", "m",
                       "--max-tokens", "5", "--name", "A", "B", "--audit", "a", "b"])
    assert (ns.backend, ns.endpoint, ns.model, ns.max_tokens) == ("dgx", "http://x", "m", 5)
    assert ns.name == ["A", "B"] and ns.audit == ["a", "b"]
    with pytest.raises(SystemExit):
        p.parse_args(["synth", "bogus"])
    with pytest.raises(SystemExit):
        p.parse_args(["compare", "world_state"])  # --live is required


def test_compare_writes_diff_and_reads_inputs_only(camp, capsys):
    _corpus(camp)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    rd = camp / "docs/summary_native/ch002-005"
    (rd / "state/drafts").mkdir(parents=True)
    draft = rd / "state/drafts/party.draft.md"
    draft.write_text("## A\n\nSee ch 7 and Chapter 12.\nnew line\n")
    live = camp / "live.md"
    live.write_text("## A\n\nSee ch 3.\n")
    before = (draft.read_bytes(), live.read_bytes())
    assert main(["compare", "party", "--summaries-dir", "summaries", "--live", "live.md"]) == 0
    out = capsys.readouterr().out
    assert "heuristic" in out and "12" in out
    diff = (rd / "state/drafts/party.vs-live.diff").read_text()
    assert "--- a/" in diff and "+++ b/" in diff and "+new line" in diff
    assert (draft.read_bytes(), live.read_bytes()) == before


def test_compare_errors_when_draft_or_live_missing(camp):
    _corpus(camp)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    (camp / "live.md").write_text("x\n")
    assert main(["compare", "party", "--summaries-dir", "summaries", "--live", "live.md"]) == 2
    rd = camp / "docs/summary_native/ch002-005"
    (rd / "state/drafts").mkdir(parents=True)
    (rd / "state/drafts/party.draft.md").write_text("x\n")
    assert main(["compare", "party", "--summaries-dir", "summaries", "--live", "nope.md"]) == 2


def test_synth_incompatible_backend_model_exits_2_without_traceback(camp, capsys):
    _corpus(camp)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    capsys.readouterr()
    rc = main(["synth", "world_state", "--summaries-dir", "summaries", "--dump-only",
               "--backend", "codex-cli", "--model", "claude-opus-5-5"])
    err = capsys.readouterr().err
    assert rc == 2 and "incompatible with backend 'codex-cli'" in err and "Traceback" not in err


@pytest.mark.parametrize(
    "body", ["entities: [unclosed\n", "entities:\n  - type: npc\n", "entities:\n  - just a string\n"]
)
@pytest.mark.parametrize("cmd", ["validate", "build"])
def test_malformed_registry_exits_2_cleanly(camp, capsys, cmd, body):
    _corpus(camp)
    (camp / "docs").mkdir()
    reg = camp / "docs" / "entity_registry.yaml"
    reg.write_text(body)
    assert main([cmd, "--summaries-dir", "summaries"]) == 2
    err = capsys.readouterr().err
    assert f"invalid entity registry {reg}" in err and "Traceback" not in err


def test_default_registry_resolved_from_config_root_not_cwd(camp, tmp_path, monkeypatch):
    import hashlib

    _corpus(camp)
    (camp / "docs").mkdir()
    reg = camp / "docs" / "entity_registry.yaml"
    reg.write_text("version: 1\nentities: []\n# campaign B\n")
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "docs").mkdir()
    (other / "docs" / "entity_registry.yaml").write_text("version: 1\nentities: []\n# A\n")
    monkeypatch.chdir(other)
    cfg = str(camp / "config" / "config.yaml")
    assert main(["build", "--config", cfg, "--summaries-dir", str(camp / "summaries")]) == 0
    m = json.loads((camp / "docs/summary_native/ch002-005/manifest.json").read_text())
    assert m["canon"]["registry_sha256"] == hashlib.sha256(reg.read_bytes()).hexdigest()


# ── spec 033 US1: extract and the chunked synth documents (T015) ─────────────


def test_extract_is_a_subcommand_with_the_backend_family_and_no_default_backend():
    from pipelines.summary_native.cli import build_parser

    ns = build_parser().parse_args(["extract", "--chunk-chars", "5", "--max-tokens", "9", "--dump-only", "--force",
                                    "--backend", "dgx", "--endpoint", "http://x", "--model", "m",
                                    "--claude-code-effort", "low"])
    assert (ns.command, ns.chunk_chars, ns.max_tokens, ns.dump_only, ns.force) == ("extract", 5, 9, True, True)
    assert (ns.backend, ns.endpoint, ns.model, ns.claude_code_effort) == ("dgx", "http://x", "m", "low")
    bare = build_parser().parse_args(["extract"])
    # flag > grounding.yaml > schema needs the flag to be absent, not defaulted
    assert bare.backend is None and bare.model is None and bare.chunk_chars is None
    assert bare.max_tokens == schema.DEFAULT_MAX_TOKENS


def test_synth_backend_is_not_defaulted_so_the_prose_config_can_apply():
    from pipelines.summary_native.cli import build_parser

    assert build_parser().parse_args(["synth", "party"]).backend is None


def test_extract_refuses_a_bad_config_block_cleanly(camp, capsys):
    _corpus(camp)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    (camp / "config" / "grounding.yaml").write_text("summary_native:\n  extract:\n    chunk_chars: 0\n")
    capsys.readouterr()
    assert main(["extract", "--summaries-dir", "summaries", "--dump-only"]) == 2
    err = capsys.readouterr().err
    assert "chunk_chars" in err and "Traceback" not in err


def test_compare_reads_the_chunked_drafts_from_state(camp):
    _corpus(camp)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    drafts = camp / "docs/summary_native/ch002-005/state/drafts"
    drafts.mkdir(parents=True)
    (drafts / "world_state.draft.md").write_text("## A\n\nnew\n")
    (camp / "live.md").write_text("## A\n\nold\n")
    assert main(["compare", "world_state", "--summaries-dir", "summaries", "--live", "live.md"]) == 0
    assert (drafts / "world_state.vs-live.diff").is_file()


# ── spec 034 US1: the party flags ───────────────────────────────────────────


def _built(camp):
    _corpus(camp)
    assert main(["build", "--summaries-dir", "summaries"]) == 0


@pytest.mark.parametrize("flag,value", [("--name", "Kalan"), ("--recent-chapters", "2"), ("--recurring-min", "2")])
def test_party_refuses_the_npc_selection_flags(camp, capsys, flag, value):
    _built(camp)
    capsys.readouterr()
    assert main(["synth", "party", "--summaries-dir", "summaries", flag, value]) == 2
    err = capsys.readouterr().err
    assert f"{flag} does not apply to party" in err
    assert "party selects no NPCs; these apply to planning and world_state" in err


@pytest.mark.parametrize("doc", ["party", "campaign_state"])
def test_fallback_npc_lines_is_refused_outside_world_state_and_planning(camp, capsys, doc):
    _built(camp)
    capsys.readouterr()
    assert main(["synth", doc, "--summaries-dir", "summaries", "--fallback-npc-lines"]) == 2
    assert f"--fallback-npc-lines applies to world_state and planning only, not {doc}" in capsys.readouterr().err


def test_party_prose_backend_defaults_come_from_the_prose_block_not_the_parser():
    from pipelines.summary_native.cli import build_parser

    ns = build_parser().parse_args(["synth", "party", "--party-config", "x.yaml"])
    assert ns.party_config == "x.yaml" and ns.backend is None and ns.model is None


# ── spec 034 US3: thread-propose ────────────────────────────────────────────


def test_thread_propose_is_a_subcommand_with_its_own_flags_and_no_parser_defaults_for_the_prose_backend():
    from pipelines.summary_native.cli import SUBCOMMANDS, build_parser

    assert "thread-propose" in SUBCOMMANDS
    ns = build_parser().parse_args(["thread-propose", "--since", "2", "--until", "9"])
    assert (ns.since, ns.until) == (2, 9)
    assert ns.max_input_chars is None  # resolved to schema.DEFAULT_THREAD_PROPOSE_MAX_INPUT_CHARS in the CLI
    assert ns.max_tokens == schema.DEFAULT_MAX_TOKENS and ns.dump_only is False
    assert ns.backend is None and ns.model is None
    ns = build_parser().parse_args(["thread-propose", "--since", "2", "--until", "9", "--max-input-chars", "5000", "--dump-only"])
    assert ns.max_input_chars == 5000 and ns.dump_only is True
    with pytest.raises(SystemExit):
        build_parser().parse_args(["thread-propose", "--max-input-chars", "0"])


@pytest.mark.parametrize("given", [["--since", "2"], ["--until", "9"], []])
def test_thread_propose_refuses_a_missing_range_before_anything_else(camp, capsys, given):
    _corpus(camp)
    assert main(["thread-propose", "--summaries-dir", "summaries", *given]) == 2
    err = capsys.readouterr().err
    assert "--since" in err and "--until" in err


# ── spec 034 US2: the planning flags ────────────────────────────────────────


def test_planning_takes_the_selection_flags_the_config_flag_and_the_fallback_flag():
    from pipelines.summary_native.cli import build_parser

    ns = build_parser().parse_args([
        "synth", "planning", "--planning-config", "p.yaml", "--name", "Kalan", "Ront", "--recent-chapters", "3",
        "--recurring-min", "5", "--fallback-npc-lines"])
    assert ns.planning_config == "p.yaml" and ns.name == ["Kalan", "Ront"]
    assert (ns.recent_chapters, ns.recurring_min, ns.fallback_npc_lines) == (3, 5, True)
    assert ns.backend is None and ns.model is None  # the prose block resolves them


def test_planning_config_applies_to_planning_only(camp, capsys):
    _built(camp)
    capsys.readouterr()
    assert main(["synth", "world_state", "--summaries-dir", "summaries", "--planning-config", "p.yaml"]) == 2
    assert "--planning-config applies to planning only, not world_state" in capsys.readouterr().err


# ── spec 034 US6: one build surface, the one-shot flags retired ─────────────

RETIRED = [
    ("--parts", "2", schema.PARTS_REFUSAL),
    ("--parts", "0", schema.PARTS_REFUSAL),  # an explicit zero is still the retired flag
    ("--world-state", "docs/world_state.md", f"--world-state is retired: {schema.UPSTREAM_REFUSAL}"),
    ("--campaign-state", "docs/campaign_state.md", f"--campaign-state is retired: {schema.UPSTREAM_REFUSAL}"),
]


@pytest.mark.parametrize("doc", schema.DOCS)
@pytest.mark.parametrize("flag,value,message", RETIRED)
def test_every_retired_flag_is_refused_with_its_replacement_for_every_document(camp, capsys, doc, flag, value, message):
    _built(camp)
    capsys.readouterr()
    assert main(["synth", doc, "--summaries-dir", "summaries", flag, value]) == 2
    err = capsys.readouterr().err
    assert message in err
    assert "Traceback" not in err and "unrecognized arguments" not in err


@pytest.mark.parametrize("flag,value,message", RETIRED)
def test_a_retired_flag_is_refused_before_the_corpus_is_read(camp, capsys, flag, value, message):
    """Nothing is built and no summaries directory is given: the flag is gone whatever else is wrong."""
    assert main(["synth", "party", flag, value]) == 2
    assert message in capsys.readouterr().err


def test_the_retired_flags_are_not_advertised_in_help(capsys):
    from pipelines.summary_native.cli import build_parser

    helptext = build_parser()._subparsers._group_actions[0].choices["synth"].format_help()
    for flag in ("--parts", "--world-state", "--campaign-state"):
        assert flag not in helptext


def test_the_schema_names_the_retired_flags_and_no_longer_declares_a_parts_default():
    assert set(schema.RETIRED_SYNTH_FLAGS) == {"parts", "world_state", "campaign_state"}
    assert not hasattr(schema, "DEFAULT_PARTS") and not hasattr(schema, "STATE_PARTS_REFUSAL")


def test_npc_root_is_accepted_for_planning_and_world_state_only(camp, capsys):
    _built(camp)
    capsys.readouterr()
    for doc in ("party", "campaign_state"):
        assert main(["synth", doc, "--summaries-dir", "summaries", "--npc-root", "docs/x"]) == 2
        assert f"--npc-root applies to world_state and planning only, not {doc}" in capsys.readouterr().err
    for doc in ("world_state", "planning"):
        main(["synth", doc, "--summaries-dir", "summaries", "--npc-root", "docs/x"])  # refused later, for want of notes
        assert "--npc-root applies" not in capsys.readouterr().err


# ── the one-shot path is gone from the source tree ──────────────────────────

ONE_SHOT_PROMPTS = ("party.system.md", "planning.system.md", "world_state.system.md", "campaign_state.system.md")
ONE_SHOT_NAMES = {
    "synth": {"split_parts", "check_threat_tracker", "_previous_draft_run"},
    "context": {"build_context", "party_config_block", "planning_config_block", "load_system_prompt",
                "_outline_instruction", "DocConfig", "AUDIT_LABEL"},
    "schema": {"DEFAULT_PARTS", "STATE_PARTS_REFUSAL"},
}


def test_the_one_shot_prompt_files_are_gone():
    prompts = Path(schema.__file__).parent / "prompts"
    assert [n for n in ONE_SHOT_PROMPTS if (prompts / n).exists()] == []
    # the outlines stay: the chunked build checks each document against its outline
    for doc in schema.DOCS:
        assert (prompts / f"{doc}.outline.yaml").is_file()


@pytest.mark.parametrize("module", sorted(ONE_SHOT_NAMES))
def test_the_one_shot_functions_and_constants_are_gone(module):
    import ast

    path = Path(schema.__file__).parent / f"{module}.py"
    defined = {
        n.name for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(n, (ast.FunctionDef, ast.ClassDef))
    } | {
        t.id for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
    }
    assert defined & ONE_SHOT_NAMES[module] == set()


def test_no_source_names_a_retired_prompt_file():
    root = Path(schema.__file__).parent
    offenders = [
        p.name for p in root.glob("*.py")
        if any(re.search(rf"(?<![\w.]){re.escape(n)}", p.read_text(encoding="utf-8")) for n in ONE_SHOT_PROMPTS)  # state.party.system.md is fine
    ]
    assert offenders == []
