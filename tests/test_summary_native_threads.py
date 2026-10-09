"""Spec 034 User Story 3: thread proposals the GM can ratify (T021, T022, T024).

``thread_attach`` and ``thread_check`` are deterministic code: a thread note attaches to the one ratified
thread whose title or alias equals its name (research R4), and a model's grouping is checked against the
notes and the registry before any proposal is written (R5). ``thread-propose`` is the one model step around
them; every batch sees only checked notes and ratified threads, never another batch's output (Principle II).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from campaignlib.thread_registry import group_key
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

    # ── #529: a split's exclusion beats name identity ──

    def test_an_excluded_note_does_not_attach_to_the_thread_that_excludes_it_and_is_unattached(self):
        a, b = tn(2, "OPENED", "The Carver's march"), tn(4, "ADVANCED", "The Carver's march", "another")
        att = thread_attach.attach(chunks(a, b), reg({**thr("cm", "The Carver's march"), "excluded_notes": [b.note_id]}))
        assert att.by_note == {a.note_id: "cm", b.note_id: None}
        assert att.unattached == [b] and [n.note_id for n in att.threads["cm"].notes] == [a.note_id]
        assert att.threads["cm"].latest.note_id == a.note_id  # the excluded note is not the thread's latest

    def test_an_excluded_note_may_still_attach_to_another_thread_by_name(self):
        n = tn(4, "ADVANCED", "The ring")
        att = thread_attach.attach(chunks(n), reg({**thr("a", "The ring"), "excluded_notes": [n.note_id]},
                                                  thr("b", "Other", ["the ring"])))
        assert att.by_note[n.note_id] == "b" and att.ambiguous == {}  # "a" no longer claims it: not ambiguous

    def test_exclusion_is_by_note_id_so_an_identical_name_with_another_id_still_attaches(self):
        gone, new = tn(4, "ADVANCED", "The ring", "old text"), tn(4, "ADVANCED", "The ring", "re-extracted text")
        att = thread_attach.attach(chunks(new), reg({**thr("a", "The ring"), "excluded_notes": [gone.note_id]}))
        assert att.by_note[new.note_id] == "a"


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


def _ids(entry) -> list[str]:
    return [m["id"] for m in entry["members"]]


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

    def test_a_pending_group_does_not_exclude_anything(self):
        prior = {"key": sha12(IDS[:2]), "kind": "new", "status": "pending", "members": [{"id": i} for i in IDS[:2]]}
        assert [n.note_id for n in thread_check.offered(N, [prior])] == IDS

    # ── #525: a ratified member that attaches to nothing any more ──

    def ratified(self, *ids, key=None, **extra):
        return {"key": key or sha12(ids), "kind": "new", "title": "Alpha plan", "status": "ratified",
                "ruled_thread": "t-alpha", "members": [{"id": i} for i in ids], **extra}

    def test_unattached_ratified_members_are_not_offered_to_the_model_but_come_back_as_singles(self):
        prior = [self.ratified(*IDS[:2])]
        assert [n.note_id for n in thread_check.offered(N, prior)] == IDS[2:]
        groups, lines = thread_check.check_groups(groups_raw(new("Alpha", IDS[0], IDS[2])), N, REGISTRY, prior)
        assert sorted(member_ids(groups)) == sorted(IDS)
        assert kinds_of(groups, IDS[0]) == {"single"} and kinds_of(groups, IDS[1]) == {"single"}
        assert any(IDS[0] in ln and "ratified group" in ln for ln in lines)  # told why the model's claim failed

    def test_a_ratified_single_is_offered_again_under_a_key_of_its_own(self):
        ratified = self.ratified(IDS[0], key=sha12([IDS[0]]))
        groups, _ = thread_check.check_groups(groups_raw(), N, REGISTRY, [ratified])
        (again,) = [g for g in groups if g["members"][0]["id"] == IDS[0]]
        assert again["kind"] == "single" and again["key"] != ratified["key"] and re.fullmatch(r"g-[0-9a-f]{12}", again["key"])
        # deterministic, and the next ratification of the same note gets yet another key
        assert thread_check.check_groups(groups_raw(), N, REGISTRY, [ratified])[0] == groups
        ruled_again = {**ratified, "key": again["key"]}
        (third,) = [g for g in thread_check.check_groups(groups_raw(), N, REGISTRY, [ratified, ruled_again])[0]
                    if g["members"][0]["id"] == IDS[0]]
        assert third["key"] not in (ratified["key"], again["key"])

    def test_a_rejected_single_stays_rejected_even_if_it_was_once_ratified(self):
        ratified = self.ratified(IDS[0], key=sha12([IDS[0]]))
        again = thread_check.check_groups(groups_raw(), N, REGISTRY, [ratified])[0][0]
        rejected = {**again, "status": "rejected"}
        groups, _ = thread_check.check_groups(groups_raw(), N, REGISTRY, [ratified, rejected])
        (offered_again,) = [g for g in groups if g["members"][0]["id"] == IDS[0]]
        assert offered_again["key"] == rejected["key"]  # merge_proposals then leaves the ruling standing

    def test_detached_names_only_the_unattached_members_of_this_run(self):
        prior = [self.ratified(IDS[0], IDS[1], "n-out-of-range"), self.ratified(IDS[1], key="g-bbbbbbbbbbbb"),
                 {"key": "g-cccccccccccc", "kind": "new", "status": "pending", "members": [{"id": IDS[2]}]}]
        found = thread_check.detached(prior, [N[0], N[1], N[2]])
        assert [d["note"].note_id for d in found] == [IDS[0], IDS[1]]  # IDS[2] is only pending; out-of-range unjudged
        assert [p["key"] for p in found[1]["groups"]] == [sha12([IDS[0], IDS[1], "n-out-of-range"]), "g-bbbbbbbbbbbb"]
        assert thread_check.detached(prior, []) == []

    def test_detached_lines_say_what_became_of_the_note(self):
        prior = [self.ratified(IDS[0]), self.ratified(IDS[1], key="g-bbbbbbbbbbbb"), self.ratified(IDS[2], key="g-cccccccccccc"),
                 {"key": "g-pppppppppppp", "kind": "single", "status": "pending", "members": [{"id": IDS[0]}]},
                 {"key": "g-rrrrrrrrrrrr", "kind": "single", "status": "rejected", "members": [{"id": IDS[1]}]}]
        lines = thread_check.detached_lines(prior, thread_check.detached(prior, N))
        assert len(lines) == 3 and all("ratified but no longer attached (alias removed?)" in ln for ln in lines)
        assert "offered again as pending proposal g-pppppppppppp" in lines[0] and "thread t-alpha" in lines[0]
        assert "g-rrrrrrrrrrrr is rejected, so it is not offered again" in lines[1]
        assert "thread-propose" in lines[2]

    def test_now_attached_lines_name_pending_proposals_whose_notes_all_attach(self):
        prior = [{"key": "g-111111111111", "kind": "single", "title": "Alpha", "status": "pending", "members": [{"id": IDS[0]}]},
                 {"key": "g-222222222222", "kind": "new", "status": "pending", "members": [{"id": IDS[1]}, {"id": IDS[2]}]},
                 {"key": "g-333333333333", "kind": "single", "status": "rejected", "members": [{"id": IDS[0]}]}]
        lines = thread_check.now_attached_lines(prior, {IDS[0]: "t-alpha", IDS[1]: "t-alpha"}, {"t-alpha": "Alpha plan"})
        assert lines == ["pending proposal g-111111111111 (Alpha): now attached to Alpha plan; dropped from the queue"]

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

    # ── #524: a replaced group never orphans a note outside the run's range ──

    def pending(self, key, title, *members, source="old run"):
        return {"key": key, "kind": "new", "title": title, "status": "pending", "source": source,
                "members": [dict(m) if isinstance(m, dict) else {"id": m} for m in members]}

    def proposals_of(self, p):
        return yaml.safe_load(p.read_text(encoding="utf-8"))["proposals"]

    def test_out_of_range_members_of_a_replaced_group_are_kept_as_pending_singles(self, tmp_path):
        p = tmp_path / "t.yaml"
        far = {"id": "n-far0000000", "chapter": 60, "tag": "OPENED", "name": "Far", "text": "far one", "cite": "[ch 060 / 060.01]"}
        g = self.pending("g-111111111111", "Spans the edge", far, {"id": IDS[0], "chapter": 2})
        p.write_text(yaml.safe_dump({"proposals": [g]}), encoding="utf-8")
        stats = thread_check.merge_proposals(
            p, self.groups(new("Alpha", IDS[0], IDS[1])), "src", scope_ids=set(IDS), known_ids=set(IDS) | {far["id"]})
        ps = self.proposals_of(p)
        assert "g-111111111111" not in {e["key"] for e in ps}
        (single,) = [e for e in ps if far["id"] in _ids(e)]
        assert single["kind"] == "single" and single["status"] == "pending" and single["members"] == [far]
        assert single["key"] == group_key([far["id"]]) and single["title"] == "Far"
        assert single["source"] == "old run"  # provenance of the earlier run is not rewritten
        assert stats["replaced"] == 1
        assert stats["kept_out_of_range"] == [{"key": "g-111111111111", "title": "Spans the edge", "members": [far]}]

    def test_a_member_ruled_elsewhere_or_covered_by_another_entry_is_not_duplicated(self, tmp_path):
        p = tmp_path / "t.yaml"
        g = self.pending("g-111111111111", "Spans", "n-far0000001", "n-far0000002", IDS[0])
        ruled = {"key": "g-333333333333", "kind": "single", "status": "rejected", "members": [{"id": "n-far0000001"}]}
        p.write_text(yaml.safe_dump({"proposals": [g, ruled]}), encoding="utf-8")
        stats = thread_check.merge_proposals(p, self.groups(new("Alpha", IDS[0], IDS[1])), "src", scope_ids=set(IDS))
        ps = self.proposals_of(p)
        assert [e for e in ps if "n-far0000001" in _ids(e)] == [ruled]
        assert sum("n-far0000002" in _ids(e) for e in ps) == 1
        assert [m["id"] for r in stats["kept_out_of_range"] for m in r["members"]] == ["n-far0000002"]

    def test_a_member_that_exists_in_no_ranges_notes_is_dropped_and_reported(self, tmp_path):
        p = tmp_path / "t.yaml"
        g = self.pending("g-111111111111", "Spans", {"id": "n-vanished00", "chapter": 3}, {"id": IDS[0], "chapter": 2},
                         {"id": "n-far0000000", "chapter": 60})
        p.write_text(yaml.safe_dump({"proposals": [g]}), encoding="utf-8")
        stats = thread_check.merge_proposals(
            p, self.groups(new("Alpha", IDS[0], IDS[1])), "src", scope_ids=set(IDS),
            known_ids=set(IDS) | {"n-far0000000"})
        ids = {i for e in self.proposals_of(p) for i in _ids(e)}
        assert "n-vanished00" not in ids and "n-far0000000" in ids
        assert stats["gone"] == [{"key": "g-111111111111", "title": "Spans", "members": [{"id": "n-vanished00", "chapter": 3}]}]

    def test_a_member_re_extracted_in_this_range_but_alive_in_a_wider_one_is_kept(self, tmp_path):
        """Ids are per extraction: ch002-060 holds b under n-b; ch002-008 chunks it differently (n-b2)."""
        p = tmp_path / "t.yaml"
        g = self.pending("g-aaaaaaaaaaaa", "T", {"id": "n-a", "chapter": 3, "name": "A"}, {"id": "n-b", "chapter": 6, "name": "B"})
        p.write_text(yaml.safe_dump({"proposals": [g]}), encoding="utf-8")
        stats = thread_check.merge_proposals(
            p, [], "narrow", scope_ids={"n-a", "n-b2"}, known_ids={"n-a", "n-b", "n-b2"})
        ps = self.proposals_of(p)
        assert [_ids(e) for e in ps] == [["n-b"]] and ps[0]["kind"] == "single" and ps[0]["status"] == "pending"
        assert stats["gone"] == [] and [m["id"] for r in stats["kept_out_of_range"] for m in r["members"]] == ["n-b"]

    def test_a_pending_entry_with_no_member_in_any_ranges_notes_is_kept_untouched_and_reported(self, tmp_path):
        p = tmp_path / "t.yaml"
        old_single = {**self.pending("g-bbbbbbbbbbbb", "Far", {"id": "n-far", "chapter": 40}), "kind": "single"}
        partial = self.pending("g-cccccccccccc", "Half", {"id": "n-gone", "chapter": 40}, {"id": "n-live", "chapter": 41})
        ruled = {**self.pending("g-dddddddddddd", "Ruled", {"id": "n-gone2"}), "status": "deferred"}
        p.write_text(yaml.safe_dump({"proposals": [old_single, partial, ruled]}), encoding="utf-8")
        stats = thread_check.merge_proposals(p, [], "wide", scope_ids={"n-far2"}, known_ids={"n-far2", "n-live"})
        assert self.proposals_of(p) == [old_single, partial, ruled]  # nothing is deleted for having no note on disk
        assert stats["stale"] == [{"key": "g-bbbbbbbbbbbb", "title": "Far", "ids": ["n-far"]}]  # only a wholly missing pending one

    def test_nothing_is_judged_gone_or_stale_without_known_ids(self, tmp_path):
        p = tmp_path / "t.yaml"
        g = self.pending("g-111111111111", "Spans", "n-x", IDS[0])
        lone = self.pending("g-222222222222", "Lone", "n-y")
        p.write_text(yaml.safe_dump({"proposals": [g, lone]}), encoding="utf-8")
        stats = thread_check.merge_proposals(p, [], "src", scope_ids={IDS[0]})
        assert {i for e in self.proposals_of(p) for i in _ids(e)} == {"n-x", "n-y"}
        assert stats["gone"] == [] and stats["stale"] == []

    def test_merging_after_a_narrower_run_is_a_fixed_point_and_the_wider_run_regroups_the_singles(self, tmp_path):
        p = tmp_path / "t.yaml"
        g = self.pending("g-111111111111", "Spans", "n-far0000000", IDS[0])
        p.write_text(yaml.safe_dump({"proposals": [g]}), encoding="utf-8")
        gs = self.groups(new("Alpha", IDS[0], IDS[1]))
        thread_check.merge_proposals(p, gs, "src", scope_ids=set(IDS))
        first = p.read_bytes()
        thread_check.merge_proposals(p, gs, "src", scope_ids=set(IDS))
        assert p.read_bytes() == first
        # the wider run now has the far note in scope: its single is replaced by whatever that run proposes
        wide = set(IDS) | {"n-far0000000"}
        thread_check.merge_proposals(p, [], "src", scope_ids=wide)
        assert not any("n-far0000000" in _ids(e) for e in self.proposals_of(p))

    def test_invariant_no_pending_note_leaves_the_queue_whatever_the_ranges(self, tmp_path):
        """Every note in a pending proposal before a run is in some proposal after it, or attached."""
        p = tmp_path / "t.yaml"
        wide = [f"n-{i:010x}" for i in range(12)]
        chapter = {nid: 50 + i for i, nid in enumerate(wide)}

        def member(nid):
            return {"id": nid, "chapter": chapter[nid], "tag": "OPENED", "name": nid, "text": nid, "cite": ""}

        def grouped(*ids):
            return {"key": group_key(ids), "kind": "new", "title": "G " + ids[0], "members": [member(i) for i in ids]}

        first = [grouped(*wide[0:4]), grouped(*wide[4:8]), grouped(*wide[8:12])]
        thread_check.merge_proposals(p, first, "wide", scope_ids=set(wide))
        queue = {i for e in self.proposals_of(p) for i in _ids(e)}
        assert queue == set(wide)
        # a sequence of narrower, overlapping runs; like thread-propose, each proposes every unattached note
        # of its scope (one group, the rest singles), and one note becomes attached to a ratified thread
        runs = [(wide[3:6], wide[4:6]), (wide[6:10], wide[7:9]), (wide[0:3], wide[0:3]), (wide[2:9], wide[2:9])]
        attached_now = {wide[8]}
        for scope, regroup in runs:
            before = {i for e in self.proposals_of(p) for i in _ids(e)}
            offered = [n for n in scope if n not in attached_now]
            group = [i for i in regroup if i in offered]
            gs = ([grouped(*group)] if len(group) > 1 else []) + [
                grouped(i) for i in offered if i not in group or len(group) < 2]
            thread_check.merge_proposals(p, gs, "narrow", scope_ids=set(scope), known_ids=set(wide))
            after = {i for e in self.proposals_of(p) for i in _ids(e)}
            assert before - after <= attached_now, f"orphaned {sorted((before - after) - attached_now)}"
            assert len([i for e in self.proposals_of(p) for i in _ids(e)]) == len(after)  # and none twice

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

    def test_a_narrower_overlapping_range_keeps_the_out_of_range_notes_of_a_replaced_group(self, tcamp):
        """#524: ch002-004 groups the Carver notes; a later ch003-004 run must not lose the ch002 one."""
        root, tm = tcamp
        empty_registry(root)
        assert propose(root)[0] == 0
        carver = next(p for p in proposals(root) if p["title"] == "The Carver's march")
        assert [m["chapter"] for m in carver["members"]] == [2, 3, 4]
        before = {m["id"] for p in proposals(root) for m in p["members"]}

        narrow = ["--config", str(root / "config" / "config.yaml"), "--summaries-dir", str(root / "docs" / "summaries"),
                  "--since", "3", "--until", "4"]
        assert cs.run_cli(["build", *narrow])[0] == 0
        rc, out, err = cs.run_cli(["extract", *narrow[:-4], "--since", "3", "--until", "4", "--chunk-chars", "1", *BACKEND])
        assert rc == 0, out + err
        rc, out, err = cs.run_cli(["thread-propose", *narrow, *BACKEND])
        assert rc == 0, out + err

        ps = proposals(root)
        after = {m["id"] for p in ps for m in p["members"]}
        assert before <= after  # nothing that was queued left the queue
        assert carver["key"] not in {p["key"] for p in ps}  # the group was replaced...
        (kept,) = [p for p in ps if p["members"][0]["chapter"] == 2 and p["members"][0]["name"] == "The Carver's march"]
        assert kept["kind"] == "single" and kept["status"] == "pending"  # ...and its ch002 member survives
        # the run says so, in the report and on the terminal
        report = (cp.range_dir(root).parent / "ch003-004" / "state" / "threads" / "propose_report.md").read_text(encoding="utf-8")
        assert carver["key"] in report and kept["members"][0]["id"] in report and "outside the run's range" in report
        assert carver["key"] in out and kept["members"][0]["id"] in out

    def test_known_note_ids_spans_every_ranges_notes(self, tcamp):
        root, _ = tcamp
        assert thread_propose.known_note_ids(cp.range_dir(root)) == set(all_note_ids(root))
        sibling = cp.range_dir(root).parent / "ch003-004"
        shutil.copytree(cp.range_dir(root) / "state" / "notes", sibling / "state" / "notes")
        assert thread_propose.known_note_ids(sibling) == set(all_note_ids(root))  # sees the sibling range too

    def test_a_pending_proposal_with_no_note_on_disk_is_kept_and_reported_every_run(self, tcamp):
        """#524: a single kept from a wide range that was later re-extracted (or deleted) is named, not deleted."""
        root, tm = tcamp
        empty_registry(root)
        stale = {"key": "g-eeeeeeeeeeee", "kind": "single", "title": "Old far note", "status": "pending",
                 "source": "summary_native ch002-070 run X",
                 "members": [{"id": "n-reextracted", "chapter": 40, "tag": "OPENED", "name": "Old far note"}]}
        proposals_path(root).parent.mkdir(parents=True, exist_ok=True)
        proposals_path(root).write_text(yaml.safe_dump({"proposals": [stale]}), encoding="utf-8")
        for _ in range(2):  # reported on every run, not once
            rc, out, err = propose(root)
            assert rc == 0, out + err
            assert stale in proposals(root)
            report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
            for text in (report, out):
                assert "g-eeeeeeeeeeee" in text and "n-reextracted" in text
                assert "none of its notes is in any range's notes on disk" in text
                assert "reject it on the Threads page" in text
                assert "retired" not in text and "nothing was lost" not in text

    def test_an_unreadable_notes_file_in_another_range_makes_the_run_judge_nothing_missing(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        assert propose(root)[0] == 0
        wide = cp.range_dir(root).parent / "ch002-060"
        bad = wide / "state" / "notes" / "chunk01.002-060.checked.json"
        bad.parent.mkdir(parents=True)
        bad.write_text('{"cache_key": "x", "notes": [', encoding="utf-8")  # truncated
        ids, unreadable = thread_propose.scan_note_ids(cp.range_dir(root))
        assert ids is None and unreadable == [bad] and thread_propose.known_note_ids(cp.range_dir(root)) is None
        carver = next(p for p in proposals(root) if p["title"] == "The Carver's march")
        far = {"key": "g-ffffffffffff", "kind": "new", "title": "Wide group", "status": "pending", "source": "w",
               "members": [{"id": "n-notinthisrun", "chapter": 40, "name": "W", "text": "t"}]}
        doc = yaml.safe_load(proposals_path(root).read_text(encoding="utf-8"))
        doc["proposals"].append(far)
        carver_member = carver["members"][0]["id"]
        for p in doc["proposals"]:
            if p["key"] == carver["key"]:
                p["members"].append({"id": "n-alsonotthere", "chapter": 40, "name": "X", "text": "t"})
        proposals_path(root).write_text(yaml.safe_dump(doc), encoding="utf-8")
        rc, out, err = propose(root)
        assert rc == 0, out + err
        ps = proposals(root)
        assert far in ps  # not reported as missing, not touched
        assert any("n-alsonotthere" in str(p) for p in ps)  # a replaced group's unknown member is kept, not dropped
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        assert "chunk01.002-060.checked.json" in report and "chunk01.002-060.checked.json" in err
        assert "none of its notes is in any range's notes" not in report and carver_member in str(ps)

    def test_a_dropped_member_is_written_out_in_full_in_the_report(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        assert propose(root)[0] == 0
        doc = yaml.safe_load(proposals_path(root).read_text(encoding="utf-8"))
        carver = next(p for p in doc["proposals"] if p["title"] == "The Carver's march")
        carver["members"].append({"id": "n-droppedone", "chapter": 40, "tag": "OPENED", "name": "Lost name",
                                  "text": "the lost statement", "cite": "[ch 040 / 040.01]"})
        proposals_path(root).write_text(yaml.safe_dump(doc), encoding="utf-8")
        rc, out, err = propose(root)
        assert rc == 0, out + err
        assert not any("n-droppedone" in str(p) for p in proposals(root))
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        assert "n-droppedone (ch 40, OPENED) Lost name — the lost statement [ch 040 / 040.01]" in report
        assert "note is in no range's notes on disk" in report

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

    # ── #525: an alias removed after a ratification ──

    CARVER_NAMES = ("The Carver's march", "Carver march")

    def ratify_carver(self, root, tm):
        """Propose against an empty registry, then ratify the Carver group with the real verb (the plan it
        derives, unedited), as the Threads page does. Returns the group entry as it was proposed."""
        empty_registry(root)
        assert propose(root)[0] == 0
        group = next(p for p in proposals(root) if p["title"] == "The Carver's march")
        self.ratify(root, group["key"])
        assert "Carver march" in yaml.safe_load(registry_path(root).read_text(encoding="utf-8"))["threads"][0]["aliases"]
        return next(p for p in proposals(root) if p["key"] == group["key"])

    def treg(self, root, *argv, stdin=None):
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        script = Path(__file__).resolve().parents[1] / "pipelines" / "grounding" / "thread_registry.py"
        return subprocess.run([sys.executable, str(script), "--registry", str(registry_path(root)), *argv],
                              capture_output=True, text=True, cwd=root, input=stdin, env=env)

    def ratify(self, root, key, **plan_edits):
        """`thread_registry ratify --key K`: derive the plan, apply the GM's edits, write it."""
        base = ["ratify", "--key", key, "--proposals", str(proposals_path(root))]
        r = self.treg(root, *base, "--emit-plan")
        assert r.returncode == 0, r.stderr
        plan = {**json.loads(r.stdout), **plan_edits}
        r = self.treg(root, *base, "--plan", "-", stdin=json.dumps(plan))
        assert r.returncode == 0, r.stderr + r.stdout
        return plan

    def drop_alias(self, root, alias="Carver march"):
        """What the GM does by hand: take an alias off a thread."""
        doc = yaml.safe_load(registry_path(root).read_text(encoding="utf-8"))
        for t in doc["threads"]:
            t["aliases"] = [a for a in t.get("aliases") or [] if a != alias]
        registry_path(root).write_text(yaml.safe_dump(doc), encoding="utf-8")

    def carver_pending(self, root):
        return [p for p in proposals(root) if p["status"] == "pending" and any(m["name"] == "Carver march" for m in p["members"])]

    def test_a_member_whose_alias_was_removed_is_reported_and_offered_again_as_a_pending_single(self, tcamp):
        root, tm = tcamp
        group = self.ratify_carver(root, tm)
        assert propose(root)[0] == 0
        assert [p for p in proposals(root) if p["status"] == "pending" and p["members"][0]["name"] in self.CARVER_NAMES] == []
        detached = [m for m in group["members"] if m["name"] == "Carver march"]
        assert detached  # the fixture names the thread both ways

        self.drop_alias(root)  # the GM removes the alias
        calls = len(tm.calls)
        rc, out, err = propose(root)
        assert rc == 0, out + err
        ps = proposals(root)
        for m in detached:
            (again,) = [p for p in ps if p["status"] == "pending" and [x["id"] for x in p["members"]] == [m["id"]]]
            assert again["kind"] == "single" and again["key"] != group["key"]
            assert again["reoffer"] == {"from_group": group["key"], "thread": "the-carvers-march"}
            assert m["id"] not in str(tm.calls[calls:])  # code offers it again; the model never saw it
        assert group in ps  # the ratified entry stays as it was: history
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        section = report.split("## Ratified but no longer attached (alias removed?)")[1].split("\n## ")[0]
        for m in detached:
            assert m["id"] in section and "ratified but no longer attached (alias removed?)" in section
            assert "offered again as pending proposal" in section
        assert group["key"] in section and "the-carvers-march" in section
        assert detached[0]["id"] in out  # and on the terminal

    def test_a_ratified_single_whose_alias_was_removed_is_offered_again_under_its_own_key(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        assert propose(root)[0] == 0
        member = next(m for p in proposals(root) for m in p["members"] if m["name"] == "Carver march")
        ratified = {"key": thread_check.group_key([member["id"]]), "kind": "single", "title": "Carver march",
                    "status": "ratified", "ruled_thread": "carver-march", "members": [member]}
        others = [p for p in proposals(root) if member["id"] not in [m["id"] for m in p["members"]]]
        proposals_path(root).write_text(yaml.safe_dump({"proposals": [ratified, *others]}), encoding="utf-8")
        assert propose(root)[0] == 0
        keys = [p["key"] for p in proposals(root)]
        assert len(keys) == len(set(keys)), "a key names one entry"
        (again,) = [p for p in proposals(root) if p["status"] == "pending" and member["id"] in str(p["members"])]
        assert again["key"] != ratified["key"] and again["kind"] == "single"
        assert ratified in proposals(root)

    def test_re_running_with_the_alias_still_missing_changes_nothing(self, tcamp):
        root, tm = tcamp
        self.ratify_carver(root, tm)
        self.drop_alias(root)
        assert propose(root)[0] == 0
        strip = lambda ps: [{k: v for k, v in p.items() if k != "source"} for p in ps]  # noqa: E731
        first = strip(proposals(root))
        assert propose(root)[0] == 0
        assert strip(proposals(root)) == first

    def test_the_alias_put_back_attaches_the_note_and_the_pending_single_leaves_the_queue_with_a_line_saying_so(self, tcamp):
        root, tm = tcamp
        group = self.ratify_carver(root, tm)
        self.drop_alias(root)
        assert propose(root)[0] == 0
        pending = [p for p in proposals(root) if p["status"] == "pending" and p["members"][0]["name"] == "Carver march"]
        assert pending
        assert self.treg(root, "alias", "--id", "the-carvers-march", "--alias", "Carver march").returncode == 0
        rc, out, err = propose(root)
        assert rc == 0, out + err
        ps = proposals(root)
        assert not any(p["key"] == q["key"] for q in pending for p in ps)
        assert group in ps
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        assert f"pending proposal {pending[0]['key']}" in report and "now attached to The Carver's march" in report
        section = report.split("## Ratified but no longer attached (alias removed?)")[1].split("\n## ")[0]
        assert "(none)" in section

    def test_one_ratification_settles_a_re_offer_for_good(self, tcamp):
        """The loop the reviewer found: ratifying a re-offered single into its thread restored no alias, so the
        note came back as re-offered-2, -3, ... Ratifying it with the plan the engine derives must end it."""
        root, tm = tcamp
        self.ratify_carver(root, tm)
        self.drop_alias(root)
        assert propose(root)[0] == 0
        (again,) = self.carver_pending(root)
        plan = json.loads(self.treg(root, "ratify", "--key", again["key"], "--proposals", str(proposals_path(root)),
                                    "--emit-plan").stdout)
        assert plan["thread"] == "the-carvers-march"  # the page's default: continues the thread it left
        self.ratify(root, again["key"])
        assert "Carver march" in yaml.safe_load(registry_path(root).read_text(encoding="utf-8"))["threads"][0]["aliases"]
        rc, out, err = propose(root)
        assert rc == 0, out + err
        assert self.carver_pending(root) == []
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        assert "ratified but no longer attached" not in report.split("## Ratified but no longer attached (alias removed?)")[1].split("\n## ")[0]
        assert not any("re-offered" in str(p) for p in proposals(root))

    def test_ratifying_a_re_offer_under_a_new_title_still_restores_the_alias(self, tcamp):
        root, tm = tcamp
        self.ratify_carver(root, tm)
        self.drop_alias(root)
        assert propose(root)[0] == 0
        (again,) = self.carver_pending(root)
        plan = json.loads(self.treg(root, "ratify", "--key", again["key"], "--proposals", str(proposals_path(root)),
                                    "--emit-plan").stdout)
        for k in ("thread",):
            plan.pop(k)
        plan.update(title="The horde marches", id="horde-marches", status="open")
        base = ["ratify", "--key", again["key"], "--proposals", str(proposals_path(root))]
        assert self.treg(root, *base, "--plan", "-", stdin=json.dumps(plan)).returncode == 0
        assert propose(root)[0] == 0
        assert self.carver_pending(root) == []  # "Carver march" is an alias of the new thread

    def test_an_ordinary_single_ratified_into_an_existing_thread_attaches_and_is_not_offered_again(self, tcamp):
        root, tm = tcamp
        # a registry with the Carver thread but WITHOUT the alias: "Carver march" notes are ordinary unattached ones
        self.drop_alias(root)
        assert propose(root)[0] == 0
        (single,) = self.carver_pending(root)
        assert single["kind"] == "single" and "reoffer" not in single
        self.ratify(root, single["key"], thread="carver-march")
        assert propose(root)[0] == 0
        assert self.carver_pending(root) == []
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        assert single["members"][0]["id"] not in report.split("## Ratified but no longer attached (alias removed?)")[1].split("\n## ")[0]

    def test_a_rejected_re_offer_is_not_offered_a_third_time(self, tcamp):
        root, tm = tcamp
        self.ratify_carver(root, tm)
        self.drop_alias(root)
        assert propose(root)[0] == 0
        doc = yaml.safe_load(proposals_path(root).read_text(encoding="utf-8"))
        for p in doc["proposals"]:
            if p["status"] == "pending" and p["members"][0]["name"] == "Carver march":
                p["status"] = "rejected"
        proposals_path(root).write_text(yaml.safe_dump(doc), encoding="utf-8")
        assert propose(root)[0] == 0
        assert not any(p["status"] == "pending" and p["members"][0]["name"] == "Carver march" for p in proposals(root))
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        assert "is rejected, so it is not offered again" in report

    # ── #529: splitting a group whose split-off note shares a ratified member's name ──

    def split_carver(self, root, keep_chapters=(2, 3), **plan_edits):
        """Propose against an empty registry, then ratify only ``keep_chapters`` of the 3-note Carver group with the
        real verb (the derived plan narrowed as the Threads page narrows it). Returns the group as proposed."""
        empty_registry(root)
        assert propose(root)[0] == 0
        group = next(p for p in proposals(root) if p["title"] == "The Carver's march")
        assert [m["chapter"] for m in group["members"]] == [2, 3, 4]
        base = ["ratify", "--key", group["key"], "--proposals", str(proposals_path(root))]
        plan = json.loads(self.treg(root, *base, "--emit-plan").stdout)
        rows = dict(zip(plan["members"], plan["log"]))
        keep = [m["id"] for m in group["members"] if m["chapter"] in keep_chapters]
        plan.update(members=keep, log=[rows[i] for i in keep], **plan_edits)
        r = self.treg(root, *base, "--plan", "-", stdin=json.dumps(plan))
        assert r.returncode == 0, r.stderr + r.stdout
        return group

    def attach_map(self, root):
        return json.loads((threads_dir(root) / "attach.json").read_text(encoding="utf-8"))

    def carver_thread(self, root):
        return yaml.safe_load(registry_path(root).read_text(encoding="utf-8"))["threads"][0]

    def test_a_split_off_note_sharing_a_ratified_members_name_is_not_attached_and_is_still_offered(self, tcamp):
        """The issue's acceptance scenario: ch004 "The Carver's march" shares the title of the ratified ch002 note."""
        root, tm = tcamp
        group = self.split_carver(root)
        off = group["members"][2]
        assert off["name"] == "The Carver's march"  # the same bold name as the ratified ch002 member
        assert self.carver_thread(root)["excluded_notes"] == [off["id"]]
        rest = next(p for p in proposals(root) if p["status"] == "pending" and [m["id"] for m in p["members"]] == [off["id"]])
        assert rest["split_from"] == group["key"]

        rc, out, err = propose(root)
        assert rc == 0, out + err
        att = self.attach_map(root)
        assert att["notes"][off["id"]] is None  # not attached: the GM's ruling beats the name
        assert att["threads"]["the-carvers-march"]["notes"] == [m["id"] for m in group["members"][:2]]
        assert att["threads"]["the-carvers-march"]["latest"] == group["members"][1]["id"]
        # ...and still offered for a ruling, not dropped as "now attached"
        (kept,) = [p for p in proposals(root) if p["status"] == "pending" and p["members"][0]["id"] == off["id"]]
        assert kept["key"] == rest["key"] and kept["kind"] == "single"
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        assert "now attached" not in report and "2 attached to 1 ratified thread" in out
        # a second run changes nothing
        strip = lambda ps: [{k: v for k, v in p.items() if k != "source"} for p in ps]  # noqa: E731
        first = strip(proposals(root))
        assert propose(root)[0] == 0 and strip(proposals(root)) == first

    def test_without_the_exclusion_the_same_note_attaches_by_name(self, tcamp):
        """The control for the test above: the field, not something else, is what holds the note out."""
        root, tm = tcamp
        group = self.split_carver(root)
        doc = yaml.safe_load(registry_path(root).read_text(encoding="utf-8"))
        del doc["threads"][0]["excluded_notes"]
        registry_path(root).write_text(yaml.safe_dump(doc), encoding="utf-8")
        assert propose(root)[0] == 0
        assert self.attach_map(root)["notes"][group["members"][2]["id"]] == "the-carvers-march"

    def test_the_planning_build_reads_the_exclusion_too(self, tcamp):
        root, tm = tcamp
        group = self.split_carver(root)
        _, results = notes.load_checked(cp.range_dir(root))
        att = thread_attach.attach(results, yaml.safe_load(registry_path(root).read_text(encoding="utf-8")))
        assert group["members"][2]["id"] in {n.note_id for n in att.unattached}

    def test_a_re_extracted_excluded_note_is_reported_never_removed(self, tcamp):
        root, tm = tcamp
        group = self.split_carver(root)
        off = group["members"][2]
        # re-extraction that changes the note's text changes its id (research R6): simulate it on disk
        for f in sorted(cp.range_dir(root).glob("state/notes/*.checked.json")):
            text = f.read_text(encoding="utf-8")
            if off["text"] in text:
                f.write_text(text.replace(off["text"], off["text"] + " Again."), encoding="utf-8")
        assert off["id"] not in set(all_note_ids(root))
        rc, out, err = propose(root)
        assert rc == 0, out + err
        line = (f"thread the-carvers-march: excluded note {off['id']} is in no range's notes on disk (re-extracted?) "
                f"— the split may no longer hold; re-check notes named The Carver's march")
        report = (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8")
        section = report.split("## Excluded notes no longer on disk (split may not hold)")[1].split("\n## ")[0]
        assert line in section and line in out
        assert self.carver_thread(root)["excluded_notes"] == [off["id"]]  # reported, not removed
        assert propose(root)[0] == 0 and line in propose(root)[1]  # on every run, not once
        # the new note really does attach by name now: that is what the report warns about
        assert len(self.attach_map(root)["threads"]["the-carvers-march"]["notes"]) == 3

    def test_nothing_is_reported_while_the_excluded_note_is_on_disk_or_a_notes_file_is_unreadable(self, tcamp):
        root, tm = tcamp
        group = self.split_carver(root)
        rc, out, err = propose(root)
        assert rc == 0 and "excluded note" not in out
        assert "(none)" in (threads_dir(root) / "propose_report.md").read_text(encoding="utf-8").split(
            "## Excluded notes no longer on disk (split may not hold)")[1].split("\n## ")[0]
        # an id that is on no disk, but with another range's notes file unreadable: judge nothing
        doc = yaml.safe_load(registry_path(root).read_text(encoding="utf-8"))
        doc["threads"][0]["excluded_notes"].append("n-nowhere000")
        registry_path(root).write_text(yaml.safe_dump(doc), encoding="utf-8")
        bad = cp.range_dir(root).parent / "ch002-060" / "state" / "notes" / "chunk01.002-060.checked.json"
        bad.parent.mkdir(parents=True)
        bad.write_text('{"cache_key": "x", "notes": [', encoding="utf-8")
        rc, out, err = propose(root)
        assert rc == 0 and "n-nowhere000" not in out
        bad.unlink()
        rc, out, err = propose(root)
        assert "excluded note n-nowhere000 is in no range's notes" in out

    def test_ratifying_the_excluded_note_into_the_same_thread_lifts_the_exclusion_and_it_attaches(self, tcamp):
        root, tm = tcamp
        group = self.split_carver(root)
        off = group["members"][2]
        assert propose(root)[0] == 0
        (rest,) = [p for p in proposals(root) if p["status"] == "pending" and p["members"][0]["id"] == off["id"]]
        self.ratify(root, rest["key"], thread="the-carvers-march")
        assert "excluded_notes" not in self.carver_thread(root)
        assert propose(root)[0] == 0
        assert self.attach_map(root)["notes"][off["id"]] == "the-carvers-march"
        assert not any(p["status"] == "pending" and p["members"][0]["id"] == off["id"] for p in proposals(root))

    def test_an_alias_only_a_left_out_member_carries_is_refused_and_the_registry_is_untouched(self, tcamp):
        root, tm = tcamp
        empty_registry(root)
        assert propose(root)[0] == 0
        group = next(p for p in proposals(root) if p["title"] == "The Carver's march")
        base = ["ratify", "--key", group["key"], "--proposals", str(proposals_path(root))]
        plan = json.loads(self.treg(root, *base, "--emit-plan").stdout)
        assert "Carver march" in plan["aliases_add"]
        keep = [m["id"] for m in group["members"] if m["chapter"] != 3]  # leave out the only "Carver march" note
        plan.update(members=keep, log=[plan["log"][0], plan["log"][2]])
        before = proposals_path(root).read_bytes()
        r = self.treg(root, *base, "--plan", "-", stdin=json.dumps(plan))
        assert r.returncode == 1 and "Carver march" in r.stderr and group["members"][1]["id"] in r.stderr
        assert not registry_path(root).exists()  # the registry was emptied above and the refusal wrote nothing
        assert proposals_path(root).read_bytes() == before

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
