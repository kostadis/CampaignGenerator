"""Chunked drafting: chunking, the map check, attribution parsing, stitch, prompts, assembly
(spec 032 T060, research R17). Stub client; no network."""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native import npc_check, npc_chunked, npc_draft, schema, synth
from tests.conftest_npc import REDUCE_BODY, SINCE, UNTIL, kind_of, map_output, npc_campaign, run_cli

OUT = "docs/npcs/summary_native/ch002-006"


# ── chunking ────────────────────────────────────────────────────────────────


def _ch(n, size):
    return npc_check.Chapter(n, f"## Chapter {n:03d}\n" + "x" * (size - 15), ())


def test_chunks_are_whole_chapters_in_order_packed_to_the_limit():
    chs = [_ch(2, 40), _ch(3, 40), _ch(4, 40), _ch(5, 100), _ch(6, 10)]
    chunks = npc_chunked.make_chunks(chs, 100)
    assert [[c.number for c in k] for k in chunks] == [[2, 3], [4], [5], [6]]
    assert all(c in chs for k in chunks for c in k)           # never split or rebuilt


def test_an_oversize_chapter_is_its_own_chunk_and_chunking_is_deterministic():
    chs = [_ch(2, 10), _ch(3, 500), _ch(4, 10)]
    a = npc_chunked.make_chunks(chs, 100)
    assert [[c.number for c in k] for k in a] == [[2], [3], [4]]
    assert a == npc_chunked.make_chunks(chs, 100)
    assert npc_chunked.make_chunks([], 100) == []


def test_make_chunks_takes_any_sequence_with_number_and_text():
    """Spec 033 T006: the state-notes chapters are chunked by the same function."""
    from dataclasses import dataclass

    @dataclass
    class Other:
        number: int
        text: str
        extra: str = "kept"

    chs = (Other(2, "a" * 40), Other(3, "b" * 40), Other(4, "c" * 40))
    chunks = npc_chunked.make_chunks(chs, 100)
    assert [[c.number for c in k] for k in chunks] == [[2, 3], [4]]
    assert chunks[0][0] is chs[0] and chunks[0][0].extra == "kept"
    assert npc_chunked.chunk_range(chunks[0]) == "002-003"
    assert npc_chunked.chunk_text(chunks[1]) == "c" * 40


# ── attribution parsing: the four real lines ────────────────────────────────

LINES = (
    "> “if I gave you a means to escape, would you take it?”\n"
    "> — Jorlan Duskryn [ch 002 / moment]\n"
    "\n"
    "> \"I'll bet five gold.\"\n"
    "— Jimjar [ch 046 / moment]\n"
    "\n"
    "> \"Eldeth is never going to go for him.\" — Buppido [ch 012 / moment]\n"
    "\n"
    "> \"I don’t hear about all the people.\" — Eldeth [ch 034 / 034.07] "
    "\"The only good drow is a dead drow.\" — Eldeth [ch 035 / 035.05]\n"
)


def test_attributions_inside_next_line_same_line_and_two_pairs_on_one_line():
    got = npc_check.quotes_in(LINES.splitlines())
    assert [(q.text, q.attribution) for q in got] == [
        ("“if I gave you a means to escape, would you take it?”", "— Jorlan Duskryn [ch 002 / moment]"),
        ('"I\'ll bet five gold."', "— Jimjar [ch 046 / moment]"),
        ('"Eldeth is never going to go for him."', "— Buppido [ch 012 / moment]"),
        ('"I don’t hear about all the people."', "— Eldeth [ch 034 / 034.07]"),
        ('"The only good drow is a dead drow."', "— Eldeth [ch 035 / 035.05]"),
    ]
    assert [q.speaker for q in got] == ["Jorlan Duskryn", "Jimjar", "Buppido", "Eldeth", "Eldeth"]


def test_placeholder_speakers_are_recognised():
    q = npc_check.quotes_in(['> "x" — Speaker [ch 002 / moment]'])[0]
    assert npc_check.placeholder_speaker(q)
    assert not npc_check.placeholder_speaker(npc_check.quotes_in(LINES.splitlines())[1])


# ── the map check ───────────────────────────────────────────────────────────

