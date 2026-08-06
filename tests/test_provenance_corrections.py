"""T020 — the corrections schema, the four consultation states, and D12.

The headline assertion in this file is
``test_a_correction_survives_the_text_it_describes_being_regenerated_away``.
Everything else supports it.

A correction is the GM saying "this generated file has drifted from the table's
truth." The tempting implementation attaches it by finding ``stale_claim`` in
the file. That implementation is already broken on the live corpus: Phandalin's
``docs/world_state.md`` was regenerated between the spec being written and
2026-08-05, and the sentence incident 1 quotes is gone. Text-matching would have
made the correction silently stop applying at the moment the file changed —
which is the exact class of silent degradation this feature exists to kill.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from provenance.corrections import (
    Correction,
    CorrectionRecord,
    CorrectionsError,
    CorrectionsStatus,
    consult,
    load_corrections,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def entry(**overrides) -> dict:
    base = {
        "id": "woodland-manse-empty",
        "applies_to": {"paths": ["docs/world_state.md"], "subjects": ["Woodland Manse"]},
        "stale_claim": "Active; Grannoc performing ritual; NOT visited.",
        "truth": "The Woodland Manse has been empty since Chapter 43.",
        "as_of": "chapter-43",
        "recorded": "2026-08-04",
        "recorded_by": "GM",
    }
    base.update(overrides)
    return base


def record(*entries, campaign: str = "alpha") -> dict:
    return {"version": 1, "campaign": campaign, "corrections": list(entries)}


def write(tmp_path: Path, data, name: str = "corrections.yaml") -> Path:
    path = tmp_path / name
    path.write_text(
        data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    return path


def refuses(tmp_path: Path, data, fragment: str, campaign: str = "alpha") -> str:
    with pytest.raises(CorrectionsError) as excinfo:
        load_corrections(write(tmp_path, data), campaign)
    message = str(excinfo.value)
    assert fragment in message, f"expected {fragment!r} in:\n{message}"
    return message


def stub(name: str, corrections: str | None):
    """A minimal stand-in for a manifest ``Campaign``."""
    return SimpleNamespace(name=name, corrections=corrections)


# ── D12: matching is path-and-subject, never text ────────────────────────────


def test_a_correction_survives_the_text_it_describes_being_regenerated_away():
    """The load-bearing assertion (research D12).

    The excerpt below contains none of ``stale_claim``'s words — it is what
    ``distill`` produced *after* the regeneration that deleted the stale
    sentence. The correction must still attach: the file is still generated, the
    GM has not pruned the entry, and nothing about the regeneration made the
    world_state trustworthy.
    """
    correction = Correction.model_validate(entry())
    regenerated = "The party cleared the Woodland Manse and returned to Phandalin."

    assert correction.stale_claim not in regenerated
    assert correction.matches("docs/world_state.md", query="Woodland Manse",
                              excerpt=regenerated)


def test_stale_claim_alone_never_attaches_a_correction():
    """The symmetric hazard: a correction must not silently *start* applying.

    A paraphrase of ``stale_claim`` appearing in a file the correction was never
    written for is not evidence of anything. Only the GM's declared paths are.
    """
    correction = Correction.model_validate(entry())
    assert not correction.matches(
        "docs/some_other_file.md",
        query="Woodland Manse",
        excerpt=correction.stale_claim,
    )


def test_subjects_gate_within_a_matched_path():
    correction = Correction.model_validate(entry())
    assert correction.matches("docs/world_state.md", query="Woodland Manse")
    assert correction.matches("docs/world_state.md", excerpt="the woodland manse stands")
    assert not correction.matches("docs/world_state.md", query="Grannoc", excerpt="a shrine")


def test_subject_matching_is_case_insensitive():
    correction = Correction.model_validate(entry())
    assert correction.matches("docs/world_state.md", query="WOODLAND MANSE")
    assert correction.matches("docs/world_state.md", query="woodland manse")


def test_empty_subjects_means_the_whole_file():
    correction = Correction.model_validate(
        entry(applies_to={"paths": ["docs/world_state.md"], "subjects": []})
    )
    assert correction.matches("docs/world_state.md", query="anything at all")


def test_path_globs_do_not_cross_directory_separators():
    correction = Correction.model_validate(
        entry(applies_to={"paths": ["docs/*.md"], "subjects": []})
    )
    assert correction.matches("docs/world_state.md")
    assert not correction.matches("docs/npcs/keeper.md")


# ── the four consultation states (FR-005) ────────────────────────────────────


def test_state_1_consulted_with_a_match(alpha, fixture_workspace):
    lookup = consult(alpha, fixture_workspace / alpha.root)
    assert lookup.status is CorrectionsStatus.CONSULTED
    assert [c.id for c in lookup.apply("docs/world_state.md", query="Silver Lantern")] == [
        "silver-lantern-recovered"
    ]


def test_state_2_consulted_with_no_match(alpha, fixture_workspace):
    """"Corrections exist for this campaign, none apply here" is a real answer.

    Collapsing it into state 3 would tell the reader the campaign records no
    corrections at all, which is false and is the more dangerous of the two.
    """
    lookup = consult(alpha, fixture_workspace / alpha.root)
    assert lookup.status is CorrectionsStatus.CONSULTED
    assert lookup.record is not None and lookup.record.corrections
    assert lookup.apply("docs/chapters/chapter_02_the_lantern.md", query="Silver Lantern") == []


def test_state_3_no_record(beta, fixture_workspace):
    lookup = consult(beta, fixture_workspace / beta.root)
    assert lookup.status is CorrectionsStatus.NO_RECORD
    assert lookup.record is None
    assert lookup.reason is None
    assert lookup.apply("docs/world_state.md", query="Silver Lantern") == []


def test_state_4_not_consulted_carries_the_reason(tmp_path):
    write(tmp_path, "version: 1\ncampaigns: [unclosed\n", name="broken.yaml")
    lookup = consult(stub("alpha", "broken.yaml"), tmp_path)
    assert lookup.status is CorrectionsStatus.NOT_CONSULTED
    assert lookup.record is None
    assert lookup.reason and "not valid YAML" in lookup.reason


def test_all_four_states_are_distinguishable(alpha, beta, fixture_workspace, tmp_path):
    """The point of the enum. Two of these states share ``record is None``."""
    write(tmp_path, "not: a: record\n", name="broken.yaml")
    observed = {
        (consult(alpha, fixture_workspace / alpha.root).status,
         bool(consult(alpha, fixture_workspace / alpha.root)
              .apply("docs/world_state.md", query="Silver Lantern"))),
        (consult(alpha, fixture_workspace / alpha.root).status,
         bool(consult(alpha, fixture_workspace / alpha.root)
              .apply("docs/chapters/chapter_02_the_lantern.md", query="Silver Lantern"))),
        (consult(beta, fixture_workspace / beta.root).status, False),
        (consult(stub("alpha", "broken.yaml"), tmp_path).status, False),
    }
    assert len(observed) == 4


def test_an_unreadable_record_does_not_take_down_another_campaign(beta, fixture_workspace,
                                                                  tmp_path):
    """Degrade, do not abort. A malformed *manifest* is fatal; this is not.

    The manifest decides what gets searched at all; a corrections record only
    annotates one campaign's hits.
    """
    write(tmp_path, "version: 1\ncampaign: alpha\ncorrections: [{bad}]\n", name="broken.yaml")
    assert consult(stub("alpha", "broken.yaml"), tmp_path).status is (
        CorrectionsStatus.NOT_CONSULTED
    )
    assert consult(beta, fixture_workspace / beta.root).status is CorrectionsStatus.NO_RECORD


def test_a_missing_declared_file_is_not_consulted(tmp_path):
    lookup = consult(stub("alpha", "docs/corrections.yaml"), tmp_path)
    assert lookup.status is CorrectionsStatus.NOT_CONSULTED
    assert lookup.reason and "no corrections record at" in lookup.reason


# ── verified: false (data-model.md §5) ───────────────────────────────────────


def test_corrections_are_verified_by_default():
    assert Correction.model_validate(entry()).verified is True


def test_an_unverified_correction_loads_and_is_findable(alpha, fixture_workspace):
    """An unreproducible correction is a question, not a fact — but it still ships.

    Dropping it would lose the GM's observation; publishing it as settled would
    assert something unverified. It ships labelled, and ``provenance check``
    reports it so it cannot be quietly forgotten.
    """
    lookup = consult(alpha, fixture_workspace / alpha.root)
    unverified = lookup.record.unverified
    assert [c.id for c in unverified] == ["torvald-death-unconfirmed"]
    assert unverified[0].note, "an unverified entry must carry its evidence"


def test_an_unverified_correction_still_attaches(alpha, fixture_workspace):
    lookup = consult(alpha, fixture_workspace / alpha.root)
    hits = lookup.apply("docs/world_state.md", query="Torvald")
    assert [c.id for c in hits] == ["torvald-death-unconfirmed"]
    assert hits[0].verified is False


# ── schema ───────────────────────────────────────────────────────────────────


def test_the_fixture_record_loads(fixture_workspace):
    loaded = load_corrections(fixture_workspace / "alpha" / "docs" / "corrections.yaml", "alpha")
    assert loaded.campaign == "alpha"
    assert len(loaded.corrections) == 4


def test_an_empty_corrections_list_is_legal(tmp_path):
    """Present-but-empty answers ``consulted``, which is not the same as ``no-record``."""
    loaded = load_corrections(write(tmp_path, record()), "alpha")
    assert loaded.corrections == []


@pytest.mark.parametrize("key", ["applies", "stale", "verified_by"])
def test_an_unrecognised_key_is_a_load_error(tmp_path, key):
    refuses(tmp_path, record(entry(**{key: "x"})), key)


def test_duplicate_ids_are_refused(tmp_path):
    refuses(tmp_path, record(entry(), entry()), "duplicate correction id")


def test_duplicate_yaml_keys_are_refused(tmp_path):
    refuses(tmp_path, "version: 1\ncampaign: alpha\ncampaign: beta\n", "duplicate key")


@pytest.mark.parametrize("version", [0, 2])
def test_unknown_version_is_refused(tmp_path, version):
    data = record()
    data["version"] = version
    refuses(tmp_path, data, "understands version 1")


def test_a_campaign_mismatch_is_refused(tmp_path):
    """Guessing which side is wrong would attach another game's corrections to this one."""
    refuses(tmp_path, record(campaign="beta"), "declares campaign 'beta'", campaign="alpha")


