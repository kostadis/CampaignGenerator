"""Name forms, ambiguity, generic words and link rulings (spec 032 T011, research R2/R4/R5)."""

from __future__ import annotations

import hashlib
import json

import pytest

from campaignlib.registry import load_registry
from pipelines.summary_native import duplicates, npc_forms, schema
from pipelines.summary_native.npc_forms import (
    AMBIGUOUS, GENERIC, GENERIC_NEVER, GENERIC_SAFE, LINKABLE, CorpusDossier, LinkRefusal,
    build_form_index, load_wordlist,
)
from tests.conftest_npc import SINCE, UNTIL, npc_campaign, run_cli

WORDS, WORDS_SHA = load_wordlist()


def _index(root, rulings=None):
    reg = load_registry(root / "docs" / "entity_registry.yaml")
    dossiers = npc_forms.read_corpus_dossiers(root / "docs" / "summary_native" / f"ch{SINCE:03d}-{UNTIL:03d}")
    return build_form_index(reg, dossiers, WORDS, rulings or {})


def _texts(forms):
    return sorted(f.text for f in forms)


def test_wordlist_loads_and_records_its_digest():
    assert "spider" in WORDS and "jimjar" not in WORDS
    assert all(w == w.lower() for w in WORDS)
    assert WORDS_SHA == hashlib.sha256(npc_forms.WORDLIST_PATH.read_bytes()).hexdigest()


def test_forms_are_headings_plus_exact_registry_npc_strings(tmp_path):
    idx = _index(npc_campaign(tmp_path))
    assert _texts(idx.forms_for("npc_eldeth_feldrun")) == ["Eldeth", "Eldeth Feldrun"]
    assert _texts(idx.forms_for("npc_jimjar")) == ["Jimjar"]
    # a heading-only NPC (no registry entry) is still a form owner
    assert _texts(idx.forms_for("npc_quaggoth")) == ["Quaggoth"]
    f = idx.forms["Eldeth"]  # a registry alias no heading uses
    assert f.owner == ("npc", "Eldeth Feldrun") and f.sources == ("registry",) and f.status == LINKABLE
    assert idx.forms["Eldeth Feldrun"].sources == ("heading", "registry")


def test_no_inferred_first_token_alias(tmp_path):
    idx = _index(npc_campaign(tmp_path))
    # "Feldrun" and "Kzekarit" are tokens of a name, not declared forms.
    assert "Feldrun" not in idx.forms and "Kzekarit" not in idx.forms
    assert "Vale" not in idx.forms


def test_registry_alias_of_another_type_is_not_an_npc_form(tmp_path):
    idx = _index(npc_campaign(tmp_path))
    assert "Mantol-Derith" not in idx.forms
    # but it collides with the NPC heading "Mantol": the cross-type location alias case
    f = idx.forms["Mantol"]
    assert f.status == AMBIGUOUS and f.owner is None
    assert f.collides_with == (("location", "Mantol-Derith"), ("npc", "Mantol"))


def test_shared_first_name_is_ambiguous_across_types(tmp_path):
    idx = _index(npc_campaign(tmp_path))
    f = idx.forms["Sarith"]
    assert f.status == AMBIGUOUS
    assert f.collides_with == (("location", "Sarith"), ("npc", "Sarith Kzekarit"))
    # the full names still link
    assert idx.forms["Sarith Kzekarit"].status == LINKABLE and idx.forms["Sarith Vale"].status == LINKABLE


def test_generic_single_token_in_word_list(tmp_path):
    idx = _index(npc_campaign(tmp_path))
    assert idx.forms["Spider"].status == GENERIC
    assert idx.forms["Kaelis"].status == LINKABLE
    assert "Spider" in _texts(idx.withheld()) and "Jimjar" not in _texts(idx.withheld())


def test_multiword_form_is_never_generic():
    d = CorpusDossier("npc_x", "npc", "Stone Giant", ("Stone Giant", "Stone"))
    idx = build_form_index(None, [d], WORDS, {})
    assert idx.forms["Stone Giant"].status == LINKABLE and idx.forms["Stone"].status == GENERIC


def test_link_ruling_safe_makes_generic_linkable_never_keeps_it_withheld(tmp_path):
    root = npc_campaign(tmp_path)
    safe = _index(root, {"Spider": "safe"})
    assert safe.forms["Spider"].status == GENERIC_SAFE
    assert [f.text for f in safe.linkable_for("npc_spider")] == ["Spider"]
    assert "Spider" not in _texts(safe.withheld())
    never = _index(root, {"Spider": "never"})
    assert never.forms["Spider"].status == GENERIC_NEVER
    assert never.linkable_for("npc_spider") == ()
    assert "Spider" in _texts(never.withheld())


