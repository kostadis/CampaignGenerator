"""T023 / quickstart steps 2, 4, 5, 12: a complete native grounding delta through the public CLI.

plan -> sources -> baseline status -> grounding propose (fake model) -> decide -> check -> preview -> apply.

The model is faked at ``grounding_edits.stream_api`` / ``grounding_check.stream_api``; no network call is made.
The main test fakes only the last delegate of ``apply`` (so it is quick and isolated); the final test,
``test_real_promotion_path_publishes_the_delta``, runs ``apply`` through the REAL ``default_publisher``: the
candidates are staged as a promotion range by ``preview``, the claims chain (select, review, check) and the four
document sign-offs run through the real claims/review modules, and the generation is activated.
"""

from __future__ import annotations

import hashlib
import json
import shutil

import pytest

from pipelines.summary_native import cli
from pipelines.summary_native.delta import baseline as bl, grounding_check, grounding_edits, grounding_publish as gp
from tests.support.delta_grounding_fixture import (
    add_new_chapter, digest_tree, history_digests, make_grounding_campaign, published_path,
)

SUPPORT = "Warden Hale confirmed the Lantern Road is open past the eastern marker"
NEW_LINE = "The Lantern Road is open to the eastern marker. [ch 004 / 004.01]"
INHERITED_LINE = "The sealed gate is the Brass Key's door. [ch 001 / 001.01]"


def run(capsys, root, *argv, expect=0):
    code = cli.main(["delta", *argv, "--campaign-dir", str(root), "--json"])
    out = capsys.readouterr()
    assert code == expect, (out.out, out.err)
    return json.loads(out.out) if out.out.strip() else {}


def anchor(root):
    """The first world_state line the delta edits (in the ACTIVE baseline), and its target id."""
    text = bl.baseline_documents(bl.bind(root), root)["world_state"]
    for t in grounding_edits.assign_targets({"world_state": text}):
        line = text.splitlines(keepends=True)[t.start - 1].decode()
        if line.startswith("Existing reviewed live edit"):
            return t, line.rstrip("\n")
    raise AssertionError("no anchor line in the fixture")


def fake_model(monkeypatch, target, line, after_text, support=SUPPORT):
    def fake_stream(client, system, user, model, **kw):
        if system.startswith("You propose"):
            return json.dumps({"proposals": [{
                "target_id": target.target_id, "after_text": after_text, "category": "new_information",
                "rationale": "the new chapter confirms the road", "support": support}]})
        return json.dumps({"findings": [{"document": "world_state", "line": 1,
                                         "detail": "model thinks the wording is loose"}]})

    for module in (grounding_edits, grounding_check):
        monkeypatch.setattr(module, "stream_api", fake_stream)
        monkeypatch.setattr(module, "client_from_args", lambda *a, **k: object())


def prepare(capsys, root, source, monkeypatch, after_text, support=SUPPORT, products=("grounding",)):
    plan = run(capsys, root, "plan", "--source", str(source),
               *[a for p in products for a in ("--product", p)], "--stop", "apply")
    pid = plan["plan_id"]
    target, line = anchor(root)
    fake_model(monkeypatch, target, line, after_text.format(line=line), support)
    proposed = run(capsys, root, "grounding", "propose", "--plan", pid)
    assert proposed["applied"] == 0 and len(proposed["proposals"]) == 1
    run(capsys, root, "grounding", "decide", proposed["proposals"][0]["proposal_id"], "--plan", pid,
        "--decision", "approve", "--reviewer", "fixture-gm")
    return pid, line


@pytest.fixture
def campaign(tmp_path):
    root = make_grounding_campaign(tmp_path)
    return root, add_new_chapter(root)


def test_quickstart_step_2_one_new_chapter_is_the_only_parsed_input(campaign, capsys):
    root, source = campaign
    plan = run(capsys, root, "plan", "--source", str(source), "--product", "grounding", "--stop", "prepare")
    sources = run(capsys, root, "sources", "--plan", plan["plan_id"])
    assert sources["read_counts"]["parsed_new"] == 1
    assert sources["read_counts"]["parsed_historical"] == 0  # SC-001
    assert sources["call_counts"]["model"] == 0


