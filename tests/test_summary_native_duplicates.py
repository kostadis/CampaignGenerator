"""Fix-at-source duplicate detection (US3): list, never merge."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from campaignlib.registry import load_registry
from pipelines.summary_native import corpus, duplicates, schema
from pipelines.summary_native.cli import main
from pipelines.summary_native.validate import scan

FIX = Path(__file__).parent / "fixtures" / "summary_native"
CANON_MSG = "canon.yaml records not-a-duplicate rulings only; fix duplicates in the summary files"


@pytest.fixture
def camp(tmp_path, monkeypatch):
    root = tmp_path / "camp"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("paths: {}\n")
    shutil.copytree(FIX / "aliases", root / "summaries")
    (root / "docs").mkdir()
    shutil.copy(FIX / "aliases" / "entity_registry.yaml", root / "docs" / "entity_registry.yaml")
    (root / "summaries" / "entity_registry.yaml").unlink()
    monkeypatch.chdir(root)
    return root


def _report(camp) -> dict:
    return json.loads((camp / "docs/summary_native/ch001-003/validation_report.json").read_text())


def _dups(camp) -> list[dict]:
    return [f for f in _report(camp)["findings"] if f["code"] == "possible-duplicate"]


def _validate(*extra) -> int:
    return main(["validate", "--summaries-dir", "summaries", *extra])


def _write_summary(camp, name, ch, npcs="", items="", spells=""):
    text = (
        f"# Chapter {ch}\n\n## Scenes\n\n### {ch:03d}.01 Move\n\nBody.\n\n"
        f"## NPCs\n\n{npcs}\n## Items\n\n{items}\n## Spells\n\n{spells}"
    )
    (camp / "summaries" / name).write_text(text)


@pytest.fixture
def tiny(camp):
    shutil.rmtree(camp / "summaries")
    (camp / "summaries").mkdir()
    return camp


def _obs(category, heading, grouper=corpus.identity_grouper, file="001-a.md", line=1):
    c, by = grouper(category, heading)
    return corpus.Observation(category, heading, c, tuple(by), 1, file, None, line, "")


def _reg(tmp_path, text):
    p = tmp_path / "r.yaml"
    p.write_text(text)
    return load_registry(p)


def test_registry_exact_same_type_alias_groups_and_keeps_headings():
    reg = load_registry(FIX / "aliases" / "entity_registry.yaml")
    g = duplicates.make_grouper(reg)
    assert g("npc", "Lord Manshoon") == ("Manshoon", ["registry"])
    assert g("npc", "Manshoon") == ("Manshoon", [])
    obs = corpus.build_observations(
        [__import__("pipelines.summary_native.parse", fromlist=["x"]).parse_file(p, FIX) for p in sorted((FIX / "aliases").glob("*.md"))],
        g,
    )
    lm = [o for o in obs if o.heading == "Lord Manshoon"]
    assert lm and lm[0].canonical == "Manshoon" and lm[0].grouped_by == ("registry",)


def test_registry_first_token_inference_not_applied():
    reg = load_registry(FIX / "aliases" / "entity_registry.yaml")
    g = duplicates.make_grouper(reg)
    assert g("npc", "Kazryn") == ("Kazryn", [])


def test_spells_never_registry_grouped(tmp_path):
    reg = _reg(
        tmp_path,
        "version: 1\nentities:\n  - {name: Fireball, type: npc, aliases: [Fire Ball]}\n",
    )
    g = duplicates.make_grouper(reg)
    assert g("spell", "Fire Ball") == ("Fire Ball", [])
    assert g("ability", "Fire Ball") == ("Fire Ball", [])
    assert g("npc", "Fire Ball") == ("Fireball", ["registry"])


def test_registry_type_must_match_category(tmp_path):
    reg = _reg(tmp_path, "version: 1\nentities:\n  - {name: Candlekeep, type: location, aliases: [The Keep]}\n")
    g = duplicates.make_grouper(reg)
    assert g("npc", "The Keep") == ("The Keep", [])
    assert g("location", "The Keep") == ("Candlekeep", ["registry"])


def test_no_cross_category_grouping_or_flag(tiny):
    _write_summary(tiny, "001-a.md", 1, items="### Staff of Power\n\nx\n")
    _write_summary(tiny, "002-b.md", 2, spells="### Staff of Power\n\ny\n")
    assert _validate() == 0
    rep = json.loads((tiny / "docs/summary_native/ch001-002/validation_report.json").read_text())
    assert [f for f in rep["findings"] if f["code"] == "possible-duplicate"] == []


def test_typo_listed_with_all_file_lines_not_merged(camp):
    assert _validate() == 0
    hits = [f for f in _dups(camp) if "Manshon" in f["message"] and "Manshoon" in f["message"]]
    typo = [f for f in hits if "similarity" in f["message"]]
    assert typo, _dups(camp)
    loc = typo[0]["locations"]
    flat = {s: v for s, v in loc.items()}
    assert any(v == ["summaries/003-third.md:30"] or v[0].startswith("summaries/003-third.md:") for v in flat.values())
    assert any("001-first.md" in x for v in flat.values() for x in v)
    assert typo[0]["blocking"] is False and typo[0]["in_range"] is True
    # Nothing merged: build keeps both dossiers.
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    dossiers = sorted(p.name for p in (camp / "docs/summary_native/ch001-003/dossiers").rglob("*.md"))
    assert any("manshon" in n and "manshoon" not in n for n in dossiers)
    assert any("manshoon" in n for n in dossiers)


def test_qualifier_pair_listed(camp):
    _validate()
    q = [f for f in _dups(camp) if "qualifier" in f["message"]]
    assert q and "Manshoon (Simulacrum)" in q[0]["message"]


def test_possible_duplicate_is_non_blocking(camp):
    assert _validate() == 0
    assert _dups(camp)
    assert _report(camp)["blocking_count"] == 0


def test_report_has_duplicates_section_and_threshold(camp, capsys):
    _validate("--dup-threshold", "0.9")
    md = (camp / "docs/summary_native/ch001-003/validation_report.md").read_text()
    assert "## Possible duplicates — fix in the summaries" in md
    assert "0.9" in md.split("## In range")[0]
    assert "summaries/003-third.md:" in md


def test_registry_alias_not_flagged_against_canonical(camp):
    _validate()
    for f in _dups(camp):
        assert not ("Lord Manshoon" in f["message"] and "'Manshoon'" in f["message"] and "similarity" in f["message"])


def test_fixing_source_clears_finding(camp):
    _validate()
    assert _dups(camp)
    p = camp / "summaries" / "003-third.md"
    p.write_text(p.read_text().replace("### Manshon\n", "### Manshoon\n"))
    q = camp / "summaries" / "002-second.md"
    q.write_text(q.read_text().replace("### Manshoon (Simulacrum)", "### Simulacrum Twin"))
    _validate()
    assert not [f for f in _dups(camp) if "Manshon" in f["message"]]


def test_not_duplicates_ruling_suppresses(camp):
    canon = camp / "docs/summary_native/canon.yaml"
    canon.parent.mkdir(parents=True, exist_ok=True)
    canon.write_text('not_duplicates:\n  - {category: npc, a: "Manshon", b: "Manshoon"}\n')
    _validate()
    assert not [f for f in _dups(camp) if "similarity" in f["message"] and "Manshon'" in f["message"]]


def test_ruling_pair_is_unordered_and_casefolded(camp):
    canon = camp / "docs/summary_native/canon.yaml"
    canon.parent.mkdir(parents=True, exist_ok=True)
    canon.write_text('not_duplicates:\n  - {category: npc, a: "MANSHOON", b: "manshon"}\n')
    _validate()
    assert not [f for f in _dups(camp) if "similarity" in f["message"] and "Manshon'" in f["message"]]


def test_registry_distinct_and_rejected_aliases_suppress(camp):
    reg = camp / "docs/entity_registry.yaml"
    base = reg.read_text()
    reg.write_text(base + "distinct:\n  - [Manshon, Manshoon]\n")
    _validate()
    assert not [f for f in _dups(camp) if "similarity" in f["message"] and "Manshon'" in f["message"]]
    reg.write_text(base + "rejected_aliases:\n  - [Manshon, Manshoon]\n")
    _validate()
    assert not [f for f in _dups(camp) if "similarity" in f["message"] and "Manshon'" in f["message"]]


@pytest.mark.parametrize("key", ["accepted", "aliases", "merge"])
def test_canon_yaml_rejects_merge_keys(camp, key, capsys):
    canon = camp / "docs/summary_native/canon.yaml"
    canon.parent.mkdir(parents=True, exist_ok=True)
    canon.write_text(f"{key}:\n  - {{category: npc, a: Manshon, b: Manshoon}}\n")
    for cmd in ("validate", "build"):
        assert main([cmd, "--summaries-dir", "summaries"]) == 2
        assert CANON_MSG in capsys.readouterr().err


def test_canon_yaml_rejects_malformed_entries(tmp_path):
    p = tmp_path / "canon.yaml"
    for body in (
        "not_duplicates: [oops]\n",
        "not_duplicates:\n  - {category: spaceship, a: x, b: y}\n",
        "not_duplicates:\n  - {category: npc, a: x}\n",
        "not_duplicates:\n  - {category: npc, a: x, b: y, extra: 1}\n",
    ):
        p.write_text(body)
        with pytest.raises(duplicates.RulingsError):
            duplicates.load_rulings(p)


def test_absent_canon_is_empty(tmp_path):
    r = duplicates.load_rulings(tmp_path / "nope.yaml")
    assert not r.pairs


def test_stale_ruling_reported(camp):
    canon = camp / "docs/summary_native/canon.yaml"
    canon.parent.mkdir(parents=True, exist_ok=True)
    canon.write_text('not_duplicates:\n  - {category: npc, a: "Ghost One", b: "Manshoon"}\n')
    assert _validate() == 0
    stale = [f for f in _report(camp)["findings"] if f["code"] == "stale-ruling"]
    assert len(stale) == 1 and "Ghost One" in stale[0]["message"] and stale[0]["blocking"] is False


def test_dup_threshold_flag_changes_listing(tiny):
    _write_summary(tiny, "001-a.md", 1, npcs="### Gundren\n\nx\n")
    _write_summary(tiny, "002-b.md", 2, npcs="### Gundrun\n\ny\n")

    def listed(*extra):
        main(["validate", "--summaries-dir", "summaries", *extra])
        rep = json.loads((tiny / "docs/summary_native/ch001-002/validation_report.json").read_text())
        return [f for f in rep["findings"] if f["code"] == "possible-duplicate"]

    assert listed() == []
    assert len(listed("--dup-threshold", "0.8")) == 1


def test_canon_yaml_never_written(camp):
    canon = camp / "docs/summary_native/canon.yaml"
    canon.parent.mkdir(parents=True, exist_ok=True)
    canon.write_text("not_duplicates: []\n")
    os.utime(canon, (1_000_000, 1_000_000))
    before = (canon.read_bytes(), canon.stat().st_mtime_ns)
    _validate()
    main(["build", "--summaries-dir", "summaries"])
    assert (canon.read_bytes(), canon.stat().st_mtime_ns) == before


def test_findings_deterministic(camp):
    _validate()
    a = (camp / "docs/summary_native/ch001-003/validation_report.json").read_text()
    _validate()
    assert a == (camp / "docs/summary_native/ch001-003/validation_report.json").read_text()


def test_build_records_grouped_by_in_frontmatter(camp):
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    texts = [p.read_text() for p in (camp / "docs/summary_native/ch001-003/dossiers").rglob("*.md")]
    assert any("grouped_by" in t and "registry" in t for t in texts)
    assert sum("grouped_by" in t for t in texts) == 1
