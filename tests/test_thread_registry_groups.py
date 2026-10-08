"""Spec 034 User Story 3: the thread_registry verbs for group proposals (T023).

``ratify --key``, ``ratify --key --emit-plan`` and ``rule --key`` extend the 014 verbs (research R7). The
rules are the old ones, kept: the GM's edited ``--plan`` is required for a write, the registry is built in
memory, validated and written once, and a refused ratification writes nothing at all. ``--norm`` is
untouched; ``tests/test_thread_registry*.py`` pin it.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _thread_fixtures import (  # noqa: E402
    ADJUDICATION, CORPUS, PROPOSALS, REGISTRY, campaign, chapter, cli, proposals_doc, registry_doc, thread_fact,
)
from campaignlib.thread_registry import group_key  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def member(n: int, chapter_no: int, tag: str, name: str, text: str) -> dict:
    return {"id": f"n-{n:010x}", "chapter": chapter_no, "tag": tag, "name": name, "text": text,
            "cite": f"[ch {chapter_no:03d} / {chapter_no:03d}.01]"}


M1 = member(1, 2, "OPENED", "The Carver's march", "A horde is spoken of in whispers.")
M2 = member(2, 3, "ADVANCED", "Carver march", "Daz counts the banners from the ridge.")
M3 = member(3, 4, "ADVANCED", "The Carver's march", "The march breaks against the gate.")
M4 = member(4, 4, "RESOLVED", "Carver marching", "The march is over.")


def group(kind: str, members: list[dict], **extra) -> dict:
    return {"key": group_key([m["id"] for m in members]), "kind": kind, "members": members,
            "status": "pending", "source": "summary_native ch002-004 run R1", **extra}


NEW = group("new", [M3, M1, M2], title="The Carver's march")  # deliberately not in chapter order


def seed(tmp_path: Path, *entries: dict, threads: list[dict] | None = None) -> Path:
    c = campaign(tmp_path)
    p = c / PROPOSALS
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"proposals": list(entries)}, sort_keys=False), encoding="utf-8")
    if threads is not None:
        (c / REGISTRY).write_text(yaml.safe_dump({"version": 1, "threads": threads}, sort_keys=False), encoding="utf-8")
    return c


def emit(c: Path, key: str) -> dict:
    r = cli(c, "ratify", "--key", key, "--emit-plan")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def ratify(c: Path, key: str, plan: dict):
    return cli(c, "ratify", "--key", key, "--plan", "-", stdin=json.dumps(plan))


def entry(c: Path, key: str) -> dict:
    return next(e for e in proposals_doc(c)["proposals"] if e.get("key") == key)


def thread(c: Path, tid: str) -> dict:
    return next(t for t in registry_doc(c)["threads"] if t["id"] == tid)


OLD = {"id": "old", "title": "An old thread", "status": "open", "aliases": ["Ye olde"], "opened": 1,
       "log": [{"chapter": 1, "change": "opened", "summary": "Before."}]}


# ── --emit-plan ─────────────────────────────────────────────────────────────


class TestEmitPlan:
    def test_a_new_group_derives_log_rows_in_chapter_order_with_change_summary_and_cite(self, tmp_path):
        c = seed(tmp_path, NEW)
        plan = emit(c, NEW["key"])
        assert [r["chapter"] for r in plan["log"]] == [2, 3, 4]
        assert [r["change"] for r in plan["log"]] == ["opened", "advanced", "advanced"]
        assert [r["summary"] for r in plan["log"]] == [M1["text"], M2["text"], M3["text"]]
        assert [r["cite"] for r in plan["log"]] == [M1["cite"], M2["cite"], M3["cite"]]
        assert plan["title"] == "The Carver's march" and plan["id"] == "the-carvers-march"
        assert plan["status"] == "open" and plan["opened"] == 2
        assert "thread" not in plan

    def test_members_are_listed_and_aliases_are_the_distinct_names_minus_the_title(self, tmp_path):
        c = seed(tmp_path, NEW)
        plan = emit(c, NEW["key"])
        assert plan["members"] == [M1["id"], M2["id"], M3["id"]]
        assert plan["aliases_add"] == ["Carver march"]  # "The Carver's march" is the title; it appears twice

    def test_every_tag_maps_to_its_change(self, tmp_path):
        ms = [member(10, 2, "OPENED", "X", "a"), member(11, 3, "ADVANCED", "X", "b"),
              member(12, 4, "RESOLVED", "X", "c"), member(13, 5, "ABANDONED", "X", "d")]
        g = group("new", ms, title="X")
        c = seed(tmp_path, g)
        assert [r["change"] for r in emit(c, g["key"])["log"]] == ["opened", "advanced", "resolved", "abandoned"]

    def test_a_continues_group_names_the_thread_and_has_no_title(self, tmp_path):
        g = group("continues", [M2, M3], thread="old")
        c = seed(tmp_path, g, threads=[OLD])
        plan = emit(c, g["key"])
        assert plan["thread"] == "old" and "title" not in plan and "id" not in plan
        assert [r["chapter"] for r in plan["log"]] == [3, 4] and plan["members"] == [M2["id"], M3["id"]]
        assert plan["aliases_add"] == ["Carver march", "The Carver's march"]

    def test_a_single_derives_a_new_thread_from_its_one_note(self, tmp_path):
        g = group("single", [M2], title="Carver march")
        c = seed(tmp_path, g)
        plan = emit(c, g["key"])
        assert plan["title"] == "Carver march" and plan["aliases_add"] == [] and len(plan["log"]) == 1

    def test_emit_plan_writes_nothing(self, tmp_path):
        c = seed(tmp_path, NEW)
        before = (c / PROPOSALS).read_bytes()
        emit(c, NEW["key"])
        assert (c / PROPOSALS).read_bytes() == before and not (c / REGISTRY).exists()

    def test_an_unknown_key_is_an_error(self, tmp_path):
        c = seed(tmp_path, NEW)
        r = cli(c, "ratify", "--key", "g-000000000000", "--emit-plan")
        assert r.returncode != 0 and "g-000000000000" in r.stderr

    def test_ratify_needs_exactly_one_of_norm_or_key(self, tmp_path):
        c = seed(tmp_path, NEW)
        assert cli(c, "ratify", "--emit-plan").returncode != 0
        assert cli(c, "ratify", "--norm", "x", "--key", NEW["key"], "--emit-plan").returncode != 0


# ── ratify --key --plan ─────────────────────────────────────────────────────


class TestRatify:
    def test_a_new_thread_gets_its_log_rows_with_cites_and_its_aliases_in_one_write(self, tmp_path):
        c = seed(tmp_path, NEW)
        r = ratify(c, NEW["key"], emit(c, NEW["key"]))
        assert r.returncode == 0, r.stderr
        t = thread(c, "the-carvers-march")
        assert t["title"] == "The Carver's march" and t["status"] == "open" and t["opened"] == 2
        assert t["aliases"] == ["Carver march"]
        assert t["log"] == [
            {"chapter": 2, "change": "opened", "summary": M1["text"], "cite": M1["cite"]},
            {"chapter": 3, "change": "advanced", "summary": M2["text"], "cite": M2["cite"]},
            {"chapter": 4, "change": "advanced", "summary": M3["text"], "cite": M3["cite"]},
        ]
        e = entry(c, NEW["key"])
        assert e["status"] == "ratified" and e["ruled_thread"] == "the-carvers-march"
        assert cli(c, "check").returncode == 0  # a `cite` on a log row passes check_registry

    def test_the_gms_edits_are_what_is_written(self, tmp_path):
        c = seed(tmp_path, NEW)
        plan = emit(c, NEW["key"])
        plan.update(title="The march of the Carver", id="carver-march", status="open", aliases_add=["Carver march", "The horde"])
        plan["log"][0]["summary"] = "Edited by the GM."
        assert ratify(c, NEW["key"], plan).returncode == 0
        t = thread(c, "carver-march")
        assert t["title"] == "The march of the Carver" and t["aliases"] == ["Carver march", "The horde"]
        assert t["log"][0]["summary"] == "Edited by the GM."

    def test_a_continues_plan_appends_log_rows_and_aliases_to_the_existing_thread(self, tmp_path):
        g = group("continues", [M2, M3], thread="old")
        c = seed(tmp_path, g, threads=[OLD])
        r = ratify(c, g["key"], emit(c, g["key"]))
        assert r.returncode == 0, r.stderr
        assert [t["id"] for t in registry_doc(c)["threads"]] == ["old"]  # no second thread
        t = thread(c, "old")
        assert [row["chapter"] for row in t["log"]] == [1, 3, 4]
        assert t["log"][0] == OLD["log"][0]
        assert t["aliases"] == ["Ye olde", "Carver march", "The Carver's march"]
        assert entry(c, g["key"])["ruled_thread"] == "old"

    def test_a_plan_may_make_any_proposal_continue_a_thread(self, tmp_path):
        g = group("new", [M2, M3], title="Whatever")
        c = seed(tmp_path, g, threads=[OLD])
        plan = emit(c, g["key"])
        for k in ("id", "title", "opened"):
            plan.pop(k, None)
        plan["thread"] = "old"
        assert ratify(c, g["key"], plan).returncode == 0
        assert [t["id"] for t in registry_doc(c)["threads"]] == ["old"] and len(thread(c, "old")["log"]) == 3

    def test_an_identical_row_already_on_the_thread_is_not_duplicated_and_the_note_says_so(self, tmp_path):
        row = {"chapter": 3, "change": "advanced", "summary": M2["text"]}
        old = {**OLD, "log": OLD["log"] + [row]}
        g = group("continues", [M2, M3], thread="old")
        c = seed(tmp_path, g, threads=[old])
        r = ratify(c, g["key"], emit(c, g["key"]))
        assert r.returncode == 0 and "already" in r.stdout
        assert [(x["chapter"], x["summary"]) for x in thread(c, "old")["log"]].count((3, M2["text"])) == 1

    def test_two_notes_of_one_chapter_and_tag_both_become_rows(self, tmp_path):
        a, b = member(20, 5, "ADVANCED", "X", "first"), member(21, 5, "ADVANCED", "X", "second")
        g = group("new", [a, b], title="X")
        c = seed(tmp_path, g)
        assert ratify(c, g["key"], emit(c, g["key"])).returncode == 0
        assert [r["summary"] for r in thread(c, "x")["log"]] == ["first", "second"]

    def test_a_subset_plan_splits_and_the_remainder_is_a_new_pending_group(self, tmp_path):
        c = seed(tmp_path, NEW)
        plan = emit(c, NEW["key"])
        plan["members"] = [M1["id"], M2["id"]]
        plan["log"] = plan["log"][:2]
        plan["aliases_add"] = ["Carver march"]
        r = ratify(c, NEW["key"], plan)
        assert r.returncode == 0, r.stderr
        assert [row["chapter"] for row in thread(c, "the-carvers-march")["log"]] == [2, 3]
        done = entry(c, NEW["key"])
        assert done["status"] == "ratified" and [m["id"] for m in done["members"]] == [M1["id"], M2["id"]]
        rest_key = group_key([M3["id"]])
        rest = entry(c, rest_key)
        assert rest["status"] == "pending" and [m["id"] for m in rest["members"]] == [M3["id"]]
        assert rest["kind"] == "single" and rest_key in r.stdout

    def test_a_larger_remainder_keeps_the_kind_and_the_suggestion(self, tmp_path):
        g = group("continues", [M1, M2, M3], thread="old")
        c = seed(tmp_path, g, threads=[OLD])
        plan = emit(c, g["key"])
        plan["members"] = [M1["id"]]
        plan["log"] = plan["log"][:1]
        assert ratify(c, g["key"], plan).returncode == 0
        rest = entry(c, group_key([M2["id"], M3["id"]]))
        assert rest["kind"] == "continues" and rest["thread"] == "old" and rest["status"] == "pending"

    def test_the_whole_member_list_leaves_no_remainder(self, tmp_path):
        c = seed(tmp_path, NEW)
        assert ratify(c, NEW["key"], emit(c, NEW["key"])).returncode == 0
        assert len(proposals_doc(c)["proposals"]) == 1

    def test_ratify_without_a_plan_is_refused(self, tmp_path):
        c = seed(tmp_path, NEW)
        r = cli(c, "ratify", "--key", NEW["key"])
        assert r.returncode != 0 and "--plan" in r.stderr and not (c / REGISTRY).exists()

    # refusals write nothing at all

    def refused(self, c: Path, key: str, plan: dict, *needles: str):
        before = [(c / p).read_bytes() if (c / p).exists() else None for p in (REGISTRY, PROPOSALS)]
        r = ratify(c, key, plan)
        assert r.returncode != 0, r.stdout
        for needle in needles:
            assert needle in r.stderr, r.stderr
        after = [(c / p).read_bytes() if (c / p).exists() else None for p in (REGISTRY, PROPOSALS)]
        assert after == before, "a refused ratification must write nothing"

    def test_an_alias_colliding_with_another_threads_title_is_refused(self, tmp_path):
        c = seed(tmp_path, NEW, threads=[OLD])
        plan = emit(c, NEW["key"])
        plan["aliases_add"] = ["Carver march", "An Old Thread"]
        self.refused(c, NEW["key"], plan, "An Old Thread", "old")

    def test_an_alias_colliding_with_another_threads_alias_is_refused(self, tmp_path):
        c = seed(tmp_path, NEW, threads=[OLD])
        plan = emit(c, NEW["key"])
        plan["aliases_add"] = ["ye olde"]
        self.refused(c, NEW["key"], plan, "ye olde", "old")

    def test_a_continues_alias_colliding_with_a_third_thread_is_refused_but_its_own_is_fine(self, tmp_path):
        other = {"id": "other", "title": "Carver march", "status": "open", "aliases": [], "opened": 1,
                 "log": [{"chapter": 1, "change": "opened", "summary": "x"}]}
        g = group("continues", [M2, M3], thread="old")
        c = seed(tmp_path, g, threads=[OLD, other])
        plan = emit(c, g["key"])
        self.refused(c, g["key"], plan, "Carver march", "other")
        plan["aliases_add"] = ["Ye olde", "The Carver's march"]  # its own alias again is not a collision
        assert ratify(c, g["key"], plan).returncode == 0

    def test_a_new_title_matching_an_existing_thread_is_refused(self, tmp_path):
        c = seed(tmp_path, NEW, threads=[OLD])
        plan = emit(c, NEW["key"])
        plan.update(title="Ye Olde", aliases_add=[])
        self.refused(c, NEW["key"], plan, "Ye Olde", "old")

    def test_a_new_id_that_exists_is_refused(self, tmp_path):
        c = seed(tmp_path, NEW, threads=[OLD])
        plan = emit(c, NEW["key"])
        plan["id"] = "old"
        self.refused(c, NEW["key"], plan, "'old' already exists")

    def test_a_continues_thread_that_does_not_exist_is_refused(self, tmp_path):
        g = group("continues", [M2, M3], thread="gone")
        c = seed(tmp_path, g, threads=[OLD])
        self.refused(c, g["key"], emit(c, g["key"]), "gone")

    @pytest.mark.parametrize("bad", [0, -1, None, "3", True])
    def test_a_log_chapter_below_one_or_not_an_integer_is_refused(self, tmp_path, bad):
        c = seed(tmp_path, NEW)
        plan = emit(c, NEW["key"])
        plan["log"][1]["chapter"] = bad
        self.refused(c, NEW["key"], plan, "log row 2")

    def test_an_empty_log_or_a_bad_change_is_refused(self, tmp_path):
        c = seed(tmp_path, NEW)
        plan = emit(c, NEW["key"])
        self.refused(c, NEW["key"], {**plan, "log": []}, "log")
        bad = json.loads(json.dumps(plan))
        bad["log"][0]["change"] = "exploded"
        self.refused(c, NEW["key"], bad, "exploded")

    def test_members_must_be_a_non_empty_subset_of_the_proposals(self, tmp_path):
        c = seed(tmp_path, NEW)
        plan = emit(c, NEW["key"])
        self.refused(c, NEW["key"], {**plan, "members": []}, "members")
        self.refused(c, NEW["key"], {k: v for k, v in plan.items() if k != "members"}, "members")
        self.refused(c, NEW["key"], {**plan, "members": [M1["id"], "n-notamember"]}, "n-notamember")
        self.refused(c, NEW["key"], {**plan, "members": [M1["id"], M1["id"]]}, "twice")

    def test_a_status_of_resolved_without_a_closing_chapter_is_refused_by_check(self, tmp_path):
        c = seed(tmp_path, NEW)
        plan = emit(c, NEW["key"])
        plan["status"] = "resolved"
        self.refused(c, NEW["key"], plan, "resolved")
        plan["resolved"] = 4
        assert ratify(c, NEW["key"], plan).returncode == 0
        assert thread(c, "the-carvers-march")["resolved"] == 4

    def test_a_ratified_or_rejected_group_cannot_be_ratified_again(self, tmp_path):
        c = seed(tmp_path, NEW)
        plan = emit(c, NEW["key"])
        assert ratify(c, NEW["key"], plan).returncode == 0
        self.refused(c, NEW["key"], {**plan, "id": "another", "title": "Another"}, "ratified")
        g2 = {**group("new", [M4], title="Four"), "status": "rejected"}
        c2 = seed(tmp_path / "two", g2)
        self.refused(c2, g2["key"], {"id": "four", "title": "Four", "members": [M4["id"]],
                                     "log": [{"chapter": 4, "change": "resolved", "summary": "x"}]}, "rejected")

    def test_the_plan_must_be_json(self, tmp_path):
        c = seed(tmp_path, NEW)
        r = cli(c, "ratify", "--key", NEW["key"], "--plan", "-", stdin="not json")
        assert r.returncode != 0 and "JSON" in r.stderr

    def test_the_ratified_aliases_attach_the_notes_by_name(self, tmp_path):
        from pipelines.summary_native import notes, thread_attach

        c = seed(tmp_path, NEW)
        assert ratify(c, NEW["key"], emit(c, NEW["key"])).returncode == 0
        registry = registry_doc(c)
        for name, expect in (("The Carver's march", True), ("Carver march", True), ("Carver marching", False)):
            n = notes.Note("thread", f"- [ADVANCED] **{name}** — x [ch 005 / 005.01]", 5, "005-005", tag="ADVANCED", subject=name)
            att = thread_attach.attach([notes.CheckedChunk("005-005", [n])], registry)
            assert (att.by_note[n.note_id] == "the-carvers-march") is expect


# ── rule --key ──────────────────────────────────────────────────────────────


class TestRule:
    @pytest.mark.parametrize("status", ["rejected", "deferred"])
    def test_a_ruling_persists_and_nothing_else_changes(self, tmp_path, status):
        other = group("new", [M4], title="Four")
        c = seed(tmp_path, NEW, other)
        r = cli(c, "rule", "--key", NEW["key"], "--status", status, "--note", "because")
        assert r.returncode == 0, r.stderr
        e = entry(c, NEW["key"])
        assert e["status"] == status and e["note"] == "because" and e["members"] == NEW["members"]
        assert entry(c, other["key"])["status"] == "pending"

    def test_a_deferred_group_goes_into_the_adjudication_bundle_with_its_members(self, tmp_path):
        c = seed(tmp_path, NEW)
        assert cli(c, "rule", "--key", NEW["key"], "--status", "deferred", "--note", "ask").returncode == 0
        bundle = json.loads((c / ADJUDICATION).read_text(encoding="utf-8"))
        (e,) = bundle["entries"]
        assert e["key"] == NEW["key"] and e["note"] == "ask" and len(e["evidence"]) == 3
        assert cli(c, "rule", "--key", NEW["key"], "--status", "deferred").returncode == 0
        assert len(json.loads((c / ADJUDICATION).read_text(encoding="utf-8"))["entries"]) == 1

    def test_ratifying_by_rule_is_refused_it_takes_a_plan(self, tmp_path):
        c = seed(tmp_path, NEW)
        r = cli(c, "rule", "--key", NEW["key"], "--status", "ratified")
        assert r.returncode != 0 and "ratify" in r.stderr
        assert entry(c, NEW["key"])["status"] == "pending"

    def test_a_bad_ruling_or_an_unknown_key_is_refused(self, tmp_path):
        c = seed(tmp_path, NEW)
        r = cli(c, "rule", "--key", NEW["key"], "--status", "maybe")
        assert r.returncode != 0 and "bad ruling 'maybe'" in r.stderr
        r = cli(c, "rule", "--key", "g-000000000000", "--status", "rejected")
        assert r.returncode != 0 and "g-000000000000" in r.stderr

    def test_rule_takes_one_key_or_one_norm_never_both_or_neither(self, tmp_path):
        c = seed(tmp_path, NEW)
        assert cli(c, "rule", "--status", "rejected").returncode != 0
        assert cli(c, "rule", "--key", NEW["key"], "--norm", "x", "--status", "rejected").returncode != 0

    def test_a_rejected_group_is_a_ruling_the_proposals_file_keeps(self, tmp_path):
        c = seed(tmp_path, NEW)
        assert cli(c, "rule", "--key", NEW["key"], "--status", "rejected").returncode == 0
        assert yaml.safe_load((c / PROPOSALS).read_text(encoding="utf-8"))["proposals"][0]["status"] == "rejected"


# ── the harvest and the listing keep working beside group entries ───────────


class TestAlongsideTheEnsembleHarvest:
    def test_a_harvest_re_propose_keeps_group_entries_untouched(self, tmp_path):
        done = {**NEW, "status": "ratified", "ruled_thread": "x"}
        c = seed(tmp_path, done)
        chapter(c, 30, [thread_fact("A thing", "It happened.")])
        r = cli(c, "propose", "--corpus", CORPUS)
        assert r.returncode == 0, r.stderr
        doc = proposals_doc(c)["proposals"]
        assert [p["norm"] for p in doc if "norm" in p] == ["a-thing"]
        assert [p for p in doc if p.get("key")] == [done]

    def test_proposals_json_lists_both_shapes_and_counts_them(self, tmp_path):
        c = seed(tmp_path, NEW, {"norm": "a-thing", "title": "A thing", "status": "pending", "chapters": [3], "evidence": []})
        r = cli(c, "proposals", "--json")
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert len(payload["proposals"]) == 2 and payload["counts"] == {"pending": 2}

    def test_the_norm_verbs_do_not_see_group_entries(self, tmp_path):
        c = seed(tmp_path, NEW)
        r = cli(c, "rule", "--norm", NEW["key"], "--status", "rejected")
        assert r.returncode != 0 and entry(c, NEW["key"])["status"] == "pending"


# ── only the thread_registry verbs open the registry for writing ────────────


def _py_files():
    skip = {".claude", "node_modules", ".git", "__pycache__", "tests", "specs", ".venv", "venv", "dist"}
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.endswith(".py"):
                yield Path(root) / f


def _touches_thread_registry(tree: ast.AST) -> bool:
    """Whether a module imports anything called ``thread_registry`` (the entity registry has its own
    ``save_registry``; this guard is about the thread registry's writer)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any("thread_registry" in a.name for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and ("thread_registry" in (node.module or "")
                                                 or any("thread_registry" in a.name for a in node.names)):
            return True
    return False