CHUNK = """## Chapter 002

### Entry — Jimjar
- Source: x.md (line 1)

A deep gnome who says, "I don't know a way out."

### Scene 002.01 — Out of the Pens (mentioned)
- Source: x.md (line 7)

Jimjar whispered, "Follow me and stay low." The party followed.

### Moment (mentioned)
- Source: x.md (line 25)
- Scene: none

> "Keep your voices down, the walls listen."
> — Jimjar
"""


def _index():
    return npc_check.EvidenceIndex.of(npc_check.split_chapters(CHUNK))


RAW = """## History with the Party
- Guides the party out. [ch 002 / 002.01]
- Has no citation at all.
- Cited outside the chunk. [ch 005 / 005.01]
- Cites a manual edit. [manual 1]
- Cites a missing manual edit. [manual 3]

## Notable Quotes
> "Keep your voices down, the walls listen." — Jimjar [ch 002 / moment]

> "Follow me and stay low." — Jimjar [ch 002 / 002.01]

> "I don’t know a way out." — Jimjar [ch 002 / entry]

> "Keep your voices down, the walls listen." — Jimjar [ch 002 / 002.01]

> "Nobody said this at all." — Jimjar [ch 002 / moment]

> “Follow me and stay low.” — Jimjar [ch 002 / 002.01]

> "Follow me and stay low." — Jimjar [ch 005 / moment]

## Arc-Score Candidates
- Candidate: he guides them. [ch 002 / 002.01]
- Candidate: a bad citation. [ch 009 / 009.01]
- Candidate with no citation.
"""


def test_map_check_keeps_and_drops_with_reasons():
    res = npc_chunked.check_map(RAW, _index(), n_manual=2)
    assert res.history == ["- Guides the party out. [ch 002 / 002.01]", "- Cites a manual edit. [manual 1]"]
    reasons = {(d.section, d.reason.split(" (")[0]) for d in res.drops}
    assert ("history", "uncited") in reasons and ("history", "outside-chunk") in reasons
    assert ("history", "invalid-citation") in reasons                       # [manual 3] with 2 edits
    assert ("quotes", "not-found") in reasons                               # not in the evidence
    assert ("quotes", "citation-mismatch") in reasons                       # in the evidence, not in the cited item
    assert ("quotes", "outside-chunk") in reasons                           # attribution cites ch 005
    assert ("arc", "outside-chunk") in reasons and ("arc", "uncited") in reasons
    assert res.arc == ["- Candidate: he guides them. [ch 002 / 002.01]"]


def test_quotes_may_come_from_a_scene_body_or_an_entry_not_only_a_moment():
    res = npc_chunked.check_map(RAW, _index(), n_manual=2)
    assert len(res.quotes) == 4        # moment, scene, entry, curly-marked scene quote
    assert res.quote_report.by_source == {"moment": 1, "scene": 2, "entry": 1}


def test_curly_versus_straight_marks_are_kept_and_recorded_typography_normalised():
    res = npc_chunked.check_map(RAW, _index(), n_manual=2)
    assert len(res.typography) == 1 and "don\u2019t know" in res.typography[0]
    assert res.counts()["typography_normalised"] == 1


def test_an_apostrophe_difference_alone_is_typography_and_any_other_change_is_not_found():
    chk = npc_check.check_quote('"I don\u2019t know a way out."', "\u2014 J [ch 002 / entry]", _index())
    assert chk.status == "typography-normalised" and chk.source == "entry"
    assert npc_check.check_quote('"I dont know a way out."', "\u2014 J [ch 002 / entry]", _index()).status == "not-found"
    assert npc_check.check_quote('"I don\'t know a way out."', "\u2014 J [ch 002 / entry]", _index()).status == "ok"


def test_every_drop_is_logged_with_text_and_reason():
    res = npc_chunked.check_map(RAW, _index(), n_manual=2)
    md = npc_chunked.render_drops_md("Jimjar", [("002-002", res)])
    for d in res.drops:
        assert d.reason in md and d.text.splitlines()[0] in md
    assert "Has no citation at all." in md and "Nobody said this at all." in md
    assert "kept, typography-normalised" in md


def test_a_quote_without_a_citation_is_a_citation_mismatch():
    chk = npc_check.check_quote('"I don\'t know a way out."', "— Jimjar", _index())
    assert chk.status == "citation-mismatch"


# ── stitch ──────────────────────────────────────────────────────────────────