def test_plan_declares_no_default_of_its_own(campaign, capsys):
    """Principle XII: the plan's backend/model come from the summary_native prose resolution."""
    from pipelines.summary_native import schema
    root, source = campaign
    plan = run(capsys, root, "plan", "--source", str(source), "--product", "grounding", "--stop", "plan")
    saved = json.loads((root / "docs/summaries/delta/plans" / f"{plan['plan_id']}-r1.json").read_text())
    assert saved["models"]["generation"]["backend"] == schema.DEFAULT_PROSE_BACKEND


def test_plan_refuses_when_no_model_resolves(campaign, capsys):
    root, source = campaign
    code = cli.main(["delta", "plan", "--source", str(source), "--product", "grounding", "--backend", "dgx",
                     "--campaign-dir", str(root), "--json"])
    assert code == 2 and "--model" in capsys.readouterr().err


def test_quickstart_step_4_baseline_binds_the_active_generation(campaign, capsys):
    root, _source = campaign
    status = run(capsys, root, "baseline", "status")
    assert status["status"] == "valid" and status["generation_id"] == "legacy-fixture"
    assert {d["name"] for d in status["documents"]} == set(bl.DOCUMENT_NAMES)
    assert all(d["origin_ref"] and d["approval_ref"] for d in status["documents"])


def test_quickstart_steps_2_4_5_12_complete_inherited_grounding_delta(campaign, capsys, monkeypatch):
    root, source = campaign
    before_tree = digest_tree(root / "docs/summary_native")
    before_history = history_digests(root)
    before_files = {p for p in root.rglob("*") if p.is_file() and not p.is_symlink()}
    # the candidate keeps the anchor (its inherited ch 003 citation), adds a line citing NEW chapter 4 and a
    # line citing INHERITED chapter 1 (not a selected source)
    pid, anchor_line = prepare(capsys, root, source, monkeypatch, "{line}\n" + NEW_LINE + "\n" + INHERITED_LINE)

    sources = run(capsys, root, "sources", "--plan", pid)
    assert sources["read_counts"]["parsed_historical"] == 0  # SC-001

    checked = run(capsys, root, "grounding", "check", "--plan", pid)
    assert checked["passed"] is True and checked["approval"] is None
    # a model consistency finding is recorded, advisory, and changes neither pass nor approval (FR-015)
    assert any(f["code"] == "CONSISTENCY_MODEL" and f["severity"] == "advisory" for f in checked["findings"])

    # SC-002: untouched baseline documents are byte-identical in the candidates
    base_docs = bl.baseline_documents(bl.bind(root), root)
    gdir = gp.grounding_dir(root, pid)
    assert sorted(p.name for p in (gdir / "candidates").glob("*.md")) == sorted(f"{n}.md" for n in bl.DOCUMENT_NAMES)
    for name in bl.DOCUMENT_NAMES:
        cand = (gdir / "candidates" / f"{name}.md").read_bytes()
        if name == "world_state":
            assert cand != base_docs[name] and NEW_LINE.encode() in cand and INHERITED_LINE.encode() in cand
            old, new = base_docs[name].splitlines(keepends=True), cand.splitlines(keepends=True)
            assert len(new) == len(old) + 2
            at = next(i for i, ln in enumerate(old) if ln != new[i])
            assert at > 0 and new[:at] == old[:at] and new[at + 3:] == old[at + 1:]
        else:
            assert cand == base_docs[name]
    assert checked["candidate_sha256"]["world_state"] == hashlib.sha256((gdir / "candidates/world_state.md").read_bytes()).hexdigest()

    # lineage: unchanged => inherited with custody (generation path + digest); changed => produced + check
    lineage = json.loads((gdir / "lineage.json").read_text())
    assert lineage["kind"] == "delta" and lineage["baseline"]["generation_id"] == "legacy-fixture"
    by_name = {m["name"]: m for m in lineage["members"]}
    assert by_name["world_state"]["mode"] == "produced" and by_name["world_state"]["check_status"] == "passed"
    assert by_name["world_state"]["check_ref"] == checked["path"].split(str(root) + "/")[1]
    for name in ("campaign_state", "party", "planning"):
        member = by_name[name]
        assert member["mode"] == "inherited"
        assert member["custody_ref"]["path"] == f"docs/grounding/generations/legacy-fixture/published/{name}.md"
        assert member["custody_ref"]["sha256"] == hashlib.sha256(published_path(root, name).read_bytes()).hexdigest()
    # the nested reference members travel as inherited, with custody
    for nested in ("reference/nested/deeper/provenance.md", "reference/locations/lantern-road.md",
                   "canon_events_timeline.md"):
        assert by_name[nested]["mode"] == "inherited" and by_name[nested]["custody_ref"]

    # inherited citations resolve through baseline custody (the chapter-1 line passed the check above)
    resolver = bl.custody_resolver(bl.bind(root), root)
    held = resolver(1, "001.01")
    assert held is not None and held.path == "docs/summaries/001-fixture.md"
    assert resolver(1, "001.99") is None  # an entry the baseline chapter does not hold

    previewed = run(capsys, root, "grounding", "preview", "--plan", pid)
    assert previewed["complete"] is True and previewed["problems"] == []

    seen = []
    monkeypatch.setattr(gp, "default_publisher", lambda campaign, plan, request: seen.append(plan.plan_id) or {"published": True})
    _record_approval(root, pid)
    applied = run(capsys, root, "grounding", "apply", "--plan", pid, "--preview-sha", previewed["preview_sha256"])
    assert applied["applied"] is True and seen == [pid]

    # no synthetic full-corpus record anywhere; nothing outside the delta tree was written; history untouched
    new_files = {p for p in root.rglob("*") if p.is_file() and not p.is_symlink()} - before_files
    assert new_files and all("docs/summaries/delta/" in p.as_posix() or "docs/summary_native/ch004-004/" in p.as_posix()
                             for p in new_files)
    assert not any("synth" in p.name or "run-" in p.as_posix() for p in new_files)
    for p in new_files:
        if p.suffix == ".json":
            assert json.loads(p.read_text()).get("step") != "synth"
    after_tree = digest_tree(root / "docs/summary_native")
    assert {k: v for k, v in after_tree.items() if not k.startswith("ch004-004/")} == before_tree
    assert history_digests(root) == before_history


