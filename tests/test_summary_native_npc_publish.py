"""``summary_native.npc_publish`` (spec 032 T041/T042, FR-031*, R16).

Fixtures are built directly in a tmp campaign (draft + composed GM dossier + verify
file), not by running ``npc-draft``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from pipelines.summary_native import npc_compose, npc_publish, schema
from tests.conftest_npc import sha_tree

RANGE = "ch002-070"
PREFIX = schema.PUBLISH_HEADER_PREFIX
NOW = lambda: datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)  # noqa: E731
SECRET = "SECRET-CANARY-7731 — he sold them out\n"

BODY = (
    "---\nsubject: Jimjar\n---\n\n## Identity\n\nA deep gnome [manual 1] who guides. [ch 004 / 004.02]\n\n"
    "## History with the Party\n\n- Bets Eldeth he will win. [manual 2]\n- Joins them. [ch 002 / entry; ch 003 / 003.01]\n"
)


def draft_text(subject, run="20261007T101500Z"):
    return (
        f"<!-- summary_native npc draft | npc: {subject} | range: {RANGE} | run: {run} "
        f"| draft_key: k | manual sha256: m | model: x | backend: y -->\n" + BODY.replace("Jimjar", subject)
    )


class World:
    def __init__(self, tmp_path):
        self.root = tmp_path / "camp"
        self.rd = self.root / "docs/npcs/summary_native" / RANGE
        (self.rd / "draft").mkdir(parents=True)
        (self.root / "docs/npcs/authored").mkdir(parents=True)

    def npc(self, subject, stem=None, verdict="pass", secrets=SECRET, via="verify.md"):
        stem = stem or "npc_" + subject.lower().replace(" ", "-")
        slug = subject.lower().replace(" ", "-")
        (self.rd / "draft" / f"{stem}.md").write_text(draft_text(subject), encoding="utf-8")
        auth = self.root / "docs/npcs/authored" / f"{slug}.authored.yaml"
        auth.write_text(yaml.safe_dump({"subject": subject, "manual": ["a", "b"], "secrets": secrets}), encoding="utf-8")
        npc_compose.compose_gm(self.rd / "draft" / f"{stem}.md", auth, self.rd / "gm" / f"{stem}.md", subject, stem)
        if verdict and via == "verify.md":
            (self.rd / "draft" / f"{stem}.verify.md").write_text(
                f"# Verification: {subject}\n\n**Verdict: {verdict}**\n", encoding="utf-8")
        if verdict and via == "record":
            run = self.rd / "runs" / "20261007T101500Z"
            run.mkdir(parents=True, exist_ok=True)
            (run / "record.json").write_text(json.dumps(
                {"npcs": {stem: {"verify": {"verdict": verdict, "counts": {}}}}}), encoding="utf-8")
        return stem

    def handbuilt(self, slug, text="# Eelrich Vane\n\nHand built.  \nNo trailing newline"):
        p = self.root / "docs/npcs/authored" / f"{slug}.md"
        p.write_text(text, encoding="utf-8")
        return p

    def pub(self, **kw):
        return npc_publish.publish(self.root, self.rd, now=NOW, **kw)

    @property
    def npcs(self):
        return self.root / "docs/npcs"

    def log(self):
        return json.loads((self.npcs / "summary_native/publish_log.json").read_text(encoding="utf-8"))


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def reasons(results):
    return {r.name: r.reason for r in results if not r.published}


# ── Selection ───────────────────────────────────────────────────────────────

def test_no_selection_refuses_and_writes_nothing(w):
    w.npc("Jimjar")
    before = sha_tree(w.root)
    with pytest.raises(npc_publish.PublishRefusal, match="no selection"):
        w.pub()
    assert sha_tree(w.root) == before


def test_name_publishes_only_that_npc(w):
    w.npc("Jimjar"); w.npc("Eldeth")
    res = w.pub(names=["jimjar"])
    assert [(r.name, r.published, r.source) for r in res] == [("Jimjar", True, "summary_native")]
    assert (w.npcs / "jimjar.md").is_file() and not (w.npcs / "eldeth.md").exists()


def test_all_publishes_every_gm_dossier_in_range(w):
    w.npc("Jimjar"); w.npc("Eldeth"); w.handbuilt("eelrich-vane")
    res = w.pub(all_=True)
    assert sorted(r.slug for r in res if r.published) == ["eldeth", "jimjar"]
    assert not (w.npcs / "eelrich-vane.md").exists()


def test_authored_all_publishes_every_handbuilt_dossier(w):
    w.npc("Jimjar"); w.handbuilt("eelrich-vane"); w.handbuilt("ilvara-mizzrym", "# Ilvara\n")
    res = w.pub(authored_all=True)
    assert sorted((r.slug, r.source) for r in res if r.published) == [
        ("eelrich-vane", "hand-built"), ("ilvara-mizzrym", "hand-built")]
    assert not (w.npcs / "jimjar.md").exists()   # .authored.yaml is not a dossier


def test_unknown_name_is_a_per_npc_refusal_others_still_publish(w):
    w.npc("Jimjar")
    res = w.pub(names=["Nobody", "Jimjar"])
    assert "no GM dossier" in reasons(res)["Nobody"]
    assert (w.npcs / "jimjar.md").is_file()


def test_handbuilt_name_without_evidence_resolves_by_slug(w):
    w.handbuilt("eelrich-vane")
    res = w.pub(names=["Eelrich Vane"])
    assert res[0].published and res[0].source == "hand-built"


# ── Summary-native source ───────────────────────────────────────────────────

def test_summary_native_header_and_body(w):
    w.npc("Jimjar")
    w.pub(names=["Jimjar"])
    text = (w.npcs / "jimjar.md").read_text(encoding="utf-8")
    first, body = text.split("\n", 1)
    gm = (w.rd / "gm/npc_jimjar.md").read_text(encoding="utf-8")
    gm_head = gm.split("\n", 1)[0]
    draft_sha = gm_head.split("draft sha256: ")[1].split(" ")[0]
    auth_sha = gm_head.split("authored sha256: ")[1].split(" ")[0]
    assert first == (
        f"{PREFIX} | source: summary_native | npc: Jimjar | range: {RANGE} | draft run: 20261007T101500Z "
        f"| draft sha256: {draft_sha} | authored sha256: {auth_sha} | verify: pass "
        f"| published sha256: {npc_publish.sha256_text(body)} -->"
    )
    assert "[manual" not in text
    assert "A deep gnome [GM] who guides. [ch 004 / 004.02]" in body
    assert "- Bets Eldeth he will win. [GM]" in body
    assert "[ch 002 / entry; ch 003 / 003.01]" in body          # chapter citations untouched
    assert "## Secrets\n" + SECRET in body                      # Secrets included byte-for-byte
    assert body == npc_publish.rewrite_manual_citations(gm.split("\n", 1)[1])


def test_rewrite_manual_citations_only_touches_manual():
    t = "a [manual 1] b [manual 12] c [ch 001 / entry] d [manual x]"
    assert npc_publish.rewrite_manual_citations(t) == "a [GM] b [GM] c [ch 001 / entry] d [manual x]"


def test_verdict_from_record_when_no_verify_file(w):
    w.npc("Jimjar", via="record")
    assert w.pub(names=["Jimjar"])[0].published


def test_verify_file_wins_over_stale_record(w):
    stem = w.npc("Jimjar", verdict="fail", via="verify.md")
    run = w.rd / "runs" / "20260101T000000Z"; run.mkdir(parents=True)
    (run / "record.json").write_text(json.dumps({"npcs": {stem: {"verify": {"verdict": "pass"}}}}))
    assert "verification failed" in w.pub(names=["Jimjar"])[0].reason


# ── Hand-built source ───────────────────────────────────────────────────────

def test_handbuilt_copied_verbatim_with_header(w):
    src = w.handbuilt("eelrich-vane")
    w.pub(authored_all=True)
    text = (w.npcs / "eelrich-vane.md").read_text(encoding="utf-8")
    first, body = text.split("\n", 1)
    raw = src.read_text(encoding="utf-8")
    assert body == raw                                          # no trailing newline added
    sha = npc_publish.sha256_text(raw)
    assert first == (
        f"{PREFIX} | source: hand-built | path: docs/npcs/authored/eelrich-vane.md | sha256: {sha} "
        f"| verification: not applicable | published sha256: {sha} -->"
    )


# ── Refusals ────────────────────────────────────────────────────────────────

def test_both_sources_refuse_naming_both_paths_until_source_given(w):
    w.npc("Jimjar"); w.handbuilt("jimjar", "# Jimjar by hand\n")
    r = w.pub(names=["Jimjar"])[0]
    assert not r.published
    assert "npc_jimjar.md" in r.reason and "authored/jimjar.md" in r.reason and "--source" in r.reason
    assert not (w.npcs / "jimjar.md").exists()
    assert w.pub(names=["Jimjar"], source="hand-built")[0].source == "hand-built"
    assert "source: hand-built" in (w.npcs / "jimjar.md").read_text().split("\n", 1)[0]
    assert w.pub(names=["Jimjar"], source="summary_native", force=True)[0].source == "summary_native"


def test_source_with_nothing_behind_it_refuses(w):
    w.npc("Jimjar")
    r = w.pub(names=["Jimjar"], source="hand-built")[0]
    assert not r.published and "no hand-built dossier" in r.reason


def test_failed_verification_refuses_and_force_publishes_with_fail_forced(w):
    w.npc("Jimjar", verdict="fail")
    r = w.pub(names=["Jimjar"])[0]
    assert not r.published and "verification failed" in r.reason and "npc_jimjar.verify.md" in r.reason
    assert not (w.npcs / "jimjar.md").exists()
    r = w.pub(names=["Jimjar"], force=True)[0]
    assert r.published and r.forced == ("verification failed",)
    assert "| verify: fail(forced) |" in (w.npcs / "jimjar.md").read_text().split("\n", 1)[0]


def test_never_verified_refuses_like_a_failure(w):
    w.npc("Jimjar", verdict=None)
    r = w.pub(names=["Jimjar"])[0]
    assert not r.published and "not verified" in r.reason
    assert w.pub(names=["Jimjar"], force=True)[0].published
    assert "| verify: unverified(forced) |" in (w.npcs / "jimjar.md").read_text().split("\n", 1)[0]


def test_foreign_target_refuses_and_is_untouched(w):
    w.npc("Jimjar")
    (w.npcs / "jimjar.md").write_text("# my own Jimjar\n")
    r = w.pub(names=["Jimjar"])[0]
    assert not r.published and "not published by summary_native" in r.reason
    assert (w.npcs / "jimjar.md").read_text() == "# my own Jimjar\n"
    assert not (w.npcs / "summary_native/publish_log.json").exists()
    assert w.pub(names=["Jimjar"], force=True)[0].published
    assert (w.npcs / "jimjar.md").read_text().startswith(PREFIX)


def test_hand_edited_target_refuses_pointing_at_authored_file(w):
    w.npc("Jimjar")
    w.pub(names=["Jimjar"])
    p = w.npcs / "jimjar.md"
    p.write_text(p.read_text() + "edit\n")
    r = w.pub(names=["Jimjar"])[0]
    assert not r.published and "edited by hand" in r.reason and "authored/jimjar.authored.yaml" in r.reason
    assert p.read_text().endswith("edit\n")
    assert w.pub(names=["Jimjar"], force=True)[0].published
    assert not p.read_text().endswith("edit\n")


def test_hand_edit_detected_from_header_when_log_is_gone(w):
    w.npc("Jimjar")
    w.pub(names=["Jimjar"])
    (w.npcs / "summary_native/publish_log.json").unlink()
    assert w.pub(names=["Jimjar"])[0].published                 # unedited: header digest matches
    p = w.npcs / "jimjar.md"
    p.write_text(p.read_text() + "x")
    (w.npcs / "summary_native/publish_log.json").unlink()
    assert not w.pub(names=["Jimjar"])[0].published


def test_republish_unchanged_and_after_redraft_is_allowed(w):
    w.npc("Jimjar")
    w.pub(names=["Jimjar"])
    assert w.pub(names=["Jimjar"])[0].published
    w.npc("Jimjar", secrets="new secret\n")
    assert w.pub(names=["Jimjar"])[0].published
    assert "new secret" in (w.npcs / "jimjar.md").read_text()


def test_slug_collision_refuses_both_names(w):
    w.npc("Jim Jar", stem="npc_jim-jar-a")
    w.npc("Jim-Jar", stem="npc_jim-jar-b")
    res = w.pub(all_=True)
    assert all(not r.published for r in res) and len(res) == 1
    assert "Jim Jar" in res[0].reason and "Jim-Jar" in res[0].reason
    assert not (w.npcs / "jim-jar.md").exists()


def test_slug_collision_with_a_registry_npc_outside_the_range(w):
    w.npc("Jimjar")
    r = w.pub(names=["Jimjar"], registry_npcs=["Jimjar", "JimJar!"])[0]
    assert not r.published and "slug collision" in r.reason


def test_undrafted_gm_dossier_is_not_publishable(w):
    npc_compose.compose_gm(None, w.root / "docs/npcs/authored/x.authored.yaml", w.rd / "gm/npc_x.md", "X", "npc_x")
    (w.rd / "draft/npc_x.md").write_text("---\nsubject: X\n---\n")
    r = w.pub(names=["X"])[0]
    assert not r.published and "not yet drafted" in r.reason


# ── Log and side effects ────────────────────────────────────────────────────

def test_publish_log_contents(w):
    w.npc("Jimjar"); w.handbuilt("eelrich-vane")
    w.pub(names=["Jimjar"], authored_all=True)
    log = w.log()
    body = (w.npcs / "jimjar.md").read_text().split("\n", 1)[1]
    assert log["jimjar"] == {
        "source": "summary_native", "range": RANGE, "run": "20261007T101500Z",
        "published_sha256": npc_publish.sha256_text(body), "published_at": "2026-10-07T12:00:00+00:00"}
    assert log["eelrich-vane"]["source"] == "hand-built" and log["eelrich-vane"]["range"] is None
    raw = (w.npcs / "summary_native/publish_log.json").read_text()
    assert raw == json.dumps(json.loads(raw), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_log_keeps_earlier_entries(w):
    w.npc("Jimjar"); w.npc("Eldeth")
    w.pub(names=["Jimjar"]); w.pub(names=["Eldeth"])
    assert sorted(w.log()) == ["eldeth", "jimjar"]


def test_only_target_and_log_change_and_nothing_is_deleted(w):
    w.npc("Jimjar"); w.npc("Eldeth"); w.handbuilt("eelrich-vane")
    (w.npcs / "distilled").mkdir()
    (w.npcs / "distilled/old.md").write_text("old\n")
    (w.npcs / "other.md").write_text("# other\n")
    before = sha_tree(w.root)
    w.pub(names=["Jimjar"])
    after = sha_tree(w.root)
    assert set(before) <= set(after)
    changed = {k for k in after if before.get(k) != after[k]}
    assert changed == {"docs/npcs/jimjar.md", "docs/npcs/summary_native/publish_log.json"}


def test_mixed_batch_publishes_the_passing_ones(w):
    w.npc("Jimjar"); w.npc("Eldeth", verdict="fail")
    res = w.pub(all_=True)
    assert sorted((r.name, r.published) for r in res) == [("Eldeth", False), ("Jimjar", True)]
    assert (w.npcs / "jimjar.md").is_file() and not (w.npcs / "eldeth.md").exists()
    assert sorted(w.log()) == ["jimjar"]


def test_result_lines_follow_the_contract(w):
    w.npc("Jimjar"); w.npc("Eldeth", verdict="fail"); w.handbuilt("eelrich-vane")
    lines = {r.name: r.line() for r in w.pub(all_=True, authored_all=True)}
    assert lines["Jimjar"] == "Jimjar: published (summary_native)"
    assert lines["Eelrich Vane".lower().replace(" ", "-")] == "eelrich-vane: published (hand-built)"
    assert lines["Eldeth"].startswith("Eldeth: refused (verification failed")


def test_authored_tree_is_byte_identical(w):
    w.npc("Jimjar"); w.handbuilt("eelrich-vane")
    before = sha_tree(w.npcs / "authored")
    w.pub(all_=True, authored_all=True)
    assert sha_tree(w.npcs / "authored") == before


def test_published_files_do_not_count_as_unmigrated_dossiers(w):
    from campaignlib.npc import refuse_unmigrated_dossier_dir  # noqa: F401  (import proves the shared prefix)
    w.npc("Jimjar")
    w.pub(names=["Jimjar"])
    assert (w.npcs / "jimjar.md").read_text().startswith(PREFIX)