def _res(history=(), quotes=(), arc=()):
    return npc_chunked.MapResult(history=list(history), quotes=list(quotes), arc=list(arc))


def test_stitch_keeps_chapter_order_and_removes_exact_duplicates_only():
    a = _res(["- B. [ch 004 / 004.01]", "- A. [ch 002 / 002.01]"], ['> "q" — X [ch 004 / moment]'])
    b = _res(["- A. [ch 002 / 002.01]", "- A, reworded. [ch 002 / 002.01]", "- C. [ch 006 / 006.02]"], ['> "q" — X [ch 002 / moment]'])
    out = npc_chunked.stitch([a, b])
    assert out[npc_chunked.HISTORY] == [
        "- A. [ch 002 / 002.01]", "- A, reworded. [ch 002 / 002.01]", "- B. [ch 004 / 004.01]", "- C. [ch 006 / 006.02]",
    ]
    assert [q[-14:] for q in out[npc_chunked.QUOTES]] == ["[ch 002 / moment]"[-14:], "[ch 004 / moment]"[-14:]]


# ── assembly ────────────────────────────────────────────────────────────────


def test_assembly_is_in_outline_order_and_passes_check_outline():
    headings = synth.load_outline("npc_dossier")
    st = {npc_chunked.HISTORY: ["- A. [ch 002 / 002.01]"], npc_chunked.QUOTES: [], npc_chunked.ARC: ["- C. [ch 002 / 002.01]"]}
    text = npc_chunked.assemble(headings, st, REDUCE_BODY)
    assert [ln for ln in text.splitlines() if ln.startswith("## ")] == headings
    assert synth.check_outline(text, headings) == []
    assert schema.NONE_VERIFIED in text                      # empty quotes section is written by code


def test_assembly_omits_a_section_the_reduce_call_left_out():
    headings = synth.load_outline("npc_dossier")
    st = {h: ["- A. [ch 002 / 002.01]"] for h in schema.MAP_SECTIONS}
    text = npc_chunked.assemble(headings, st, REDUCE_BODY.replace("## Relationships\n\n- Travels with Eldeth. [ch 002 / 002.01]\n", ""))
    assert "missing heading: ## Relationships" in synth.check_outline(text, headings)


# ── through the CLI ─────────────────────────────────────────────────────────


def _args(root, cmd, *extra):
    return [
        cmd, "--config", str(root / "config/config.yaml"), "--summaries-dir", str(root / "docs/summaries"),
        "--since", str(SINCE), "--until", str(UNTIL), *extra,
    ]


@pytest.fixture
def linked(tmp_path):
    root = npc_campaign(tmp_path)
    assert run_cli(_args(root, "npc-link"))[0] == 0
    return root


@pytest.fixture
def fake(monkeypatch):
    calls = []
    one = "\n".join(f"{h}\n\n- ok. [ch 002 / 002.01]\n" for h in synth.load_outline("npc_dossier"))
    state = {"map": map_output, "reduce": REDUCE_BODY, "one-shot": one, "fail_at": None}

    def render_part(client, system, user, model, max_tokens):
        calls.append({"kind": kind_of(system), "system": system, "user": user, "model": model})
        if state["fail_at"] is not None and len(calls) == state["fail_at"]:
            raise RuntimeError("boom")
        k = kind_of(system)
        v = state[k] if k in state else REDUCE_BODY
        return v(user) if callable(v) else v

    monkeypatch.setattr(npc_draft, "render_part", render_part)
    monkeypatch.setattr(npc_draft, "client_from_args", lambda a, **k: object())
    return calls, state


def run(root):
    return sorted((root / OUT / "runs").iterdir())[-1]


