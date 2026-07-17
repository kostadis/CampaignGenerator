"""Tests for registry.py's triage-candidates / mark-distinct / mark-rejected
subcommands (Packet 3b).

triage-candidates deterministically diffs proper nouns found in a campaign's
session outputs against the registry and emits a queue JSON of UNKNOWN
surface forms — the human checkpoint before the (separate) interactive
entity-triage skill walks the GM through them. No API calls anywhere here.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from entity_registry import registry  # noqa: E402
from campaignlib.registry import load_registry  # noqa: E402


def _init(tmp_path, campaign="test-campaign") -> Path:
    campaign_dir = tmp_path / campaign
    campaign_dir.mkdir()
    assert registry.main(["init", str(campaign_dir)]) == 0
    return campaign_dir


def _add(campaign_dir, name, type_="npc", aliases=None):
    args = ["add", str(campaign_dir), "--name", name, "--type", type_]
    if aliases:
        args += ["--aliases", *aliases]
    assert registry.main(args) == 0


# ── triage-candidates ────────────────────────────────────────────────────────

def _make_campaign(tmp_path):
    """A tmp campaign with one known entity and an ensemble merged.json fact
    corpus (the canonical registry source), plus a summary file whose surface
    ("Xyzzy") must be IGNORED — summaries are upstream of the ensemble and are
    not scanned when an ensemble exists. Shared fixture for the tests below.

    Subjects are lowercase descriptive phrases (as in real merged.json), so the
    only proper nouns tokenized out of subject+fact text are the capitalized
    names: Ilvara(1, known→dropped), Zalthir(3), Grazzt(1), Orcus(2)."""
    campaign_dir = _init(tmp_path, campaign="out-of-the-abyss")
    _add(campaign_dir, "Ilvara Mizzrym", aliases=["Ilvara"])

    ensemble_dir = campaign_dir / "docs" / "ensemble"
    ensemble_dir.mkdir(parents=True)
    (ensemble_dir / "merged.json").write_text(
        json.dumps([
            {"subject": "the drow priestess", "fact": "Ilvara addressed the drow."},
            {"subject": "a shadow figure", "fact": "Zalthir emerged from the shadows."},
            {"subject": "a shadow figure", "fact": "Zalthir spoke to Zalthir again."},
            {"subject": "a demon lord", "fact": "Grazzt watched from the throne."},
            {"subject": "a demon lord", "fact": "Orcus appeared in the vision."},
            {"subject": "a demon lord", "fact": "Orcus was summoned by the cultists."},
        ]),
        encoding="utf-8",
    )

    # Summaries are upstream of the ensemble and must NOT be scanned when an
    # ensemble is present. "Xyzzy" is the tripwire for that.
    summary_dir = campaign_dir / "summaries" / "20260101"
    summary_dir.mkdir(parents=True)
    (summary_dir / "session-summary.md").write_text(
        "Xyzzy the forgotten haunts the archive.\n",
        encoding="utf-8",
    )
    return campaign_dir


def _append_ensemble_fact(campaign_dir, subject, fact):
    """Append one fact to the campaign's ensemble merged.json corpus."""
    merged = campaign_dir / "docs" / "ensemble" / "merged.json"
    data = json.loads(merged.read_text(encoding="utf-8"))
    data.append({"subject": subject, "fact": fact})
    merged.write_text(json.dumps(data), encoding="utf-8")


def test_triage_candidates_drops_knowns_and_queues_unknowns(tmp_path):
    campaign_dir = _make_campaign(tmp_path)
    out = tmp_path / "queue.json"

    rc = registry.main(["triage-candidates", str(campaign_dir), "--out", str(out)])
    assert rc == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["campaign"] == "out-of-the-abyss"

    surfaces = {c["surface"] for c in payload["candidates"]}
    assert "Ilvara" not in surfaces  # known (registered alias) — dropped
    assert "Xyzzy" not in surfaces   # summary-only surface — ignored (ensemble is source)

    zalthir = next(c for c in payload["candidates"] if c["surface"] == "Zalthir")
    assert zalthir["count"] == 3
    assert zalthir["norm"] == "zalthir"
    assert any("merged.json" in s for s in zalthir["sources"])
    assert zalthir["near_miss"] is None

    grazzt = next(c for c in payload["candidates"] if c["surface"] == "Grazzt")
    assert grazzt["count"] == 1

    orcus = next(c for c in payload["candidates"] if c["surface"] == "Orcus")
    assert orcus["count"] == 2
    assert any("merged.json" in s for s in orcus["sources"])

    # ensemble is the source; summaries are not scanned when one exists
    assert any("merged.json" in g for g in payload["generated_from"])
    assert not any("summaries" in g for g in payload["generated_from"])

    # sorted by count desc then surface: Zalthir(3) before Orcus(2)/Grazzt(1)
    counts = [c["count"] for c in payload["candidates"]]
    assert counts == sorted(counts, reverse=True)


