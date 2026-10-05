"""CLI tests for summary_native validate/build (T012): exit codes and writes."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

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
                       "--max-tokens", "5", "--parts", "2", "--name", "A", "B", "--audit", "a", "b"])
    assert (ns.backend, ns.endpoint, ns.model, ns.max_tokens, ns.parts) == ("dgx", "http://x", "m", 5, 2)
    assert ns.name == ["A", "B"] and ns.audit == ["a", "b"]
    with pytest.raises(SystemExit):
        p.parse_args(["synth", "bogus"])
    with pytest.raises(SystemExit):
        p.parse_args(["compare", "world_state"])  # --live is required


def test_compare_writes_diff_and_reads_inputs_only(camp, capsys):
    _corpus(camp)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    rd = camp / "docs/summary_native/ch002-005"
    (rd / "drafts").mkdir()
    draft = rd / "drafts/world_state.draft.md"
    draft.write_text("## A\n\nSee ch 7 and Chapter 12.\nnew line\n")
    live = camp / "live.md"
    live.write_text("## A\n\nSee ch 3.\n")
    before = (draft.read_bytes(), live.read_bytes())
    assert main(["compare", "world_state", "--summaries-dir", "summaries", "--live", "live.md"]) == 0
    out = capsys.readouterr().out
    assert "heuristic" in out and "12" in out
    diff = (rd / "drafts/world_state.vs-live.diff").read_text()
    assert "--- a/" in diff and "+++ b/" in diff and "+new line" in diff
    assert (draft.read_bytes(), live.read_bytes()) == before


def test_compare_errors_when_draft_or_live_missing(camp):
    _corpus(camp)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    (camp / "live.md").write_text("x\n")
    assert main(["compare", "world_state", "--summaries-dir", "summaries", "--live", "live.md"]) == 2
    rd = camp / "docs/summary_native/ch002-005"
    (rd / "drafts").mkdir()
    (rd / "drafts/world_state.draft.md").write_text("x\n")
    assert main(["compare", "world_state", "--summaries-dir", "summaries", "--live", "nope.md"]) == 2


def test_synth_incompatible_backend_model_exits_2_without_traceback(camp, capsys):
    _corpus(camp)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    capsys.readouterr()
    rc = main(["synth", "world_state", "--summaries-dir", "summaries", "--dump-only",
               "--backend", "codex-cli", "--model", "claude-opus-5-5"])
    err = capsys.readouterr().err
    assert rc == 2 and "incompatible with backend 'codex-cli'" in err and "Traceback" not in err