def test_quickstart_step_5_stale_candidate_after_check_is_refused_by_preview(campaign, capsys, monkeypatch):
    root, source = campaign
    pid, _ = prepare(capsys, root, source, monkeypatch, "{line}\n" + NEW_LINE)
    run(capsys, root, "grounding", "check", "--plan", pid)
    candidate = gp.grounding_dir(root, pid) / "candidates/world_state.md"
    candidate.write_bytes(candidate.read_bytes() + b"smuggled after the check\n")
    code = cli.main(["delta", "grounding", "preview", "--plan", pid, "--campaign-dir", str(root), "--json"])
    assert code == 3 and "check" in capsys.readouterr().err


def test_quickstart_step_12_removed_inherited_support_blocks_with_targeted_message(campaign, capsys, monkeypatch):
    root, source = campaign
    pid, _ = prepare(capsys, root, source, monkeypatch, "{line}\n" + NEW_LINE + "\n" + INHERITED_LINE)
    # deliberately remove the baseline's custody of chapter 1
    manifest_path = root / "docs/summary_native/ch001-003/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] = [f for f in manifest["files"] if f["chapter"] != 1]
    manifest_path.write_text(json.dumps(manifest))
    code = cli.main(["delta", "grounding", "check", "--plan", pid, "--campaign-dir", str(root), "--json"])
    captured = capsys.readouterr()
    assert code == 1
    report = json.loads(captured.out)
    custody = [f for f in report["findings"] if f["code"] == "CITATION_CUSTODY"]
    assert custody and report["passed"] is False
    assert "[ch 001 / 001.01]" in custody[0]["detail"] and "baseline does not hold" in custody[0]["detail"]
    assert "Restore the line" in custody[0]["detail"]
    # the lineage still records the failed check, so preview reports it incomplete and apply cannot run
    previewed = run(capsys, root, "grounding", "preview", "--plan", pid)
    assert previewed["complete"] is False
    _record_approval(root, pid)  # reviewed, so the refusal below is the incomplete lineage, not a missing review
    code = cli.main(["delta", "grounding", "apply", "--plan", pid, "--preview-sha", previewed["preview_sha256"],
                     "--campaign-dir", str(root)])
    assert code == 1