def test_empty_applies_to_paths_is_refused(tmp_path):
    refuses(tmp_path, record(entry(applies_to={"paths": [], "subjects": []})), "non-empty")


@pytest.mark.parametrize("field_name", ["stale_claim", "truth"])
def test_blank_required_prose_is_refused(tmp_path, field_name):
    refuses(tmp_path, record(entry(**{field_name: "   "})), "must be non-empty")


def test_a_blank_id_is_refused(tmp_path):
    refuses(tmp_path, record(entry(id="  ")), "non-empty slug")


def test_recorded_is_a_real_date(tmp_path):
    loaded = load_corrections(write(tmp_path, record(entry())), "alpha")
    assert loaded.corrections[0].recorded == date(2026, 8, 4)


def test_as_of_accepts_a_chapter_or_a_date(tmp_path):
    """``as_of: chapter-43`` and ``as_of: 2026-08-04`` are both legal authorings.

    YAML parses the second into a ``date`` before pydantic sees it; normalising
    to a string keeps both spellings loadable rather than rejecting one on a
    technicality the GM cannot see.
    """
    loaded = load_corrections(
        write(tmp_path, record(entry(id="a"), entry(id="b", as_of="2026-08-04"),
                               entry(id="c", as_of=None))),
        "alpha",
    )
    assert [c.as_of for c in loaded.corrections] == ["chapter-43", "2026-08-04", None]


def test_a_missing_file_is_a_load_error(tmp_path):
    with pytest.raises(CorrectionsError, match="no corrections record at"):
        load_corrections(tmp_path / "nope.yaml", "alpha")


def test_an_empty_file_is_a_load_error(tmp_path):
    refuses(tmp_path, "", "is empty")


def test_a_non_mapping_file_is_a_load_error(tmp_path):
    refuses(tmp_path, "- a\n- b\n", "mapping at the top level")


def test_the_record_model_forbids_extras(tmp_path):
    data = record()
    data["notes"] = "hello"
    refuses(tmp_path, data, "notes")
    assert CorrectionRecord.model_config["extra"] == "forbid"