def test_triage_candidates_near_miss_hint(tmp_path):
    campaign_dir = _make_campaign(tmp_path)
    # Add a near-miss typo of the known alias "Ilvara" to the ensemble corpus.
    _append_ensemble_fact(campaign_dir, "a speaker", "Ilvaraa gave a speech. Ilvaraa again.")

    rc = registry.main(["triage-candidates", str(campaign_dir)])
    assert rc == 0
    # captured via stdout — re-run with --out to inspect the JSON directly
    out = tmp_path / "queue.json"
    assert registry.main(["triage-candidates", str(campaign_dir), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))

    ilvaraa = next(c for c in payload["candidates"] if c["surface"] == "Ilvaraa")
    assert ilvaraa["near_miss"] is not None
    assert ilvaraa["near_miss"]["name"] == "Ilvara Mizzrym"
    assert 0.0 < ilvaraa["near_miss"]["ratio"] <= 1.0


def test_triage_candidates_suppresses_near_miss_for_settled_ruling(tmp_path):
    campaign_dir = _make_campaign(tmp_path)
    _append_ensemble_fact(campaign_dir, "a speaker", "Ilvaraa gave a speech. Ilvaraa again.")

    # GM already ruled "Ilvaraa" and "Ilvara" (the alias that would have
    # matched) are DIFFERENT entities — the hint must be suppressed.
    assert registry.main(["mark-distinct", str(campaign_dir), "Ilvaraa", "Ilvara"]) == 0

    out = tmp_path / "queue.json"
    assert registry.main(["triage-candidates", str(campaign_dir), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))

    ilvaraa = next(c for c in payload["candidates"] if c["surface"] == "Ilvaraa")
    assert ilvaraa["near_miss"] is None  # suppressed — settled GM ruling
    # still present in the queue — only the hint is nulled, not the candidate
    assert ilvaraa["count"] == 2


def test_triage_candidates_min_count_filters(tmp_path):
    campaign_dir = _make_campaign(tmp_path)

    rc = registry.main([
        "triage-candidates", str(campaign_dir), "--min-count", "2",
        "--out", str(tmp_path / "q.json"),
    ])
    assert rc == 0
    payload = json.loads((tmp_path / "q.json").read_text(encoding="utf-8"))
    surfaces = {c["surface"] for c in payload["candidates"]}
    assert "Grazzt" not in surfaces  # count 1 < min-count 2
    assert "Zalthir" in surfaces     # count 3 >= 2
    assert "Orcus" in surfaces       # count 2 >= 2


