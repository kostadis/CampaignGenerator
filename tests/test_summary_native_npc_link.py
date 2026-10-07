"""``summary_native npc-link``: items, linking, evidence files and refusals (spec 032 T012)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil

import yaml

from pipelines.summary_native import npc_link, parse
from tests.conftest_npc import NPC_FIXTURE, SINCE, UNTIL, npc_campaign, run_cli, sha_tree

WARNING = (
    "warning: 2 ambiguous, 1 generic (unruled) name forms withheld from linking — "
    "see docs/npcs/summary_native/ch002-006/link_report.md"
)


def _args(root, cmd="npc-link", *extra):
    return [
        cmd, "--config", str(root / "config/config.yaml"),
        "--summaries-dir", str(root / "docs/summaries"),
        "--since", str(SINCE), "--until", str(UNTIL), *extra,
    ]


def _link(root, *extra):
    return run_cli(_args(root, "npc-link", *extra))


def _out(root):
    return root / "docs/npcs/summary_native/ch002-006"


def _evidence(root, stem):
    return (_out(root) / "evidence" / f"{stem}.md").read_text(encoding="utf-8")


def _front(text):
    return yaml.safe_load(text.split("---\n")[1])


def _linked(tmp_path):
    root = npc_campaign(tmp_path)
    rc, out, err = _link(root)
    assert rc == 0, err
    return root


# ── iter_items ──────────────────────────────────────────────────────────────

SUMMARY = """# Chapter 9

## Scenes

### 009.01 First

Jimjar waits.

#### Synopsis.

### 009.02 Second

Nobody here.

## Memorable Moments

*An orphan italic paragraph before any moment.*

> "One."
> — A
> *Context one.*

**Bold two.**

*Context two.*

An unquoted tail paragraph belonging to moment two.

- List three
- List four

*Context four.*

> "Five."


## NPCs

### Jimjar

