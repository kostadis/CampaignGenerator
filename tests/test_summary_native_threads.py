"""Spec 034 User Story 3: thread proposals the GM can ratify (T021, T022, T024).

``thread_attach`` and ``thread_check`` are deterministic code: a thread note attaches to the one ratified
thread whose title or alias equals its name (research R4), and a model's grouping is checked against the
notes and the registry before any proposal is written (R5). ``thread-propose`` is the one model step around
them; every batch sees only checked notes and ratified threads, never another batch's output (Principle II).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from pipelines.summary_native import notes, schema, thread_attach, thread_check, thread_propose
from tests import conftest_party as cp
from tests import conftest_state as cs

# ── helpers ─────────────────────────────────────────────────────────────────


def tn(chapter: int, tag: str, name: str, body: str = "does a thing") -> notes.Note:
    """A kept thread note, built the way ``notes.check_chunk`` builds one."""
    text = f"- [{tag}] **{name}** — {body} [ch {chapter:03d} / {chapter:03d}.01]"
    return notes.Note("thread", text, chapter, f"{chapter:03d}-{chapter:03d}", tag=tag, subject=name)


def chunks(*ns: notes.Note) -> list[notes.CheckedChunk]:
    return [notes.CheckedChunk("002-004", list(ns))]


def thr(tid: str, title: str, aliases=(), status: str = "open", log=()) -> dict:
    return {"id": tid, "title": title, "aliases": list(aliases), "status": status, "opened": 2, "log": list(log)}


def reg(*threads: dict) -> dict:
    return {"version": 1, "threads": list(threads)}


def sha12(ids) -> str:
    return "g-" + hashlib.sha1("|".join(sorted(ids)).encode("utf-8")).hexdigest()[:12]


# ── T021: attach ────────────────────────────────────────────────────────────


class TestAttach:
    def test_exact_title_or_alias_attaches(self):
        a, b, c = tn(2, "OPENED", "The Carver's march"), tn(3, "ADVANCED", "the CARVER's march!"), tn(4, "ADVANCED", "Carver march")
        att = thread_attach.attach(chunks(a, b, c), reg(thr("cm", "The Carver's march", ["Carver march"])))
        assert [att.by_note[n.note_id] for n in (a, b, c)] == ["cm", "cm", "cm"]
        assert att.unattached == []
        assert [n.note_id for n in att.threads["cm"].notes] == [a.note_id, b.note_id, c.note_id]

    def test_a_different_name_is_not_attached_by_similarity(self):
        near = tn(3, "ADVANCED", "Carver marches")  # one letter from an alias
        att = thread_attach.attach(chunks(near), reg(thr("cm", "The Carver's march", ["Carver march"])))
        assert att.by_note[near.note_id] is None and att.unattached == [near]

    def test_a_name_matching_two_threads_is_ambiguous_and_unattached(self):
        n = tn(3, "ADVANCED", "The ring")
        att = thread_attach.attach(chunks(n), reg(thr("a", "The ring"), thr("b", "Other", ["the ring"])))
        assert att.by_note[n.note_id] == thread_attach.AMBIGUOUS
        assert att.unattached == [n]
        assert att.ambiguous == {"The ring": ["a", "b"]}
        assert att.threads == {}

    def test_only_thread_notes_are_considered(self):
        ev = notes.Note("event", "- The march breaks. [ch 004 / 004.01]", 4, "004-004")
        t = tn(4, "ADVANCED", "The march")
        att = thread_attach.attach(chunks(ev, t), reg())
        assert att.unattached == [t] and list(att.by_note) == [t.note_id]

    def test_a_note_without_a_name_is_unattached(self):
        n = notes.Note("thread", "- [ADVANCED] no bold name [ch 004 / 004.01]", 4, "004-004", tag="ADVANCED", subject=None)
        att = thread_attach.attach(chunks(n), reg(thr("a", "no bold name")))
        assert att.unattached == [n]

    def test_an_empty_or_absent_registry_attaches_nothing(self):
        n1, n2 = tn(2, "OPENED", "A"), tn(3, "ADVANCED", "B")
        for registry in (None, {}, {"threads": []}, reg()):
            att = thread_attach.attach(chunks(n1, n2), registry)
            assert att.unattached == [n1, n2] and att.threads == {}
            assert att.open_threads == [] and att.dormant_threads == []

    def test_unattached_notes_are_in_chapter_order_whatever_the_chunk_order(self):
        late, early = tn(4, "ADVANCED", "B"), tn(2, "OPENED", "A")
        att = thread_attach.attach([notes.CheckedChunk("004-004", [late]), notes.CheckedChunk("002-002", [early])], reg())
        assert att.unattached == [early, late]

    def test_an_identical_note_in_two_chunks_counts_once(self):
        n = tn(3, "ADVANCED", "A")
        att = thread_attach.attach(
            [notes.CheckedChunk("002-003", [n]), notes.CheckedChunk("003-004", [n])], reg())
        assert att.unattached == [n]

    # open / closed (FR-009a)

    def test_open_defers_to_the_latest_attached_tag(self):
        r = reg(thr("t", "T"))
        for tag, is_open in (("OPENED", True), ("ADVANCED", True), ("RESOLVED", False), ("ABANDONED", False)):
            att = thread_attach.attach(chunks(tn(2, "OPENED", "T"), tn(3, tag, "T")), r)
            assert att.threads["t"].open is is_open, tag

    def test_the_latest_note_is_the_highest_chapter_not_the_last_extracted(self):
        r = reg(thr("t", "T"))
        resolved, opened = tn(4, "RESOLVED", "T"), tn(2, "OPENED", "T")
        att = thread_attach.attach([notes.CheckedChunk("004-004", [resolved]), notes.CheckedChunk("002-002", [opened])], r)
        assert att.threads["t"].latest == resolved and att.threads["t"].open is False

    @pytest.mark.parametrize("status", ["resolved", "abandoned"])
    def test_a_gm_status_other_than_open_wins_over_an_advancing_tag(self, status):
        att = thread_attach.attach(chunks(tn(3, "ADVANCED", "T")), reg(thr("t", "T", status=status)))
        st = att.threads["t"]
        assert st.open is False and st.dormant is False
        assert att.open_threads == [] and att.dormant_threads == []

    def test_a_dormant_thread_is_in_the_dormant_set_not_the_open_one(self):
        att = thread_attach.attach(chunks(tn(3, "ADVANCED", "T")), reg(thr("t", "T", status="dormant")))
        assert att.threads["t"].open is False and att.threads["t"].dormant is True
        assert [s.id for s in att.dormant_threads] == ["t"] and att.open_threads == []

    def test_a_thread_with_no_status_is_open_by_default(self):
        t = thr("t", "T")
        del t["status"]
        att = thread_attach.attach(chunks(tn(3, "ADVANCED", "T")), reg(t))
        assert att.threads["t"].open is True

    def test_a_thread_with_no_notes_in_range_is_not_listed(self):
        att = thread_attach.attach(chunks(tn(3, "ADVANCED", "T")), reg(thr("t", "T"), thr("u", "U")))
        assert list(att.threads) == ["t"]

    def test_active_plots_order_is_newest_activity_first(self):
        r = reg(thr("old", "Old"), thr("new", "New"), thr("mid", "Mid"))
        att = thread_attach.attach(
            chunks(tn(2, "OPENED", "Old"), tn(4, "ADVANCED", "New"), tn(3, "ADVANCED", "Mid"), tn(2, "OPENED", "New")), r)
        assert [s.id for s in att.open_threads] == ["new", "mid", "old"]

    def test_active_plots_ties_keep_registry_order(self):
        r = reg(thr("b", "B"), thr("a", "A"))
        att = thread_attach.attach(chunks(tn(3, "ADVANCED", "A"), tn(3, "ADVANCED", "B")), r)
        assert [s.id for s in att.open_threads] == ["b", "a"]

    # the fixture campaign

    def test_the_fixture_notes_attach_to_the_fixture_registry(self):
        registry = yaml.safe_load((cp.PARTY_FIXTURE / "docs" / "thread_registry.yaml").read_text(encoding="utf-8"))
        att = thread_attach.attach(cp.checked_results(), registry)
        assert att.unattached == []
        assert [n.first_chapter for n in att.threads["carver-march"].notes] == [2, 3, 4]  # "Carver march" is an alias
        assert att.threads["carver-march"].open is True
        assert att.threads["signet-ring"].open is False  # GM-set resolved
        assert [s.id for s in att.open_threads] == ["carver-march"]

    # outputs

    def test_attach_json_is_deterministic_and_holds_no_path_or_time(self, tmp_path):
        a = tn(2, "OPENED", "T")
        att = thread_attach.attach(chunks(a, tn(3, "ADVANCED", "Loose")), reg(thr("t", "T")))
        p = thread_attach.write_attach(tmp_path / "ch002-004", att, (2, 4))
        assert p == tmp_path / "ch002-004" / "state" / "threads" / "attach.json"
        first = p.read_bytes()
        thread_attach.write_attach(tmp_path / "ch002-004", att, (2, 4))
        assert p.read_bytes() == first
        data = json.loads(first)
        assert data["notes"][a.note_id] == "t" and None in data["notes"].values()
        assert data["range"] == {"since": 2, "until": 4}
        assert str(tmp_path) not in first.decode("utf-8")

    def test_the_report_names_threads_ambiguous_names_and_the_unattached_count(self):
        att = thread_attach.attach(
            chunks(tn(2, "OPENED", "T"), tn(3, "RESOLVED", "T"), tn(3, "ADVANCED", "Dup"), tn(4, "ADVANCED", "Loose")),
            reg(thr("t", "The T", ["T"]), thr("d1", "Dup"), thr("d2", "Other", ["dup"])))
        md = thread_attach.threads_report_md(att, (2, 4))
        assert "ch002-004" in md and "The T" in md and "closed" in md
        assert "Dup" in md and "d1" in md and "d2" in md and "ambiguous" in md.lower()
        assert "2 unattached" in md  # "Dup" (ambiguous) and "Loose"


# ── T022: check_groups ──────────────────────────────────────────────────────

N = [tn(2, "OPENED", "Alpha", "a one"), tn(3, "ADVANCED", "Alfa", "a two"), tn(3, "OPENED", "Beta", "b one"),
     tn(4, "ADVANCED", "Beta plan", "b two"), tn(4, "OPENED", "Gamma", "g one")]
IDS = [n.note_id for n in N]
REGISTRY = reg(thr("t-old", "Old thread"))


def groups_raw(*gs) -> dict:
    return {"groups": list(gs)}


def new(title: str, *members) -> dict:
    return {"kind": "new", "title": title, "members": list(members)}


def cont(thread: str, *members) -> dict:
    return {"kind": "continues", "thread": thread, "members": list(members)}


def member_ids(groups) -> list[str]:
    return [m["id"] for g in groups for m in g["members"]]


def by_key(groups) -> dict:
    return {g["key"]: g for g in groups}


def kinds_of(groups, *ids) -> set:
    return {g["kind"] for g in groups if set(ids) & {m["id"] for m in g["members"]}}


class TestCheckGroups:
    def test_valid_groups_pass_and_leftovers_become_singles(self):
        groups, lines = thread_check.check_groups(
            groups_raw(new("Alpha", IDS[0], IDS[1]), cont("t-old", IDS[2], IDS[3])), N, REGISTRY, [])
        assert sorted(member_ids(groups)) == sorted(IDS)  # exactly once each
        kinds = sorted(g["kind"] for g in groups)
        assert kinds == ["continues", "new", "single"]
        new_g = next(g for g in groups if g["kind"] == "new")
        assert new_g["title"] == "Alpha" and [m["id"] for m in new_g["members"]] == [IDS[0], IDS[1]]
        assert next(g for g in groups if g["kind"] == "continues")["thread"] == "t-old"
        assert not [ln for ln in lines if ln.startswith(thread_check.DROPPED)]

    def test_a_member_has_the_note_fields_the_gm_reads(self):
        (g,) = [g for g in thread_check.check_groups(groups_raw(new("Alpha", IDS[0], IDS[1])), N[:2], REGISTRY, [])[0]]
        assert g["members"][0] == {
            "id": IDS[0], "chapter": 2, "tag": "OPENED", "name": "Alpha", "text": "a one", "cite": "[ch 002 / 002.01]"}

    def test_an_unknown_member_is_removed_and_reported_the_rest_stands(self):
        groups, lines = thread_check.check_groups(
            groups_raw(new("Alpha", IDS[0], "n-0000000000", IDS[1])), N, REGISTRY, [])
        g = next(g for g in groups if g["kind"] == "new")
        assert [m["id"] for m in g["members"]] == [IDS[0], IDS[1]]
        assert any("n-0000000000" in ln and ln.startswith(thread_check.DROPPED) for ln in lines)

    def test_an_attached_member_is_removed_and_the_report_says_where_it_is_attached(self):
        unattached = N[1:]
        groups, lines = thread_check.check_groups(
            groups_raw(new("Alpha", IDS[0], IDS[1])), unattached, REGISTRY, [], attached={IDS[0]: "t-old"})
        assert IDS[0] not in member_ids(groups)
        assert any(IDS[0] in ln and "t-old" in ln for ln in lines)
        assert kinds_of(groups, IDS[1]) == {"single"}  # left with one member

    def test_a_note_in_two_groups_is_removed_from_both_and_becomes_a_single(self):
        groups, lines = thread_check.check_groups(
            groups_raw(new("X", IDS[0], IDS[1], IDS[2]), new("Y", IDS[2], IDS[3], IDS[4])), N, REGISTRY, [])
        (holder,) = [g for g in groups if IDS[2] in {m["id"] for m in g["members"]}]
        assert holder["kind"] == "single" and len(holder["members"]) == 1
        assert sorted(member_ids(groups)) == sorted(IDS)
        assert any(IDS[2] in ln and ln.startswith(thread_check.DROPPED) for ln in lines)

    def test_a_continues_naming_a_missing_thread_is_dropped_and_its_notes_become_singles(self):
        groups, lines = thread_check.check_groups(groups_raw(cont("t-nope", IDS[0], IDS[1])), N, REGISTRY, [])
        assert all(g["kind"] == "single" for g in groups) and sorted(member_ids(groups)) == sorted(IDS)
        assert any("t-nope" in ln and ln.startswith(thread_check.DROPPED) for ln in lines)

    def test_a_dropped_group_does_not_count_as_a_claim(self):
        # the first group is dropped (missing thread); its note is then free for the second group
        groups, _ = thread_check.check_groups(
            groups_raw(cont("t-nope", IDS[0], IDS[1]), new("X", IDS[1], IDS[2])), N, REGISTRY, [])
        (g,) = [g for g in groups if g["kind"] == "new"]
        assert [m["id"] for m in g["members"]] == [IDS[1], IDS[2]]

    def test_a_group_left_empty_is_dropped(self):
        groups, lines = thread_check.check_groups(groups_raw(new("Ghost", "n-1", "n-2")), N, REGISTRY, [])
        assert all(g["kind"] == "single" for g in groups)
        assert any("Ghost" in ln or "empty" in ln for ln in lines)

    def test_a_group_left_with_one_member_becomes_a_single(self):
        groups, _ = thread_check.check_groups(groups_raw(new("Alpha", IDS[0], "n-1")), N, REGISTRY, [])
        (g,) = [g for g in groups if IDS[0] in {m["id"] for m in g["members"]}]
        assert g["kind"] == "single" and g["key"] == sha12([IDS[0]])

    def test_a_malformed_group_is_dropped_and_its_notes_fall_through(self):
        raw = groups_raw("not an object", {"kind": "merge", "members": [IDS[0], IDS[1]]},
                         {"kind": "new", "title": "T", "members": "n-x"}, new("Beta", IDS[2], IDS[3]))
        groups, lines = thread_check.check_groups(raw, N, REGISTRY, [])
        assert sorted(member_ids(groups)) == sorted(IDS)
        assert sum(1 for ln in lines if ln.startswith(thread_check.DROPPED)) >= 3

    def test_a_repeated_id_inside_one_group_counts_once(self):
        groups, _ = thread_check.check_groups(groups_raw(new("Alpha", IDS[0], IDS[0], IDS[1])), N, REGISTRY, [])
        g = next(g for g in groups if g["kind"] == "new")
        assert [m["id"] for m in g["members"]] == [IDS[0], IDS[1]]

    def test_every_unattached_note_is_in_exactly_one_group_whatever_the_model_said(self):
        raw = groups_raw(new("A", IDS[0], IDS[1], "n-bogus"), new("B", IDS[1], IDS[2]), cont("t-nope", IDS[3]), new("C"))
        groups, _ = thread_check.check_groups(raw, N, REGISTRY, [])
        assert sorted(member_ids(groups)) == sorted(IDS)

    def test_keys_are_g_plus_the_sha1_of_the_sorted_member_ids(self):
        groups, _ = thread_check.check_groups(groups_raw(new("Alpha", IDS[1], IDS[0])), N, REGISTRY, [])
        g = next(g for g in groups if g["kind"] == "new")
        assert g["key"] == sha12([IDS[0], IDS[1]])
        assert re.fullmatch(r"g-[0-9a-f]{12}", g["key"])
        assert thread_check.group_key([IDS[1], IDS[0]]) == g["key"]

    def test_output_is_deterministic_and_in_chapter_order(self):
        raw = groups_raw(new("B", IDS[3], IDS[2]), new("A", IDS[1], IDS[0]))
        one = thread_check.check_groups(raw, N, REGISTRY, [])
        assert one == thread_check.check_groups(raw, N, REGISTRY, [])
        firsts = [g["members"][0]["chapter"] for g in one[0]]
        assert firsts == sorted(firsts)
        assert [m["chapter"] for m in one[0][0]["members"]] == sorted(m["chapter"] for m in one[0][0]["members"])

    def test_json_text_is_parsed_and_unparseable_text_is_all_singles(self):
        ok, _ = thread_check.check_groups(json.dumps(groups_raw(new("Alpha", IDS[0], IDS[1]))), N, REGISTRY, [])
        assert any(g["kind"] == "new" for g in ok)
        fenced, _ = thread_check.check_groups("```json\n" + json.dumps(groups_raw(new("Alpha", IDS[0], IDS[1]))) + "\n```",
                                              N, REGISTRY, [])
        assert any(g["kind"] == "new" for g in fenced)
        bad, lines = thread_check.check_groups("I think these go together", N, REGISTRY, [])
        assert all(g["kind"] == "single" for g in bad) and len(bad) == len(N)
        assert lines  # says so

    def test_parse_groups_raises_for_text_that_is_not_the_contract(self):
        for text in ("nope", "[1, 2]", '{"groups": 3}', '{"other": []}'):
            with pytest.raises(thread_check.ThreadJsonError):
                thread_check.parse_groups(text)
        assert thread_check.parse_groups('{"groups": []}') == []

    # rulings

    def test_rejected_members_are_kept_out_of_model_input_and_come_back_as_singles(self):
        rejected = {"key": sha12(IDS[:2]), "kind": "new", "status": "rejected", "members": [{"id": i} for i in IDS[:2]]}
        assert [n.note_id for n in thread_check.offered(N, [rejected])] == IDS[2:]
        # a model that groups them anyway is told they were not offered
        groups, lines = thread_check.check_groups(groups_raw(new("Alpha", IDS[0], IDS[1])), N, REGISTRY, [rejected])
        assert kinds_of(groups, IDS[0]) == {"single"} and kinds_of(groups, IDS[1]) == {"single"}
        assert sorted(member_ids(groups)) == sorted(IDS)
        assert any(ln.startswith(thread_check.DROPPED) for ln in lines)

    def test_deferred_members_are_neither_offered_nor_re_offered(self):
        deferred = {"key": sha12(IDS[:2]), "kind": "new", "status": "deferred", "members": [{"id": i} for i in IDS[:2]]}
        assert [n.note_id for n in thread_check.offered(N, [deferred])] == IDS[2:]
        groups, _ = thread_check.check_groups(groups_raw(), N, REGISTRY, [deferred])
        assert sorted(member_ids(groups)) == sorted(IDS[2:])  # they live in the deferred entry

    def test_pending_and_ratified_groups_do_not_exclude_anything(self):
        for status in ("pending", "ratified"):
            prior = {"key": sha12(IDS[:2]), "kind": "new", "status": status, "members": [{"id": i} for i in IDS[:2]]}
            assert [n.note_id for n in thread_check.offered(N, [prior])] == IDS

    def test_name_keyed_ensemble_proposals_are_ignored(self):
        ensemble = {"norm": "alpha", "title": "Alpha", "status": "rejected", "chapters": [2], "evidence": []}
        assert [n.note_id for n in thread_check.offered(N, [ensemble])] == IDS

    def test_stale_ratified_groups_are_listed(self):
        gone = {"key": "g-aaaaaaaaaaaa", "status": "ratified", "kind": "new",
                "members": [{"id": IDS[0], "chapter": 2}, {"id": "n-vanished0", "chapter": 3}]}
        elsewhere = {"key": "g-bbbbbbbbbbbb", "status": "ratified", "kind": "new", "members": [{"id": "n-other00000", "chapter": 90}]}
        live = {"key": "g-cccccccccccc", "status": "ratified", "kind": "new", "members": [{"id": IDS[1], "chapter": 3}]}
        pending = {"key": "g-dddddddddddd", "status": "pending", "kind": "new", "members": [{"id": "n-vanished1", "chapter": 3}]}
        lines = thread_check.stale_ratified([gone, elsewhere, live, pending], set(IDS), 2, 4)
        assert len(lines) == 1 and "g-aaaaaaaaaaaa" in lines[0] and "n-vanished0" in lines[0]


class TestMergeProposals:
    def groups(self, *specs):
        out, _ = thread_check.check_groups(groups_raw(*specs), N, REGISTRY, [])
        return out

    def test_a_new_file_gets_pending_entries_with_the_source(self, tmp_path):
        p = tmp_path / "docs" / "ensemble" / "thread_proposals.yaml"
        gs = self.groups(new("Alpha", IDS[0], IDS[1]))
        stats = thread_check.merge_proposals(p, gs, "summary_native ch002-004 run R1")
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert [e["key"] for e in doc["proposals"]] == [g["key"] for g in gs]
        assert {e["status"] for e in doc["proposals"]} == {"pending"}
        assert {e["source"] for e in doc["proposals"]} == {"summary_native ch002-004 run R1"}
        assert stats["pending"] == len(gs)
        assert list(p.parent.glob("*.tmp")) == [] and sorted(x.name for x in p.parent.iterdir()) == [p.name]

    def test_name_keyed_ensemble_entries_are_left_untouched(self, tmp_path):
        p = tmp_path / "t.yaml"
        ensemble = {"norm": "buppido", "title": "Buppido", "all_titles": ["Buppido"], "matches": None, "chapters": [30],
                    "status": "ratified", "ruled_thread": "bup", "evidence": [{"chapter": 30, "fact": "x"}]}
        p.write_text(yaml.safe_dump({"note": "keep me", "proposals": [ensemble]}), encoding="utf-8")
        thread_check.merge_proposals(p, self.groups(new("Alpha", IDS[0], IDS[1])), "src")
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert doc["proposals"][0] == ensemble and doc["note"] == "keep me"
        assert len(doc["proposals"]) > 1

    def test_rulings_are_preserved_by_key_and_not_duplicated_as_pending(self, tmp_path):
        p = tmp_path / "t.yaml"
        gs = self.groups(new("Alpha", IDS[0], IDS[1]))
        key = next(g["key"] for g in gs if g["kind"] == "new")
        ruled = {"key": key, "kind": "new", "title": "Alpha (edited)", "members": [{"id": IDS[0]}, {"id": IDS[1]}],
                 "status": "deferred", "note": "ask the table", "source": "old"}
        p.write_text(yaml.safe_dump({"proposals": [ruled]}), encoding="utf-8")
        thread_check.merge_proposals(p, gs, "src")
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert [e for e in doc["proposals"] if e["key"] == key] == [ruled]

    def test_a_pending_group_sharing_a_note_with_the_new_run_is_replaced(self, tmp_path):
        p = tmp_path / "t.yaml"
        stale = {"key": "g-111111111111", "kind": "new", "title": "Old grouping", "status": "pending",
                 "members": [{"id": IDS[0]}, {"id": "n-notinthisrun"}], "source": "old"}
        far = {"key": "g-222222222222", "kind": "new", "title": "Other range", "status": "pending",
               "members": [{"id": "n-farchapter0"}, {"id": "n-farchapter1"}], "source": "old"}
        p.write_text(yaml.safe_dump({"proposals": [stale, far]}), encoding="utf-8")
        thread_check.merge_proposals(p, self.groups(new("Alpha", IDS[0], IDS[1])), "src")
        keys = [e["key"] for e in yaml.safe_load(p.read_text(encoding="utf-8"))["proposals"]]
        assert "g-111111111111" not in keys and "g-222222222222" in keys

    def test_a_pending_group_whose_notes_are_attached_now_is_replaced_via_scope(self, tmp_path):
        p = tmp_path / "t.yaml"
        stale = {"key": "g-111111111111", "kind": "new", "status": "pending", "members": [{"id": "n-nowattached"}]}
        p.write_text(yaml.safe_dump({"proposals": [stale]}), encoding="utf-8")
        thread_check.merge_proposals(p, [], "src", scope_ids={"n-nowattached"})
        assert yaml.safe_load(p.read_text(encoding="utf-8"))["proposals"] == []

    def test_merging_twice_is_a_fixed_point(self, tmp_path):
        p = tmp_path / "t.yaml"
        gs = self.groups(new("Alpha", IDS[0], IDS[1]), cont("t-old", IDS[2], IDS[3]))
        thread_check.merge_proposals(p, gs, "src")
        first = p.read_bytes()
        thread_check.merge_proposals(p, gs, "src")
        assert p.read_bytes() == first


# ── T024: thread-propose, end to end with the fake client ───────────────────

BACKEND = ["--backend", "dgx", "--model", "fake-model", "--endpoint", "http://spark:8001/v1"]
NOTE_ROW = re.compile(r"^(n-[0-9a-f]{10}) \| (\d+) \| ([A-Z]+) \| (.*?) \| (.*)$", re.M)


class ThreadModel:
    """Answers ``thread-propose`` calls and records every prompt."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.clients = 0
        self.output = None  # callable(rows) -> str, or None for the default grouping
        self.fail = False

    def client(self, args, **kw):
        self.clients += 1
        return object()

    def render(self, client, system, user, model, max_tokens):
        rows = [m.groups() for m in NOTE_ROW.finditer(user)]
        self.calls.append({"system": system, "user": user, "rows": rows, "model": model, "max_tokens": max_tokens})
        if self.fail:
            raise RuntimeError("upstream failure")
        if self.output is not None:
            return self.output(rows)
        groups = []
        for key, title in (("carver", "The Carver's march"), ("signet", "The signet ring")):
            ids = [r[0] for r in rows if key in r[3].lower()]
            if ids:
                groups.append({"kind": "new", "title": title, "members": ids})
        return json.dumps({"groups": groups})