def test_triage_candidates_bible_source(tmp_path):
    campaign_dir = _init(tmp_path)
    bible = tmp_path / "bible.md"
    bible.write_text("Vlaakith rules the githyanki.\n", encoding="utf-8")

    out = tmp_path / "q.json"
    rc = registry.main([
        "triage-candidates", str(campaign_dir), "--bible", str(bible), "--out", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    surfaces = {c["surface"] for c in payload["candidates"]}
    assert "Vlaakith" in surfaces
    assert any(str(bible) in g for g in payload["generated_from"])


def test_triage_candidates_drops_pc_names_from_party_yaml(tmp_path):
    campaign_dir = _make_campaign(tmp_path)
    # A PC named "Grygum" lives in party.yaml, not the registry — the union of
    # known_names + PC names must suppress it (it would otherwise be queued).
    (campaign_dir / "docs" / "party.yaml").write_text(
        "characters:\n  - name: Grygum\n  - name: Zalthir\n",
        encoding="utf-8",
    )
    _append_ensemble_fact(campaign_dir, "a skirmish", "Grazzt fought Grygum near the throne.")

    out = tmp_path / "q.json"
    assert registry.main(["triage-candidates", str(campaign_dir), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    surfaces = {c["surface"] for c in payload["candidates"]}

    assert "Grygum" not in surfaces   # PC name — suppressed via party.yaml union
    assert "Zalthir" not in surfaces  # also a listed PC now — suppressed
    assert "Grazzt" in surfaces        # not a PC, still an unknown candidate


def test_triage_candidates_ignores_summaries_when_ensemble_present(tmp_path):
    # Regression guard: when an ensemble exists, raw summaries (incl. the
    # summaries/old archive) must not be scanned — they are upstream of the
    # ensemble and re-derive noisy/archived entities.
    campaign_dir = _make_campaign(tmp_path)  # ensemble corpus + a summary with "Xyzzy"
    # Also drop an archived scene extraction that would otherwise be swept in.
    old = campaign_dir / "summaries" / "old" / "20260101" / "scene_extractions_new"
    old.mkdir(parents=True)
    (old / "01_archived.md").write_text("Archivius stalks the stacks.\n", encoding="utf-8")

    out = tmp_path / "q.json"
    assert registry.main(["triage-candidates", str(campaign_dir), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    surfaces = {c["surface"] for c in payload["candidates"]}

    assert "Orcus" in surfaces          # ensemble surface — queued
    assert "Xyzzy" not in surfaces      # current summary — ignored
    assert "Archivius" not in surfaces  # summaries/old archive — ignored
    assert not any("summaries" in g for g in payload["generated_from"])


def test_triage_candidates_falls_back_to_summaries_without_ensemble(tmp_path):
    # No docs/ensemble/* at all → legacy fallback scans raw summaries directly.
    campaign_dir = _init(tmp_path, campaign="legacy")
    _add(campaign_dir, "Ilvara Mizzrym", aliases=["Ilvara"])
    summary_dir = campaign_dir / "summaries" / "20260101"
    summary_dir.mkdir(parents=True)
    (summary_dir / "session-summary.md").write_text(
        "Zalthir emerged from the shadows. Grazzt watched from the throne.\n",
        encoding="utf-8",
    )

    out = tmp_path / "q.json"
    assert registry.main(["triage-candidates", str(campaign_dir), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    surfaces = {c["surface"] for c in payload["candidates"]}

    assert "Zalthir" in surfaces
    assert "Grazzt" in surfaces
    assert any("session-summary.md" in g for g in payload["generated_from"])


def test_triage_candidates_missing_registry_errors(tmp_path):
    campaign_dir = tmp_path / "no-registry"
    campaign_dir.mkdir()
    rc = registry.main(["triage-candidates", str(campaign_dir)])
    assert rc == 1


def test_triage_candidates_no_sources_is_empty_queue(tmp_path):
    campaign_dir = _init(tmp_path)
    out = tmp_path / "q.json"
    rc = registry.main(["triage-candidates", str(campaign_dir), "--out", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["candidates"] == []
    assert payload["generated_from"] == []


# ── mark-distinct / mark-rejected ───────────────────────────────────────────

def test_mark_distinct_writes_and_reloads(tmp_path):
    campaign_dir = _init(tmp_path)
    _add(campaign_dir, "Topsy")
    _add(campaign_dir, "Turvy")

    rc = registry.main(["mark-distinct", str(campaign_dir), "Topsy", "Turvy"])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert any(
        {n.lower() for n in pair} == {"topsy", "turvy"} for pair in reg.distinct
    )


def test_mark_distinct_same_entity_raises_and_leaves_file_unchanged(tmp_path):
    campaign_dir = _init(tmp_path)
    _add(campaign_dir, "Ilvara Mizzrym", aliases=["Ilvara"])

    path = campaign_dir / "docs" / "entity_registry.yaml"
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        registry.main(["mark-distinct", str(campaign_dir), "Ilvara Mizzrym", "Ilvara"])

    after = path.read_text(encoding="utf-8")
    assert before == after


def test_mark_rejected_writes_and_reloads(tmp_path):
    campaign_dir = _init(tmp_path)
    _add(campaign_dir, "Shoor")
    _add(campaign_dir, "Stool")

    rc = registry.main(["mark-rejected", str(campaign_dir), "Shoor", "Stool"])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert any(
        {n.lower() for n in group} == {"shoor", "stool"} for group in reg.rejected_aliases
    )


def test_mark_rejected_requires_two_names(tmp_path):
    campaign_dir = _init(tmp_path)
    rc = registry.main(["mark-rejected", str(campaign_dir), "OnlyOne"])
    assert rc == 1
