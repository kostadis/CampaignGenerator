"""T009-T011: explicit source ingestion parses only the selection."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipelines.summary_native import corpus, parse, validate
from pipelines.summary_native.delta import plan as dplan
from pipelines.summary_native.delta import sources
from pipelines.summary_native.delta.errors import EXIT_STALE, EXIT_USAGE, DeltaRefusal

FIX = Path(__file__).parent / "fixtures" / "delta" / "campaign"


@pytest.fixture
def camp(tmp_path):
    root = tmp_path / "camp"
    shutil.copytree(FIX, root)
    return root


@pytest.fixture
def sd(camp):
    return camp / "docs" / "summaries"


@pytest.fixture
def parse_calls(monkeypatch):
    calls: list[str] = []
    real = parse.parse_file

    def counting(path, root):
        calls.append(Path(path).name)
        return real(path, root)

    monkeypatch.setattr(parse, "parse_file", counting)
    return calls


def _ch3(sd):
    return sd / "003-the-new-fire.md"


def test_only_selected_chapter_parsed(camp, sd, parse_calls):
    sel = sources.ingest([_ch3(sd)], summaries_dir=sd, campaign_root=camp)
    assert parse_calls == ["003-the-new-fire.md"]
    counts = sel.read_counts
    assert counts["parsed_new"] == 1 and counts["parsed_historical"] == 0
    assert counts["model_input"] == 0 and counts["integrity_only"] == 0
    assert set(counts) == set(sources.ROLES)
    assert sel.report.files_scanned == 1


def test_integrity_reads_counted_separately(camp, sd, parse_calls):
    custody = sd / "001-the-cold-forge.md"
    sel = sources.ingest([_ch3(sd)], summaries_dir=sd, campaign_root=camp, integrity_paths=[custody])
    assert parse_calls == ["003-the-new-fire.md"]
    assert sel.read_counts["integrity_only"] == 1 and sel.read_counts["parsed_historical"] == 0


def test_empty_selection_refused(camp, sd):
    with pytest.raises(DeltaRefusal) as e:
        sources.ingest([], summaries_dir=sd, campaign_root=camp)
    assert e.value.exit_code == EXIT_USAGE and "no sources selected" in e.value.message
    with pytest.raises(validate.EmptySourceSelection, match="no sources selected"):
        validate.scan(sd, camp, None, None, sources=[])


def test_sha_mismatch_is_stale(camp, sd, parse_calls):
    p = dplan.create_plan(
        campaign_identity="c", products=["npc"], stopping_point="plan", source_paths=[_ch3(sd)],
        models={"generation": {"backend": "b", "model": "m"}, "consistency": {"backend": "b", "model": "m"}})
    with _ch3(sd).open("a", encoding="utf-8") as fh:
        fh.write("\nedited\n")
    with pytest.raises(DeltaRefusal) as e:
        sources.ingest(p, summaries_dir=sd, campaign_root=camp)
    assert e.value.exit_code == EXIT_STALE
    assert parse_calls == []


def test_plan_ingest_ok(camp, sd):
    p = dplan.create_plan(
        campaign_identity="c", products=["npc"], stopping_point="plan", source_paths=[_ch3(sd)],
        models={"generation": {"backend": "b", "model": "m"}, "consistency": {"backend": "b", "model": "m"}})
    sel = sources.ingest(p, summaries_dir=sd, campaign_root=camp)
    assert sel.read_counts["parsed_new"] == 1
    assert sel.entries[0].sha256 == p.sources[0].sha256


def test_round_trip(camp, sd, tmp_path):
    sel = sources.ingest([_ch3(sd)], summaries_dir=sd, campaign_root=camp)
    out = sources.save_selection(sel, tmp_path / "x" / "sel.json")
    back = sources.load_selection(out)
    assert back.entries == sel.entries and back.read_counts == sel.read_counts
    assert back.schema_version == sources.SCHEMA_VERSION


def test_build_corpus_with_sources(camp, sd, tmp_path):
    log: list = []
    report = validate.scan(sd, camp, None, None, sources=[_ch3(sd)], parse_log=log)
    assert [p.name for p in log] == ["003-the-new-fire.md"]
    manifest = corpus.build_corpus(sd, camp, report, tmp_path / "out", sources=[_ch3(sd)])
    assert manifest["complete"]
    text = (tmp_path / "out" / "chronology.md").read_text(encoding="utf-8")
    assert "Chapter 003" in text and "Chapter 001" not in text and "Chapter 002" not in text
    with pytest.raises(validate.EmptySourceSelection):
        corpus.build_corpus(sd, camp, report, tmp_path / "out2", sources=[])
    with pytest.raises(corpus.CorpusError):
        corpus.build_corpus(sd, camp, report, tmp_path / "out3", sources=[sd / "001-the-cold-forge.md"])


def test_scan_without_sources_unchanged(camp, sd, parse_calls):
    plain = validate.scan(sd, camp, None, None)
    assert sorted(parse_calls) == sorted(p.name for p in sd.glob("*.md"))
    allsrc = validate.scan(sd, camp, None, None, sources=sorted(sd.glob("*.md")))
    assert plain.to_dict() == allsrc.to_dict()
    assert plain.files_scanned == 3