def _record_approval(root, pid):
    """An explicit GM approval recorded against the current hashes (the record `apply` requires)."""
    from pipelines.summary_native.delta import review_binding as rb
    from pipelines.summary_native.delta.plan import load_plan, plans_dir

    plan = load_plan(plans_dir(root), pid)
    rb.save_binding(root, rb.make_binding(root, plan, "grounding", "publication", decisions=[
        rb.BoundDecision(id="doc", level="document", decision="approve", reviewer="fixture-gm")]))


def publish_delta(capsys, root, source, monkeypatch, chapter, review_id, after_text, support=SUPPORT):
    """Plan, decide, check, stage, run the real claims chain and sign-offs, and apply for real."""
    from datetime import datetime, timezone

    from campaignlib.grounding_config import promotion_config_from_summary_native
    from pipelines.summary_native.claims.selection import (
        confirm_selection, mandatory_source_closure, save_confirmed_selection)
    from pipelines.summary_native.promotion.manifest import build_bundle_selection
    from pipelines.summary_native.promotion.settings import load_settings
    from pipelines.summary_native.review.documents import sign_document
    from pipelines.summary_native.review.models import canonical_bytes
    from pipelines.summary_native.review.store import load_campaign_identity, read_snapshot

    pid, _ = prepare(capsys, root, source, monkeypatch, after_text, support)
    assert run(capsys, root, "grounding", "check", "--plan", pid)["passed"] is True
    staged = run(capsys, root, "grounding", "preview", "--plan", pid)["staged"]
    assert staged["range"] == f"ch{chapter:03d}-{chapter:03d}"  # the delta's own range, not a full corpus
    config = root / "config/config.yaml"
    settings = load_settings(str(config))
    rules = promotion_config_from_summary_native(settings.summary_native).rule_versions
    campaign_id = str(load_campaign_identity(root).campaign_id)
    bundle = build_bundle_selection(root, out_root=staged["request"]["out_root"], since=chapter, until=chapter,
                                    campaign_id=campaign_id, review_id="claims-selection", rule_versions=rules,
                                    config_path=root / "config/grounding.yaml")
    selection = mandatory_source_closure(root, bundle, effective_horizon=f"through-chapter-{chapter}",
                                         audience="gm", rule_versions=rules)  # inherited citations: custody
    confirmed = confirm_selection(selection, reviewer="gm", confirmed_at=datetime(2026, 11, 6, tzinfo=timezone.utc))
    save_confirmed_selection(root, confirmed)
    selection_file = root.parent / f"selection-{chapter}.json"
    selection_file.write_bytes(canonical_bytes(confirmed))
    assert cli.main(["claims", "review", "--config", str(config), "--selection", str(selection_file),
                     "--review", review_id, "--json"]) == 0
    capsys.readouterr()
    code = cli.main(["claims", "check", "--config", str(config), "--selection", str(selection_file),
                     "--review", review_id, "--json"])
    checked = json.loads(capsys.readouterr().out)
    assert code == 0, checked
    report = checked["data"]["paths"][0]
    _m, _c, items = read_snapshot(root, review_id)
    for item in items:
        if item.proposed_action.action == "signoff_document":
            sign_document(root, review_id, document_item_id=item.item_id,
                          item_sha256=item.proposed_action.details["document_sha256"],
                          expected_decision_revision=0, reviewer="fixture-gm")
    previewed = run(capsys, root, "grounding", "preview", "--plan", pid, "--review", review_id,
                    "--claims-report", report)
    # the GM also rules on the review's other items (claims coverage) through the real review decide verb
    manifest, _c, items = read_snapshot(root, review_id)
    others = [i for i in items if i.proposed_action.action != "signoff_document"]
    if others:
        batch = root.parent / f"decisions-{chapter}.json"
        batch.write_text(json.dumps({"version": 1, "request_id": f"rq-{chapter}", "review_generation": manifest.generation,
                                     "reviewer": "fixture-gm", "decisions": [
            {"item_id": i.item_id, "item_revision": i.revision, "review_digest": i.review_digest,
             "expected_decision_revision": 0, "verdict": "approve", "disposition": "accept_no_change",
             "note": "reviewed"} for i in others]}))
        assert cli.main(["review", "decide", review_id, "--decisions", str(batch),
                         "--campaign-dir", str(root), "--json"]) == 0, capsys.readouterr()
        capsys.readouterr()
    # the real handoff records the review binding apply requires (it reads the sign-offs just made)
    run(capsys, root, "review", "handoff", "--plan", pid)
    applied = run(capsys, root, "grounding", "apply", "--plan", pid, "--preview-sha", previewed["preview_sha256"])
    assert applied["applied"] is True, applied
    return pid