@pytest.fixture
def tcamp(tmp_path, monkeypatch):
    root = cp.party_campaign(tmp_path)
    cp.fake_party_models(monkeypatch)
    rc, out, err = cs.run_cli(cp.extract_args(root))
    assert rc == 0, out + err
    tm = ThreadModel()
    monkeypatch.setattr(thread_propose, "render_part", tm.render)
    monkeypatch.setattr(thread_propose, "client_from_args", tm.client)
    return root, tm


def propose(root, *extra):
    return cs.run_cli(["thread-propose", *cp.common(root), *BACKEND, *extra])


def registry_path(root) -> Path:
    return root / "docs" / "thread_registry.yaml"


def proposals_path(root) -> Path:
    return root / "docs" / "ensemble" / "thread_proposals.yaml"


def threads_dir(root) -> Path:
    return cp.range_dir(root) / "state" / "threads"


def empty_registry(root) -> None:
    registry_path(root).unlink()


def proposals(root) -> list[dict]:
    return yaml.safe_load(proposals_path(root).read_text(encoding="utf-8"))["proposals"]


def all_note_ids(root) -> list[str]:
    _, results = notes.load_checked(cp.range_dir(root))
    return [n.note_id for n in thread_attach.attach(results, None).notes]


class TestThreadPropose:
    def test_an_empty_registry_groups_the_notes_and_every_note_is_in_exactly_one_proposal(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        rc, out, err = propose(root)
        assert rc == 0, out + err
        ps = proposals(root)
        assert sorted(m["id"] for p in ps for m in p["members"]) == sorted(all_note_ids(root))
        assert {p["status"] for p in ps} == {"pending"} and all(re.fullmatch(r"g-[0-9a-f]{12}", p["key"]) for p in ps)
        by_title = {p["title"]: p for p in ps}
        assert [m["chapter"] for m in by_title["The Carver's march"]["members"]] == [2, 3, 4]
        assert len(by_title["The signet ring"]["members"]) == 2
        assert all(p["source"].startswith("summary_native ch002-004 run ") for p in ps)

    def test_the_summary_line(self, tcamp):
        root, _ = tcamp
        empty_registry(root)
        rc, out, _ = propose(root)
        assert rc == 0
        assert "threads: 5 notes — 0 attached to 0 ratified threads, 5 unattached → 2 group proposals (0 single), 0 dropped" in out
        assert "propose_report.md" in out

    def test_ratified_threads_attach_by_code_and_only_unattached_notes_are_sent(self, tcamp):
        root, tm = tcamp
        # the fixture registry attaches all five notes: nothing to propose, nothing to ask a model
        rc, out, err = propose(root)
        assert rc == 0, out + err
        assert tm.calls == [] and tm.clients == 0
        assert "5 attached to 2 ratified threads, 0 unattached → 0 group proposals" in out
        assert yaml.safe_load(proposals_path(root).read_text(encoding="utf-8"))["proposals"] == []

    def test_the_prompt_carries_unattached_notes_and_the_ratified_threads_only(self, tcamp):
        root, tm = tcamp
        reg = yaml.safe_load(registry_path(root).read_text(encoding="utf-8"))
        reg["threads"][0]["aliases"] = []  # the Carver notes named "Carver march" no longer attach; the title still does
        registry_path(root).write_text(yaml.safe_dump(reg), encoding="utf-8")
        rc, out, err = propose(root)
        assert rc == 0, out + err
        (call,) = tm.calls
        assert [r[3] for r in call["rows"]] == ["Carver march"]  # the one unattached note
        assert "carver-march | The Carver's march" in call["user"] and "signet-ring | The signet ring" in call["user"]
        # the ratified thread's latest note is shown to the model
        assert "The march breaks against the gate" in call["user"]
        assert call["system"].lstrip().startswith("You are helping a GM keep a campaign's plot-thread registry")
        assert call["model"] == "fake-model"
        ps = proposals(root)
        assert len(ps) == 1 and ps[0]["kind"] == "single" and ps[0]["members"][0]["name"] == "Carver march"

    def test_batching_splits_at_max_input_chars_in_chapter_order(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        rc, out, err = propose(root, "--max-input-chars", "1")
        assert rc == 0, out + err
        assert len(tm.calls) == 5
        chapters = [int(r[1]) for c in tm.calls for r in c["rows"]]
        assert chapters == sorted(chapters) and all(len(c["rows"]) == 1 for c in tm.calls)
        # one big batch when the limit allows it
        tm.calls.clear()
        for f in threads_dir(root).iterdir():
            f.unlink()
        rc, out, err = propose(root, "--max-input-chars", "1000000")
        assert rc == 0 and len(tm.calls) == 1 and len(tm.calls[0]["rows"]) == 5

    def test_a_middle_limit_makes_ordered_batches_of_whole_notes(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        propose(root, "--max-input-chars", "1")
        one_note = max(len(c["user"]) for c in tm.calls)
        tm.calls.clear()
        rc, out, err = propose(root, "--max-input-chars", str(one_note + 150))
        assert rc == 0, out + err
        sizes = [len(c["rows"]) for c in tm.calls]
        assert 1 < len(sizes) < 5 and sum(sizes) == 5
        chapters = [int(r[1]) for c in tm.calls for r in c["rows"]]
        assert chapters == sorted(chapters)

    def test_no_batch_prompt_contains_another_batchs_output(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        marks = iter(f"MARK-{i}-TITLE" for i in range(1, 10))
        tm.output = lambda rows: json.dumps({"groups": [{"kind": "new", "title": next(marks), "members": [r[0] for r in rows]}]})
        rc, out, err = propose(root, "--max-input-chars", "1")
        assert rc == 0, out + err
        assert len(tm.calls) == 5
        for call in tm.calls:
            assert "MARK-" not in call["user"] and "g-" not in call["user"]  # no output and no proposal key
            assert "n-" in call["user"]
        # ...and the same ratified-thread block, and nothing else, in every batch
        blocks = {c["user"].split("THREAD NOTES")[0] for c in tm.calls}
        assert len(blocks) == 1

    def test_prompts_and_outputs_land_in_state_threads_one_pair_per_batch(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        assert propose(root, "--max-input-chars", "1")[0] == 0
        names = sorted(p.name for p in threads_dir(root).iterdir())
        assert names == ["attach.json", "propose.01.out.md", "propose.01.user.md", "propose.02.out.md", "propose.02.user.md",
                         "propose.03.out.md", "propose.03.user.md", "propose.04.out.md", "propose.04.user.md",
                         "propose.05.out.md", "propose.05.user.md", "propose_report.md"]
        assert (threads_dir(root) / "propose.01.user.md").read_text(encoding="utf-8") == tm.calls[0]["user"]
        assert json.loads((threads_dir(root) / "propose.01.out.md").read_text(encoding="utf-8"))["groups"]

    def test_a_shorter_rerun_leaves_no_stale_batch_files(self, tcamp):
        root, _ = tcamp
        empty_registry(root)
        propose(root, "--max-input-chars", "1")
        propose(root)
        assert sorted(p.name for p in threads_dir(root).glob("propose.*")) == ["propose.01.out.md", "propose.01.user.md"]

    def test_the_run_record_is_written(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        assert propose(root)[0] == 0
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        rec = json.loads((run / "record.json").read_text(encoding="utf-8"))
        assert rec["step"] == "thread-propose" and rec["range"] == {"since": 2, "until": 4}
        assert rec["backend"] == "dgx" and rec["model"] == "fake-model" and rec["exit_code"] == 0
        assert rec["max_input_chars"] == schema.DEFAULT_THREAD_PROPOSE_MAX_INPUT_CHARS
        assert rec["counts"]["notes"] == 5 and rec["counts"]["unattached"] == 5 and rec["batches"][0]["notes"] == 5
        assert rec["inputs"]["notes_manifest_sha256"] and "thread_registry_sha256" in rec["inputs"]
        assert (run / "propose.system.md").is_file()

    def test_dump_only_makes_no_call_and_writes_the_prompts_and_nothing_else(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        rc, out, err = propose(root, "--dump-only")
        assert rc == 0, out + err
        assert tm.calls == [] and tm.clients == 0
        assert (threads_dir(root) / "propose.01.user.md").is_file() and not (threads_dir(root) / "propose.01.out.md").exists()
        assert not proposals_path(root).exists() and not registry_path(root).exists()
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        assert json.loads((run / "record.json").read_text(encoding="utf-8"))["dump_only"] is True

    def test_the_registry_is_never_written(self, tcamp):
        root, _ = tcamp
        before = registry_path(root).read_bytes()
        reg = yaml.safe_load(before)
        reg["threads"][0]["aliases"] = []
        registry_path(root).write_text(yaml.safe_dump(reg), encoding="utf-8")
        before = registry_path(root).read_bytes()
        assert propose(root)[0] == 0
        assert registry_path(root).read_bytes() == before
        empty_registry(root)
        assert propose(root)[0] == 0
        assert not registry_path(root).exists()

    def test_a_bogus_id_a_double_claim_and_a_missing_continues_target_are_corrected(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        ids = all_note_ids(root)

        def out(rows):
            r = [x[0] for x in rows]
            return json.dumps({"groups": [
                {"kind": "new", "title": "A", "members": [r[0], r[1], "n-bogus0000"]},
                {"kind": "new", "title": "B", "members": [r[1], r[2], r[3]]},
                {"kind": "continues", "thread": "no-such-thread", "members": [r[4]]},
            ]})

        tm.output = out
        rc, stdout, err = propose(root)
        assert rc == 0, stdout + err
        ps = proposals(root)
        assert sorted(m["id"] for p in ps for m in p["members"]) == sorted(ids)
        assert all("n-bogus0000" not in str(p) for p in ps)
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        assert "n-bogus0000" in report and "no-such-thread" in report and ids[1] in report
        assert "dropped" in stdout

    def test_unparseable_output_makes_that_batchs_notes_singles_and_says_so(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        tm.output = lambda rows: "Sorry, I cannot do that."
        rc, out, err = propose(root)
        assert rc == 0, out + err
        ps = proposals(root)
        assert len(ps) == 5 and {p["kind"] for p in ps} == {"single"}
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        assert "batch 1" in report and "not valid" in report.lower()

    def test_a_model_failure_exits_4_and_writes_no_proposal(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        tm.fail = True
        rc, out, err = propose(root)
        assert rc == 4, out + err
        assert not proposals_path(root).exists()
        assert len(tm.calls) == 2  # retried once

    def test_rejected_groups_are_not_proposed_again_and_their_notes_return_as_singles(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        propose(root)
        carver = next(p for p in proposals(root) if p["title"] == "The Carver's march")
        doc = yaml.safe_load(proposals_path(root).read_text(encoding="utf-8"))
        for p in doc["proposals"]:
            if p["key"] == carver["key"]:
                p["status"] = "rejected"
        proposals_path(root).write_text(yaml.safe_dump(doc), encoding="utf-8")
        tm.calls.clear()
        rc, out, err = propose(root)
        assert rc == 0, out + err
        sent = {r[0] for c in tm.calls for r in c["rows"]}
        assert not sent & {m["id"] for m in carver["members"]}  # excluded from model input
        ps = proposals(root)
        assert [p["status"] for p in ps if p["key"] == carver["key"]] == ["rejected"]  # the ruling is kept
        singles = [p for p in ps if p["kind"] == "single" and p["status"] == "pending"]
        assert sorted(p["members"][0]["id"] for p in singles) == sorted(m["id"] for m in carver["members"])

    def test_existing_rulings_and_ensemble_entries_survive_a_rerun(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        proposals_path(root).parent.mkdir(parents=True, exist_ok=True)
        ensemble = {"norm": "buppido", "title": "Buppido", "status": "rejected", "chapters": [30], "evidence": []}
        proposals_path(root).write_text(yaml.safe_dump({"proposals": [ensemble]}), encoding="utf-8")
        assert propose(root)[0] == 0
        first = proposals(root)
        assert first[0] == ensemble
        assert propose(root)[0] == 0
        strip = lambda ps: [{k: v for k, v in p.items() if k != "source"} for p in ps]  # the source names the run
        assert strip(proposals(root)) == strip(first)  # deterministic, idempotent

    def test_a_ratified_group_whose_notes_have_vanished_is_listed_stale(self, tcamp):
        root, _ = tcamp
        empty_registry(root)
        proposals_path(root).parent.mkdir(parents=True, exist_ok=True)
        gone = {"key": "g-aaaaaaaaaaaa", "kind": "new", "title": "Old", "status": "ratified", "ruled_thread": "old",
                "members": [{"id": "n-vanished00", "chapter": 3, "name": "Old", "tag": "OPENED", "text": "x", "cite": ""}]}
        proposals_path(root).write_text(yaml.safe_dump({"proposals": [gone]}), encoding="utf-8")
        assert propose(root)[0] == 0
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        assert "stale" in report.lower() and "g-aaaaaaaaaaaa" in report
        assert any(p["key"] == "g-aaaaaaaaaaaa" for p in proposals(root))

    def test_a_ratification_attaches_the_next_run_by_name_with_no_model_call(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        propose(root)
        calls = len(tm.calls)
        # the GM ratifies the Carver group: the registry gains the thread and both spellings as names
        registry_path(root).write_text(yaml.safe_dump({"version": 1, "threads": [
            {"id": "carver-march", "title": "The Carver's march", "status": "open", "aliases": ["Carver march"],
             "opened": 2, "log": [{"chapter": 2, "change": "opened", "summary": "x"}]}]}), encoding="utf-8")
        rc, out, err = propose(root)
        assert rc == 0, out + err
        sent = {r[3] for c in tm.calls[calls:] for r in c["rows"]}
        assert "The Carver's march" not in sent and "Carver march" not in sent
        assert {p["title"] for p in proposals(root) if p["status"] == "pending"} == {"The signet ring"}
        assert "3 attached to 1 ratified thread" in out

    def test_the_registry_and_proposals_paths_come_from_projections_yaml(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        custom = root / "elsewhere"
        custom.mkdir()
        (root / "config" / "projections.yaml").write_text(
            "stores:\n  thread_registry: elsewhere/registry.yaml\n  thread_proposals: elsewhere/props.yaml\n", encoding="utf-8")
        (custom / "registry.yaml").write_text(yaml.safe_dump({"version": 1, "threads": [
            {"id": "carver-march", "title": "The Carver's march", "status": "open", "aliases": ["Carver march"], "log": []}]}),
            encoding="utf-8")
        rc, out, err = propose(root)
        assert rc == 0, out + err
        assert "3 attached to 1 ratified threads" in out
        assert (custom / "props.yaml").is_file() and not proposals_path(root).exists()

    # refusals

    def test_no_range_is_a_refusal(self, tcamp):
        root, _ = tcamp
        rc, out, err = cs.run_cli(["thread-propose", "--config", str(root / "config" / "config.yaml"),
                                   "--summaries-dir", str(root / "docs" / "summaries"), *BACKEND])
        assert rc == 2 and "--since" in err and "--until" in err

    def test_missing_notes_are_a_refusal_naming_the_command(self, tmp_path, monkeypatch):
        root = cp.party_campaign(tmp_path)
        tm = ThreadModel()
        monkeypatch.setattr(thread_propose, "render_part", tm.render)
        monkeypatch.setattr(thread_propose, "client_from_args", tm.client)
        rc, out, err = propose(root)
        assert rc == 2 and "summary_native extract" in err and tm.calls == []

    def test_a_registry_that_fails_check_is_a_refusal_with_the_findings(self, tcamp):
        root, tm = tcamp
        registry_path(root).write_text(yaml.safe_dump({"version": 1, "threads": [
            {"id": "a", "title": "Same", "status": "open", "aliases": [], "log": []},
            {"id": "b", "title": "Same", "status": "open", "aliases": [], "log": []}]}), encoding="utf-8")
        rc, out, err = propose(root)
        assert rc == 2 and "collides" in err and tm.calls == []
        assert not proposals_path(root).exists()