def test_chunked_is_n_map_calls_plus_one_reduce_and_passes_the_outline_check(linked, fake):
    calls, _ = fake
    rc, so, err = run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--chunk-chars", "1"))
    assert rc == 0, err
    assert [c["kind"] for c in calls] == ["map"] * 4 + ["reduce"]          # Jimjar: chapters 2, 3, 4, 6
    text = (linked / OUT / "draft/npc_jimjar.md").read_text()
    body = text[text.index("## Identity"):]
    assert synth.check_outline(body, synth.load_outline("npc_dossier")) == []
    files = {p.name for p in run(linked).iterdir()}
    assert {"npc_jimjar.map01.system.md", "npc_jimjar.map04.out.md", "npc_jimjar.reduce.user.md",
            "npc_jimjar.reduce.out.md", "npc_jimjar.drops.md", "record.json", "verify.json"} <= files
    rec = json.loads((run(linked) / "record.json").read_text())
    n = rec["npcs"]["npc_jimjar"]
    assert rec["mode"] == "chunked" and rec["chunk_chars"] == 1
    assert [c["chapters"] for c in n["chunked"]["chunks"]] == ["002-002", "003-003", "004-004", "006-006"]
    assert n["chunked"]["reduce"]["secs"] >= 0 and n["verify"]["verdict"] == "pass"


def test_a_seeded_bad_citation_and_scene_dialogue_quote_are_dropped_with_reasons(linked, fake):
    _, state = fake

    def bad(user):
        base = map_output(user)
        return base.replace("## Notable Quotes\n", '## Notable Quotes\n> "Nobody wrote this." — Jimjar [ch 002 / moment]\n\n') \
            .replace("## History with the Party\n", "## History with the Party\n- Bad cite. [ch 002 / 002.77]\n")

    state["map"] = bad
    assert run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--chunk-chars", "1"))[0] == 0
    drops = (run(linked) / "npc_jimjar.drops.md").read_text()
    assert "Nobody wrote this." in drops and "not-found" in drops and "Bad cite." in drops and "outside-chunk" in drops
    draft = (linked / OUT / "draft/npc_jimjar.md").read_text()
    assert "Nobody wrote this" not in draft and "002.77" not in draft


def test_reduce_prompt_has_notes_last_chunk_and_manual_edits_only(linked, fake):
    calls, _ = fake
    d = linked / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "jimjar.authored.yaml").write_text("subject: Jimjar\nmanual:\n  - Jimjar is a deep gnome.\nsecrets: |\n  SECRET-CANARY-7731\n")
    assert run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--chunk-chars", "1"))[0] == 0
    maps = [c for c in calls if c["kind"] == "map"]
    red = next(c for c in calls if c["kind"] == "reduce")
    assert all("[manual 1] Jimjar is a deep gnome." in m["user"] for m in maps)
    assert "[manual 1] Jimjar is a deep gnome." in red["user"]
    assert "## Chapter 006" in red["user"] and "## Chapter 002" not in red["user"].split("EVIDENCE OF THE LAST CHUNK")[1]
    assert "VERIFIED NOTES" in red["user"] and "Something happened. [ch 002 / 002.01]" in red["user"]
    assert "## Identity" in red["user"] and "## History with the Party\n- " not in red["user"].split("OUTLINE:")[1]
    assert not any("SECRET-CANARY" in c["user"] + c["system"] for c in calls)


def test_missing_reduce_section_gives_incomplete_and_exit_3(linked, fake):
    _, state = fake
    state["reduce"] = REDUCE_BODY.replace("## Relationships\n\n- Travels with Eldeth. [ch 002 / 002.01]\n", "")
    rc, so, _ = run_cli(_args(linked, "npc-draft", "--name", "Jimjar"))
    assert rc == 3 and "incomplete" in so and "## Relationships" in so
    assert (linked / OUT / "draft/npc_jimjar.incomplete.md").is_file()
    assert not (linked / OUT / "draft/npc_jimjar.md").exists()


def test_a_map_failure_exits_4_and_records_where_it_stopped(linked, fake):
    calls, state = fake
    state["fail_at"] = 2
    rc, _, err = run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--chunk-chars", "1"))
    assert rc == 4 and "map02" in err and len(calls) == 2
    rec = json.loads((run(linked) / "record.json").read_text())
    assert rec["stopped_at"]["stem"] == "npc_jimjar" and rec["stopped_at"]["stage"] == "map02"


def test_a_reduce_failure_exits_4(linked, fake):
    calls, state = fake
    state["fail_at"] = 5
    rc, _, err = run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--chunk-chars", "1"))
    assert rc == 4 and json.loads((run(linked) / "record.json").read_text())["stopped_at"]["stage"] == "reduce"