def test_real_promotion_path_publishes_the_delta(campaign, capsys, monkeypatch):
    """Apply through the REAL ``default_publisher``: staged range, real claims chain, real sign-offs."""
    root, source = campaign
    publish_delta(capsys, root, source, monkeypatch, 4, "delta-review",
                  "{line}\n" + NEW_LINE + "\n" + INHERITED_LINE)
    live = (root / "docs/world_state.md").read_text(encoding="utf-8")
    assert NEW_LINE in live and INHERITED_LINE in live          # the candidate is now the live document
    assert (root / "docs/party.md").read_bytes().split(b"\n", 1)[1] == \
        published_path(root, "party").read_bytes().split(b"\n", 1)[1]   # inherited: body unchanged
    assert len(list((root / "docs/grounding/generations").iterdir())) == 2
    assert not any("synth" in p.name for p in (root / "docs/grounding").rglob("*"))


def test_claims_selection_blocks_removed_inherited_support_with_targeted_message(campaign, capsys, monkeypatch):
    from campaignlib.grounding_config import promotion_config_from_summary_native
    from pipelines.summary_native.claims.selection import mandatory_source_closure
    from pipelines.summary_native.promotion.errors import PromotionError
    from pipelines.summary_native.promotion.manifest import build_bundle_selection
    from pipelines.summary_native.promotion.settings import load_settings
    from pipelines.summary_native.review.store import load_campaign_identity

    root, source = campaign
    pid, _ = prepare(capsys, root, source, monkeypatch, "{line}\n" + NEW_LINE + "\n" + INHERITED_LINE)
    run(capsys, root, "grounding", "check", "--plan", pid)
    staged = run(capsys, root, "grounding", "preview", "--plan", pid)["staged"]
    manifest_path = root / "docs/summary_native/ch001-003/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] = [f for f in manifest["files"] if f["chapter"] != 1]
    manifest_path.write_text(json.dumps(manifest))
    rules = promotion_config_from_summary_native(load_settings(str(root / "config/config.yaml")).summary_native).rule_versions
    bundle = build_bundle_selection(root, out_root=staged["request"]["out_root"], since=4, until=4,
                                    campaign_id=str(load_campaign_identity(root).campaign_id),
                                    review_id="claims-selection", rule_versions=rules,
                                    config_path=root / "config/grounding.yaml")
    with pytest.raises(PromotionError) as err:
        mandatory_source_closure(root, bundle, effective_horizon="through-chapter-4", audience="gm", rule_versions=rules)
    assert err.value.code == "CLAIMS_SOURCE_MISSING" and "has no baseline custody" in str(err.value)


CHAPTER_5 = """# Chapter 5

Date: 2026-04-09

## Scenes

### 005.01 The Far Marker

Warden Hale walked the Lantern Road past the eastern marker and found the far marker standing.

#### The far marker stands.

- Hale confirms the far marker stands.

## Memorable Moments

> "It still stands."
> - Warden Hale
> *Mara smiled.*
"""
NEW_LINE_5 = "The far marker beyond the eastern marker still stands. [ch 005 / 005.01]"
OLD_LINE_1 = "The brass key still opens the sealed gate. [ch 001 / 001.01]"