x
"""


def _mom(text):
    pf = parse.parse_text(text, "docs/summaries/009-x.md")
    return [i for i in npc_link.iter_items(pf) if i.kind == "moment"]


def test_iter_items_cuts_scenes_then_moments_with_file_lines():
    pf = parse.parse_text(SUMMARY, "docs/summaries/009-x.md")
    items = npc_link.iter_items(pf)
    assert [i.kind for i in items] == ["scene", "scene"] + ["moment"] * 6
    s1 = items[0]
    assert (s1.scene_id, s1.title, s1.line, s1.chapter) == ("009.01", "First", 5, 9)
    assert s1.text == "Jimjar waits.\n\n#### Synopsis."
    assert s1.lines[0] == (5, "009.01 First")           # the heading line is searched too
    assert (7, "Jimjar waits.") in s1.lines


def test_moment_shapes_context_and_orphans():
    items = _mom(SUMMARY)
    assert [i.text.split("\n")[0] for i in items] == [
        "*An orphan italic paragraph before any moment.*",   # its own item
        '> "One."', "**Bold two.**", "- List three", "- List four", '> "Five."',
    ]
    assert items[1].text == '> "One."\n> — A\n> *Context one.*'
    # italic context and loose prose attach to the bold moment before them
    assert items[2].text == "**Bold two.**\n\n*Context two.*\n\nAn unquoted tail paragraph belonging to moment two."
    assert items[3].text == "- List three"                  # each `- ` item starts its own moment
    assert items[4].text == "- List four\n\n*Context four.*"
    assert items[5].text == '> "Five."'                     # trailing blank lines trimmed
    assert all(i.scene_id is None for i in items)
    lines = SUMMARY.split("\n")
    for it in items:                                        # `line` is the first line, 1-based
        assert lines[it.line - 1] == it.text.split("\n")[0]


def test_bold_moment_with_italic_context():
    (m,) = _mom("# Chapter 9\n\n## Memorable Moments\n\n**Werz hands over gems.**\n\n*Jimjar identifies them.*\n")
    assert m.text == "**Werz hands over gems.**\n\n*Jimjar identifies them.*"
    assert m.line == 5 and m.lines[-1] == (7, "*Jimjar identifies them.*")


def test_section_that_starts_with_a_bold_moment():
    items = _mom("# Chapter 9\n\n## Memorable Moments\n**First.**\n\n**Second.**\n")
    assert [i.text for i in items] == ["**First.**", "**Second.**"]


def test_quote_followed_by_a_bold_moment_are_two_items():
    items = _mom('# Chapter 9\n\n## Memorable Moments\n\n> "Grinta speaks."\n> — Grinta\n\n**Jimjar names the gems.**\n')
    assert len(items) == 2
    forms = ("Jimjar",)
    assert not any(f in items[0].text for f in forms) and "Jimjar" in items[1].text


def test_orphan_paragraphs_before_the_first_start_are_separate_items():
    items = _mom("# Chapter 9\n\n## Memorable Moments\n\n*one*\n\n*two*\n\n> q\n\n*ctx*\n")
    assert [i.text for i in items] == ["*one*", "*two*", "> q\n\n*ctx*"]


def test_a_context_paragraph_naming_the_npc_links_the_moment(tmp_path):
    root = _linked(tmp_path)
    assert "Eldeth takes the rear." in _evidence(root, "npc_eldeth_feldrun")       # bold moment, named in its own line
    assert "**Eldeth takes the rear.**\n\n*She would not be argued with.*" in _evidence(root, "npc_eldeth_feldrun")
    assert "Eldeth takes the rear" not in _evidence(root, "npc_jimjar")


def test_player_character_is_not_global_but_is_still_linked(tmp_path):
    root = _linked(tmp_path)
    thorin = _front(_evidence(root, "npc_thorin"))
    assert (thorin["global"], thorin["exclusion"]) == (False, "player character (players.yaml)")
    assert thorin["n_entries"] == 1                       # still linked (FR-012a)
    assert _front(_evidence(root, "npc_jimjar"))["global"] is True


def test_unresolved_plays_name_is_a_finding(tmp_path):
    root = _linked(tmp_path)
    rep = json.loads((_out(root) / "link_report.json").read_text())
    (f,) = [f for f in rep["findings"] if f["code"] == "player-character-unresolved"]
    assert f["subject"] == "Nobody Known" and f["player"] == "Joe"
    assert "Nobody Known" in (_out(root) / "link_report.md").read_text()


def test_no_players_yaml_excludes_nobody_and_does_not_refuse(tmp_path):
    root = npc_campaign(tmp_path)
    (root / "config/players.yaml").unlink()
    rc, _, err = _link(root)
    assert rc == 0, err
    assert _front(_evidence(root, "npc_thorin"))["global"] is True
    rep = json.loads((_out(root) / "link_report.json").read_text())
    assert not [f for f in rep["findings"] if f["code"] == "player-character-unresolved"]


def test_file_without_moments_section_yields_scenes_only():
    pf = parse.parse_text("# Chapter 1\n\n## Scenes\n\n### 001.01 A\n\nx\n", "docs/summaries/001-a.md")
    assert [i.kind for i in npc_link.iter_items(pf)] == ["scene"]


# ── The fixture, end to end ─────────────────────────────────────────────────


def test_whole_scene_attached_verbatim_with_mention_lines(tmp_path):
    root = _linked(tmp_path)
    text = _evidence(root, "npc_jimjar")
    src = (root / "docs/summaries/002-the-pens.md").read_text().split("\n")
    scene = "\n".join(src[8:14])   # body lines 9..14 of "### 002.01"
    assert "### Scene 002.01 — Out of the Pens (mentioned)" in text
    assert "- Source: docs/summaries/002-the-pens.md (line 7)\n- Mention lines: 9, 11, 13\n" in text
    assert scene.strip("\n") in text                       # verbatim, incl. the H4 synopsis and the bullet
    assert "Eldeth watched the rear" in text               # who else was there is kept (FR-004)
    assert "(mentioned)" in text and "(present)" not in text and "present" not in text.split("---\n", 2)[2]


def test_moment_block_and_scene_none(tmp_path):
    root = _linked(tmp_path)
    text = _evidence(root, "npc_jimjar")
    block = (
        '### Moment (mentioned)\n- Source: docs/summaries/002-the-pens.md (line 25)\n- Scene: none\n'
        '- Mention lines: 26\n\n'
        '> "Keep your voices down, the walls listen."\n> — Jimjar\n'
        '> *Whispered at the mouth of the tunnel, with a glance back toward the pens.*\n'
    )
    assert block in text
    assert "We share the water" not in text                # the next moment is a different item


def test_ordering_chapter_then_entry_then_scenes_then_moments(tmp_path):
    root = _linked(tmp_path)
    text = _evidence(root, "npc_jimjar")
    heads = re.findall(r"^(## Chapter \d+|### (?:Entry|Scene|Moment)[^\n]*)$", text, re.M)
    assert heads == [
        "## Chapter 002", "### Entry — Jimjar", "### Scene 002.01 — Out of the Pens (mentioned)", "### Moment (mentioned)",
        "## Chapter 003", "### Entry — Jimjar", "### Scene 003.01 — Down the Stair (mentioned)",
        "## Chapter 004", "### Scene 004.01 — Market Day (mentioned)", "### Moment (mentioned)",
        "## Chapter 006", "### Entry — Jimjar", "### Scene 006.02 — The Last Camp (mentioned)",
    ]


def test_case_sensitive_word_boundary_matching(tmp_path):
    root = _linked(tmp_path)
    text = _evidence(root, "npc_jimjar")
    assert "Jimjar's brother kept a stall" in text         # the possessive links (004.01)
    assert "A joke at Jimjar's expense" in text            # ... and in the 004 moment
    assert "Jimjarr" not in text and "jimjar was here" not in text
    assert "005" not in "".join(re.findall(r"## Chapter \d+", text))
    assert _front(text)["chapters"] == [2, 3, 4, 6]


def test_mention_only_chapters_count_toward_chapters_and_last_seen(tmp_path):
    root = _linked(tmp_path)
    jim = _front(_evidence(root, "npc_jimjar"))
    assert 4 in jim["chapters"] and jim["n_entries"] == 3 and jim["n_scenes"] == 4 and jim["n_moments"] == 2
    assert (jim["first_seen"], jim["last_seen"], jim["range"]) == (2, 6, "2-6")
    sar = _front(_evidence(root, "npc_sarith_kzekarit"))   # entry only in ch 2; named in a ch 6 scene
    assert sar["n_entries"] == 1 and sar["chapters"] == [2, 6] and sar["last_seen"] == 6
    assert sar["aliases_used"] == ["Sarith Kzekarit"]


def test_ambiguous_form_is_withheld_but_full_names_link(tmp_path):
    root = _linked(tmp_path)
    sar = _evidence(root, "npc_sarith_kzekarit")
    assert "Daylight" in sar                               # 006.01 names "Sarith Kzekarit"
    assert "Sarith's patrol" not in sar and "Sarith was spoken" not in sar
    rep = json.loads((_out(root) / "link_report.json").read_text())
    amb = {f["form"]: f for f in rep["findings"] if f["code"] == "ambiguous-form"}
    assert set(amb) == {"Sarith", "Mantol"}
    assert amb["Sarith"]["collides_with"] == [
        {"type": "location", "canonical": "Sarith"}, {"type": "npc", "canonical": "Sarith Kzekarit"},
    ]
    assert "docs/summaries/003-the-descent.md:9" in amb["Sarith"]["locations"]
    assert "docs/summaries/004-the-market.md:17" in amb["Sarith"]["locations"]
    assert not any("006-the-surface" in loc for loc in amb["Sarith"]["locations"])


def test_every_npc_dossier_is_linked_global_or_not(tmp_path):
    root = _linked(tmp_path)
    stems = {p.stem for p in (_out(root) / "evidence").glob("*.md")}
    built = {p.stem for p in (root / "docs/summary_native/ch002-006/dossiers").glob("npc_*.md")}
    assert stems == built and {"npc_kaelis", "npc_quaggoth", "npc_spider"} <= stems     # FR-012a
    assert not any(p.name.startswith(("location_", "item_")) for p in (_out(root) / "evidence").iterdir())


def test_global_and_exclusion_frontmatter(tmp_path):
    root = _linked(tmp_path)
    jim, kae, qua = (_front(_evidence(root, s)) for s in ("npc_jimjar", "npc_kaelis", "npc_quaggoth"))
    assert (jim["global"], jim["exclusion"]) == (True, None)
    assert (kae["global"], kae["exclusion"]) == (False, "registry scope chapter-3: local (deferred to the local-NPC feature)")
    assert (qua["global"], qua["exclusion"]) == (False, "not in registry")
    assert jim["source_kind"] == "summary_native_npc_link" and jim["type"] == "npc"


def test_no_dossier_for_a_registry_name_without_a_heading(tmp_path):
    root = npc_campaign(tmp_path)
    reg = root / "docs/entity_registry.yaml"
    reg.write_text(reg.read_text() + "  - name: Brannoc\n    type: npc\n")
    s6 = root / "docs/summaries/006-the-surface.md"
    s6.write_text(s6.read_text().replace("Jimjar kept the first watch.", "Jimjar kept the first watch; Brannoc nodded."))
    rc, _, err = run_cli(_args(root, "build", "--force"))
    assert rc == 0, err
    rc, out, err = _link(root)
    assert rc == 0, err
    assert not (_out(root) / "evidence/npc_brannoc.md").exists()
    rep = json.loads((_out(root) / "link_report.json").read_text())
    (f,) = [f for f in rep["findings"] if f["code"] == "mention-without-heading"]
    assert f["subject"] == "Brannoc" and f["locations"] == ["docs/summaries/006-the-surface.md:17"]
    assert "Brannoc" in (_out(root) / "link_report.md").read_text()
    # and the line that names him still links Jimjar's scene (a different form, a different NPC)
    assert "006.02" in _evidence(root, "npc_jimjar")


def test_run_end_warning_text_and_summary(tmp_path):
    root = npc_campaign(tmp_path)
    rc, out, err = _link(root)
    assert rc == 0
    assert err.strip() == WARNING
    assert "NPCs linked: 9" in out and "scenes linked: 9" in out and "moments linked: 5" in out
    assert "2 ambiguous, 1 generic (unruled)" in out


def test_generic_ruling_safe_links_and_never_stays_withheld(tmp_path):
    root = npc_campaign(tmp_path)
    canon = root / "docs/summary_native/canon.yaml"
    canon.write_text("link_rulings:\n  - {form: Spider, ruling: safe}\n")
    rc, out, err = _link(root)
    assert rc == 0 and "1 ambiguous" not in err and "2 ambiguous, 0 generic" in err
    spider = _front(_evidence(root, "npc_spider"))
    assert spider["n_scenes"] == 2 and spider["chapters"] == [3, 4]      # 003.02, and 004.01 via "Spider-silk"

    canon.write_text("link_rulings:\n  - {form: Spider, ruling: never}\n")
    rc, out, err = _link(root, "--force")
    assert rc == 0 and "2 ambiguous, 0 generic (unruled)" in err
    assert _front(_evidence(root, "npc_spider"))["n_scenes"] == 0
    rep = json.loads((_out(root) / "link_report.json").read_text())
    (g,) = [f for f in rep["findings"] if f["code"] == "generic-form"]
    assert g["form"] == "Spider" and g["ruling"] == "never"


def test_link_manifest_digests(tmp_path):
    root = _linked(tmp_path)
    m = json.loads((_out(root) / "link_manifest.json").read_text())
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    assert m["kind"] == "npc_link" and m["range"] == {"since": 2, "until": 6}
    assert m["corpus_manifest_sha256"] == sha(root / "docs/summary_native/ch002-006/manifest.json")
    assert m["registry_sha256"] == sha(root / "docs/entity_registry.yaml")
    assert m["canon_sha256"] is None                       # no canon.yaml in the fixture
    from pipelines.summary_native import npc_forms
    assert m["wordlist_sha256"] == npc_forms.load_wordlist()[1]
    assert set(m["evidence"]) == {p.stem for p in (_out(root) / "evidence").glob("*.md")}
    for stem, digest in m["evidence"].items():
        assert digest == sha(_out(root) / "evidence" / f"{stem}.md")


def test_canon_digest_recorded_when_present(tmp_path):
    root = npc_campaign(tmp_path)
    canon = root / "docs/summary_native/canon.yaml"
    canon.write_text("link_rulings:\n  - {form: Spider, ruling: safe}\n")
    _link(root)
    m = json.loads((_out(root) / "link_manifest.json").read_text())
    assert m["canon_sha256"] == hashlib.sha256(canon.read_bytes()).hexdigest()


def test_output_is_byte_identical_across_runs(tmp_path):
    root = _linked(tmp_path)
    first = sha_tree(_out(root))
    assert {"link_manifest.json", "link_report.md", "link_report.json"} <= set(first)
    rc, _, err = _link(root, "--force")
    assert rc == 0
    assert sha_tree(_out(root)) == first
    # and a second campaign built independently produces the same bytes
    other = npc_campaign(tmp_path / "again")
    _link(other)
    assert sha_tree(_out(other)) == first


def test_the_031_corpus_is_unchanged(tmp_path):
    root = npc_campaign(tmp_path)
    before = sha_tree(root / "docs/summary_native")
    assert _link(root)[0] == 0 and _link(root, "--force")[0] == 0
    assert sha_tree(root / "docs/summary_native") == before


# ── Refusals ────────────────────────────────────────────────────────────────


def test_refuses_without_a_built_corpus(tmp_path):
    root = tmp_path / "camp"
    shutil.copytree(NPC_FIXTURE, root, ignore=shutil.ignore_patterns("README.md"))
    rc, out, err = _link(root)
    assert rc == 2 and "summary_native build" in err
    assert not (root / "docs/npcs").exists()


def test_refuses_a_stale_corpus(tmp_path):
    root = npc_campaign(tmp_path)
    p = root / "docs/summaries/006-the-surface.md"
    p.write_text(p.read_text().replace("Jimjar kept", "Jimjar keeps"))
    rc, out, err = _link(root)
    assert rc == 2 and "build --force" in err
    assert not (root / "docs/npcs").exists()


def test_refuses_a_stale_registry(tmp_path):
    root = npc_campaign(tmp_path)
    reg = root / "docs/entity_registry.yaml"
    reg.write_text(reg.read_text() + "  - name: Brannoc\n    type: npc\n")
    rc, out, err = _link(root)
    assert rc == 2 and "registry changed" in err


def test_refuses_an_ambiguous_form_ruling_and_writes_nothing(tmp_path):
    root = npc_campaign(tmp_path)
    (root / "docs/summary_native/canon.yaml").write_text("link_rulings:\n  - {form: Mantol, ruling: never}\n")
    rc, out, err = _link(root)
    assert rc == 2 and "'Mantol'" in err and "Mantol-Derith" in err
    assert not (root / "docs/npcs").exists()


def test_refuses_a_malformed_canon(tmp_path):
    root = npc_campaign(tmp_path)
    (root / "docs/summary_native/canon.yaml").write_text("link_rulings:\n  - {form: Spider, ruling: maybe}\n")
    rc, out, err = _link(root)
    assert rc == 2 and "maybe" in err


def test_refuses_existing_output_without_force(tmp_path):
    root = _linked(tmp_path)
    before = sha_tree(_out(root))
    rc, out, err = _link(root)
    assert rc == 2 and "--force" in err
    assert sha_tree(_out(root)) == before


def test_blocking_validation_exits_1(tmp_path):
    root = npc_campaign(tmp_path)
    p = root / "docs/summaries/002-the-pens.md"
    p.write_text(p.read_text().replace("### 002.02", "### 003.02"))
    rc, out, err = _link(root)
    assert rc == 1 and "blocking" in err
    assert not (root / "docs/npcs").exists()


def test_force_removes_evidence_for_an_npc_that_left_the_corpus(tmp_path):
    root = _linked(tmp_path)
    ghost = _out(root) / "evidence" / "npc_ghost.md"
    ghost.write_text("old")
    assert _link(root, "--force")[0] == 0
    assert not ghost.exists()


def test_npc_root_flag_and_config_precedence(tmp_path):
    root = npc_campaign(tmp_path)
    (root / "config/npc_dossiers.yaml").write_text("npc_root: out/from-config\n")
    assert _link(root)[0] == 0
    assert (root / "out/from-config/ch002-006/link_manifest.json").is_file()
    assert _link(root, "--npc-root", "out/from-flag")[0] == 0
    assert (root / "out/from-flag/ch002-006/link_manifest.json").is_file()
    assert not (root / "docs/npcs").exists()