def test_dump_only_writes_map_prompts_and_makes_no_call(linked, fake, monkeypatch):
    calls, _ = fake
    monkeypatch.setattr(npc_draft, "client_from_args", lambda *a, **k: (_ for _ in ()).throw(AssertionError("client")))
    rc, _, _ = run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--chunk-chars", "1", "--dump-only"))
    assert rc == 0 and not calls
    names = {p.name for p in run(linked).iterdir()}
    assert "npc_jimjar.map04.user.md" in names and not any("reduce" in n or ".out." in n for n in names)
    assert not (linked / OUT / "draft").exists()


def test_the_draft_key_changes_with_mode_chunk_chars_and_prompts(linked, fake, monkeypatch):
    calls, _ = fake
    n = lambda: len(calls)  # noqa: E731
    base = ["npc-draft", "--name", "Jimjar"]
    assert run_cli(_args(linked, *base))[0] == 0
    k = n()
    assert run_cli(_args(linked, *base))[0] == 0 and n() == k                      # unchanged: skipped
    assert run_cli(_args(linked, *base, "--chunk-chars", "1"))[0] == 0 and n() > k  # chunk size
    k = n()
    assert run_cli(_args(linked, *base, "--mode", "one-shot"))[0] == 0 and n() == k + 1   # mode
    k = n()
    monkeypatch.setattr(npc_chunked, "load_reduce_system", lambda: "PROSE PART changed")
    assert run_cli(_args(linked, *base))[0] == 0 and n() > k                       # a prompt


def test_defaults_are_the_spark_chunked_and_come_from_the_schema(linked, fake):
    assert run_cli(_args(linked, "npc-draft", "--name", "Jimjar"))[0] == 0
    rec = json.loads((run(linked) / "record.json").read_text())
    assert (rec["backend"], rec["model"], rec["mode"]) == ("dgx", "qwen3.8-flash-next", "chunked")
    assert rec["chunk_chars"] == schema.DEFAULT_CHUNK_CHARS == 60000


def test_config_draft_block_overrides_the_schema_and_flags_override_the_config(linked, fake):
    (linked / "config/npc_dossiers.yaml").write_text("draft:\n  model: cfg-model\n  mode: one-shot\n  chunk_chars: 5\n")
    assert run_cli(_args(linked, "npc-draft", "--name", "Jimjar"))[0] == 0
    rec = json.loads((run(linked) / "record.json").read_text())
    assert (rec["backend"], rec["model"], rec["mode"], rec["chunk_chars"]) == ("dgx", "cfg-model", "one-shot", None)
    assert run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--mode", "chunked", "--model", "flag-model"))[0] == 0
    rec = json.loads((run(linked) / "record.json").read_text())
    assert (rec["model"], rec["mode"], rec["chunk_chars"]) == ("flag-model", "chunked", 5)


def test_unknown_draft_keys_refuse(linked, fake):
    (linked / "config/npc_dossiers.yaml").write_text("draft:\n  endpoint: http://x/v1\n")
    rc, _, err = run_cli(_args(linked, "npc-draft", "--name", "Jimjar"))
    assert rc == 2 and "endpoint" in err
    (linked / "config/npc_dossiers.yaml").write_text("draft:\n  mode: sideways\n")
    assert run_cli(_args(linked, "npc-draft", "--name", "Jimjar"))[0] == 2


def test_a_different_backend_does_not_inherit_the_spark_model(linked, fake):
    assert run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--backend", "anthropic"))[0] == 0
    rec = json.loads((run(linked) / "record.json").read_text())
    assert rec["backend"] == "anthropic" and rec["model"] != schema.DEFAULT_DRAFT_MODEL


def test_no_endpoint_literal_in_the_package():
    import pathlib
    for p in pathlib.Path(schema.__file__).parent.glob("*.py"):
        t = p.read_text(encoding="utf-8")
        assert "192.168." not in t and "http://" not in t.replace("http://x", ""), p.name


# ── quoted spans in History and Arc bullets; wider normalisation (GM ruling 2026-10-06) ──

SPAN_CHUNK = """## Chapter 035

### Scene 035.04 — Bets (mentioned)
- Source: x.md (line 7)

Jimjar then wonders aloud "Who decides?" and offers a bet that no one will agree. He says "I don't want to get killed. Not today." Ilvara tracks the party by scent.
"""


def _span_index():
    return npc_check.EvidenceIndex.of(npc_check.split_chapters(SPAN_CHUNK))