def test_second_delta_resolves_chapter_one_through_the_chain_and_coverage_stays_honest(campaign, capsys, monkeypatch):
    root, source = campaign
    # delta 1: chapter 4, published for real
    publish_delta(capsys, root, source, monkeypatch, 4, "r1", "{line}\n" + NEW_LINE + "\n" + INHERITED_LINE)
    first = bl.bind(root)
    assert first.generation_id != "legacy-fixture"
    coverage = {m.name: m for m in first.members}
    assert coverage["timeline"].coverage_through == 4
    # the legacy baseline recorded no range, so coverage before chapter 4 is NOT claimed
    assert any("before chapter 4" in g for g in coverage["timeline"].gaps)

    # delta 2: a new chapter 5 on top of the delta-published generation
    source5 = root / "docs/summaries/005-the-far-marker.md"
    source5.write_text(CHAPTER_5, encoding="utf-8")
    resolver = bl.custody_resolver(first, root)
    assert resolver(1, "001.01").path == "docs/summaries/001-fixture.md"      # two hops back (legacy range)
    assert resolver(4, "004.01").path == "docs/summaries/004-the-eastern-marker.md"   # delta 1's own range
    assert resolver(1, "001.99") is None and resolver(7, "007.01") is None

    pid = publish_delta(capsys, root, source5, monkeypatch, 5, "r2",
                        "{line}\n" + NEW_LINE_5 + "\n" + OLD_LINE_1,
                        support="Warden Hale walked the Lantern Road past the eastern marker")
    second = bl.bind(root)
    assert second.generation_id not in (first.generation_id, "legacy-fixture")
    timeline = next(m for m in second.members if m.name == "timeline")
    assert timeline.coverage_through == 5            # the chain's range, not the highest chapter cited anywhere
    live = (root / "docs/world_state.md").read_text(encoding="utf-8")
    assert OLD_LINE_1 in live and NEW_LINE_5 in live and NEW_LINE in live
    lineage = json.loads((gp.grounding_dir(root, pid) / "lineage.json").read_text())
    assert lineage["baseline"]["generation_id"] == first.generation_id

    # live prose citing a later chapter never raises coverage
    wp = root / "docs/grounding/generations" / second.generation_id / "live" / "world_state.md"
    wp.write_text(wp.read_text(encoding="utf-8") + "A hand edit citing the future. [ch 009 / 009.01]\n", encoding="utf-8")
    drifted = bl.bind(root)
    assert drifted.status == "unadopted"
    assert {m.name: m.coverage_through for m in drifted.members} == {m.name: m.coverage_through for m in second.members}

    # a tampered hop is refused
    retained = root / "docs/grounding/generations" / second.generation_id / "metadata/records/world_state.json"
    retained.write_text(retained.read_text(encoding="utf-8") + " ", encoding="utf-8")
    from pipelines.summary_native.delta.errors import DeltaRefusal
    with pytest.raises(DeltaRefusal) as err:
        bl.bind(root)
    assert err.value.exit_code in (3, 5)  # stale (our hop check) or recovery (promotion history refuses first)


def test_real_delta_publishes_inherited_legacy_document_shape(tmp_path, capsys, monkeypatch):
    from tests.support.delta_grounding_fixture import FACTORY

    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    for name in FACTORY.DOCUMENTS:
        p = root / f"docs/{name}.md"
        old = "\n".join(line for line in p.read_text().splitlines()
                        if "summary_native pointers:" not in line) + "\n"
        p.write_text(f"# Retained legacy {name}\n\n## Legacy snapshot\nHistorical context.\n\n" + old)
    FACTORY.initialize_managed(root, "legacy-fixture")
    source = add_new_chapter(root)
    publish_delta(capsys, root, source, monkeypatch, 4, "legacy-shape-review", "{line}\n" + NEW_LINE)
    assert "# Retained legacy world_state" in (root / "docs/world_state.md").read_text()
    assert NEW_LINE in (root / "docs/world_state.md").read_text()


def test_preserved_contract_still_checks_required_sections_order_and_tables():
    from pipelines.summary_native.delta.outline_contract import preserved_outline_problems
    from pipelines.summary_native.outline import load_outline

    heads = load_outline("world_state")
    base = ("# Legacy title\n\n" + "\n\n".join(h + "\nRetained content." for h in heads) + "\n").encode()
    assert preserved_outline_problems("world_state", base, base) == []
    missing = base.replace(heads[0].encode(), b"## Renamed section")
    assert any("missing heading" in p for p in preserved_outline_problems("world_state", base, missing))
    empty = base.replace((heads[0] + "\nRetained content.").encode(), heads[0].encode())
    assert any("empty body" in p for p in preserved_outline_problems("world_state", base, empty))
    swapped = base.replace(heads[0].encode(), b"TEMP").replace(heads[1].encode(), heads[0].encode()).replace(b"TEMP", heads[1].encode())
    assert any("order" in p for p in preserved_outline_problems("world_state", base, swapped))
    table = base + b"\n| A | B |\n| x |\n"
    assert any("column" in p for p in preserved_outline_problems("world_state", base, table))