def test_ruling_on_an_ambiguous_form_refuses_naming_the_collisions(tmp_path):
    root = npc_campaign(tmp_path)
    with pytest.raises(LinkRefusal) as e:
        _index(root, {"Sarith": "safe"})
    msg = str(e.value)
    assert "'Sarith'" in msg and "location 'Sarith'" in msg and "npc 'Sarith Kzekarit'" in msg


def test_ambiguous_beats_generic():
    dossiers = [
        CorpusDossier("npc_a", "npc", "Spider", ("Spider",)),
        CorpusDossier("location_spider", "location", "Spider", ("Spider",)),
    ]
    idx = build_form_index(None, dossiers, WORDS, {})
    assert idx.forms["Spider"].status == AMBIGUOUS
    # and so a ruling on it is a refusal, not a generic ruling
    with pytest.raises(LinkRefusal):
        build_form_index(None, dossiers, WORDS, {"Spider": "never"})


def test_ruling_findings_stale_and_unneeded(tmp_path):
    root = npc_campaign(tmp_path)
    idx = _index(root, {"Spider": "safe", "Jimjar": "never", "Nowhere": "safe"})
    found = idx.ruling_findings({"Spider", "Jimjar"})
    got = {(f["code"], f["form"]) for f in found}
    assert (schema.STALE_LINK_RULING, "Nowhere") in got
    assert (schema.LINK_RULING_UNNEEDED, "Jimjar") in got       # linkable, not generic
    assert (schema.LINK_RULING_UNNEEDED, "Nowhere") in got      # not a form at all
    assert (schema.LINK_RULING_UNNEEDED, "Spider") not in got   # generic: the ruling is needed
    assert (schema.STALE_LINK_RULING, "Spider") not in got
    assert idx.ruling_findings({"Spider", "Jimjar"}) == found


def test_global_status_follows_registry_scope(tmp_path):
    idx = _index(npc_campaign(tmp_path))
    assert idx.global_status("Jimjar") == (True, None)
    assert idx.global_status("Kaelis") == (False, "registry scope chapter-3: local (deferred to the local-NPC feature)")
    assert idx.global_status("Quaggoth") == (False, "not in registry")


def test_matching_is_case_sensitive_on_word_boundaries(tmp_path):
    idx = _index(npc_campaign(tmp_path))
    hit = lambda s: [m[2].text for m in idx.match_line(s)]  # noqa: E731
    assert hit("Jimjar's brother") == ["Jimjar"]
    assert hit("Jimjarr and jimjar and xJimjar") == []
    assert hit("Eldeth Feldrun spoke") == ["Eldeth Feldrun"]   # longest form wins, one mention
    assert hit("Eldeth spoke") == ["Eldeth"]


def test_forms_come_from_the_registry_and_stems_from_the_built_corpus(tmp_path):
    root = npc_campaign(tmp_path)
    idx = _index(root)
    built = {p.stem for p in (root / "docs/summary_native/ch002-006/dossiers").glob("npc_*.md")}
    assert set(idx.stem_forms) == built


def test_cli_refuses_a_ruling_on_an_ambiguous_form(tmp_path):
    root = npc_campaign(tmp_path)
    (root / "docs/summary_native/canon.yaml").write_text("link_rulings:\n  - {form: Sarith, ruling: safe}\n")
    rc, out, err = run_cli(_link_args(root))
    assert rc == 2 and "Sarith" in err and "ambiguous" in err and "Sarith Kzekarit" in err
    assert not (root / "docs/npcs").exists()


def test_cli_reports_unneeded_and_stale_link_rulings(tmp_path):
    root = npc_campaign(tmp_path)
    (root / "docs/summary_native/canon.yaml").write_text(
        "link_rulings:\n  - {form: Spider, ruling: safe}\n  - {form: Jimjar, ruling: never}\n"
        "  - {form: Nowhere, ruling: safe}\n"
    )
    rc, out, err = run_cli(_link_args(root))
    assert rc == 0, err
    rep = json.loads((root / "docs/npcs/summary_native/ch002-006/link_report.json").read_text())
    got = {(f["code"], f.get("form")) for f in rep["findings"]}
    assert (schema.STALE_LINK_RULING, "Nowhere") in got
    assert (schema.LINK_RULING_UNNEEDED, "Jimjar") in got
    assert (schema.LINK_RULING_UNNEEDED, "Spider") not in got


def _link_args(root, *extra):
    return [
        "npc-link", "--config", str(root / "config/config.yaml"),
        "--summaries-dir", str(root / "docs/summaries"),
        "--since", str(SINCE), "--until", str(UNTIL), *extra,
    ]