def _arc(text):
    return f"## History with the Party\n## Notable Quotes\n## Arc-Score Candidates\n- {text} [ch 035 / 035.04]\n"


def test_nested_single_marks_and_a_comma_moved_inside_the_quote_are_typography():
    idx = _span_index()
    for span in ("\"Jimjar then wonders aloud 'Who decides?' and offers a bet that no one will agree.\"",
                 '"I don\'t want to get killed,"'):
        verdict, _ = npc_check.in_evidence(span, idx)
        assert verdict == "typography-normalised", span
    assert npc_check.in_evidence('"I don\'t want to get killed. Not today."', idx)[0] == "ok"


def test_other_changes_still_fail_including_a_paraphrase_and_an_ellipsis_join():
    idx = _span_index()
    assert npc_check.in_evidence('"Ilvara can track the party through the pervasive fungi of the Underdark."', idx)[0] is None
    assert npc_check.in_evidence('"I do not want to get killed,"', idx)[0] is None
    assert npc_check.in_evidence('"Jimjar then wonders aloud... Nobody takes it."', idx)[0] is None


def test_map_check_drops_a_history_or_arc_bullet_whose_span_is_not_verbatim_and_logs_the_span():
    raw = (
        "## History with the Party\n"
        "- Ilvara tracks \"Ilvara can track the party through the pervasive fungi of the Underdark.\" [ch 035 / 035.04]\n"
        "- Jimjar wonders \"Who decides?\" aloud. [ch 035 / 035.04]\n"
        "- Jimjar wonders aloud 'Who decides?' with no marks of the outer kind. [ch 035 / 035.04]\n"
        "## Notable Quotes\n"
        "## Arc-Score Candidates\n"
        "- Candidate: \"I don't want to get killed,\" [ch 035 / 035.04]\n"
        "- Candidate: \"he never said this\" [ch 035 / 035.04]\n"
    )
    res = npc_chunked.check_map(raw, _span_index(), 0)
    assert len(res.history) == 2 and len(res.arc) == 1
    dropped = [d for d in res.drops if d.reason == "quoted-span-not-found"]
    assert {d.section for d in dropped} == {"history", "arc"} and len(dropped) == 2
    md = npc_chunked.render_drops_md("Ilvara", [("035-035", res)])
    assert "quoted-span-not-found" in md and "pervasive fungi" in md and "he never said this" in md
    assert any("don't want to get killed," in t for t in res.typography)       # kept, recorded


def test_reduce_sections_are_not_span_checked_by_the_map_check_but_verify_still_reports_them(linked, fake):
    _, state = fake
    state["reduce"] = REDUCE_BODY.replace("Cautious and watchful.", 'He said "never in my life" once.')
    assert run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--chunk-chars", "1"))[0] == 0
    assert "never in my life" in (linked / OUT / "draft/npc_jimjar.md").read_text()      # nothing dropped
    rc, so, _ = run_cli(_args(linked, "npc-verify", "--name", "Jimjar"))
    assert rc == 5 and "not-found 1" in so


# ── quiet streaming and progress lines ──────────────────────────────────────


def test_model_calls_are_silent_and_progress_lines_are_printed(linked, fake, monkeypatch):
    calls, _ = fake
    rc, so, _ = run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--chunk-chars", "1"))
    assert rc == 0
    import re
    lines = [ln for ln in so.splitlines() if ln.startswith("Jimjar: ")]
    assert re.fullmatch(r"Jimjar: map 1/4 \(ch 002-002\) \d+\.\ds", lines[0])
    assert re.fullmatch(r"Jimjar: map 4/4 \(ch 006-006\) \d+\.\ds", lines[3])
    assert re.fullmatch(r"Jimjar: reduce \d+\.\ds", lines[4])
    rc, so, _ = run_cli(_args(linked, "npc-draft", "--name", "Jimjar", "--mode", "one-shot", "--force"))
    assert re.search(r"(?m)^Jimjar: draft \d+\.\ds$", so)


def test_render_part_asks_the_backend_for_silence(monkeypatch):
    seen = {}
    monkeypatch.setattr(npc_draft, "stream_api", lambda *a, **k: seen.update(k) or "x")
    assert npc_draft.render_part(object(), "s", "u", "m", 5) == "x" and seen["silent"] is True