def test_legacy_contract_requires_checked_bytes_and_pinned_lineage(tmp_path, capsys, monkeypatch):
    from campaignlib.grounding_config import promotion_config_from_summary_native
    from pipelines.summary_native.delta.outline_contract import legacy_delta_outline
    from pipelines.summary_native.promotion.manifest import build_bundle_selection
    from pipelines.summary_native.promotion.settings import load_settings
    from pipelines.summary_native.review.store import load_campaign_identity
    from tests.support.delta_grounding_fixture import FACTORY

    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    p = root / "docs/world_state.md"
    old = "\n".join(line for line in p.read_text().splitlines()
                    if "summary_native pointers:" not in line) + "\n"
    p.write_text("# Legacy title\n\n" + old)
    FACTORY.initialize_managed(root, "legacy-fixture")
    source = add_new_chapter(root)
    pid, _ = prepare(capsys, root, source, monkeypatch, "{line}\n" + NEW_LINE)
    assert run(capsys, root, "grounding", "check", "--plan", pid)["passed"]
    run(capsys, root, "grounding", "preview", "--plan", pid)
    settings = load_settings(str(root / "config/config.yaml"))
    bundle = build_bundle_selection(root, out_root="docs/summary_native", since=4, until=4,
        campaign_id=str(load_campaign_identity(root).campaign_id), review_id="r",
        rule_versions=promotion_config_from_summary_native(settings.summary_native).rule_versions,
        config_path=root / "config/grounding.yaml")
    document = next(x for x in bundle.documents if x.document_id.value == "world_state")
    text = (root / document.path).read_text()
    assert legacy_delta_outline(root, bundle, "world_state", text) == []
    from pipelines.summary_native.delta.outline_contract import legacy_delta_paths
    from pipelines.summary_native import pointers
    path = root / document.path
    assert pointers.check_paths(path, root)  # The strict checker still requires an inline contract.
    assert legacy_delta_paths(root, bundle, "world_state", path) == []
    reference = path.parent / "reference/factions.md"
    data = reference.read_bytes()
    reference.unlink()
    assert any("missing file" in p for p in legacy_delta_paths(root, bundle, "world_state", path))
    reference.write_bytes(data)
    assert legacy_delta_outline(root, bundle, "world_state", text + "unreviewed") is None
    assert legacy_delta_outline(root, bundle.model_copy(update={"retained_records": ()}), "world_state", text) is None
    published_path(root, "world_state").write_text("changed baseline")
    assert legacy_delta_outline(root, bundle, "world_state", text) is None


def test_legacy_pointer_fallback_never_replaces_an_existing_contract(tmp_path, capsys, monkeypatch):
    from campaignlib.grounding_config import promotion_config_from_summary_native
    from pipelines.summary_native.delta.outline_contract import legacy_delta_paths
    from pipelines.summary_native.promotion.manifest import build_bundle_selection
    from pipelines.summary_native.promotion.settings import load_settings
    from pipelines.summary_native.review.store import load_campaign_identity

    root = make_grounding_campaign(tmp_path)
    source = add_new_chapter(root)
    pid, _ = prepare(capsys, root, source, monkeypatch, "{line}\n" + NEW_LINE)
    run(capsys, root, "grounding", "check", "--plan", pid)
    run(capsys, root, "grounding", "preview", "--plan", pid)
    settings = load_settings(str(root / "config/config.yaml"))
    bundle = build_bundle_selection(root, out_root="docs/summary_native", since=4, until=4,
        campaign_id=str(load_campaign_identity(root).campaign_id), review_id="r",
        rule_versions=promotion_config_from_summary_native(settings.summary_native).rule_versions,
        config_path=root / "config/grounding.yaml")
    path = root / next(x.path for x in bundle.documents if x.document_id.value == "world_state")
    assert legacy_delta_paths(root, bundle, "world_state", path) is None