def test_only_thread_registry_defines_and_calls_save_registry():
    callers = []
    for p in _py_files():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        if p.relative_to(REPO).as_posix() == "pipelines/grounding/thread_registry.py" or not _touches_thread_registry(tree):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                if name == "save_registry":
                    callers.append(p.relative_to(REPO).as_posix())
    assert callers == [], f"only the thread_registry verbs may write the thread registry: {callers}"
    src = (REPO / "pipelines" / "grounding" / "thread_registry.py").read_text(encoding="utf-8")
    assert "def save_registry" in src


@pytest.mark.parametrize("name", ["thread_attach", "thread_check", "thread_propose"])
def test_the_propose_modules_never_open_the_registry_for_writing(name):
    src = (REPO / "pipelines" / "summary_native" / f"{name}.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            assert not any(m.startswith("pipelines.grounding") for m in mods), f"{name} imports the CLI: {mods}"
        if isinstance(node, ast.Call):
            f = node.func
            called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            assert called not in {"save_registry", "dump_registry"}, f"{name} calls {called}"
            # a write helper whose target is named like the registry
            if called in {"atomic_write_text", "write_text", "write_bytes", "open"} and node.args:
                first = ast.unparse(node.args[0]).lower()
                assert "registry" not in first or "proposal" in first, f"{name}: {called}({first}) may write the registry"
    assert "thread_registry.yaml" not in src
