import hashlib
import json

import pytest

from pipelines.summary_native.delta.errors import EXIT_USAGE, DeltaRefusal
from pipelines.summary_native.delta.plan import (
    DELTA_ROOT_REL, create_plan, load_plan, plan_digest, plans_dir, revise, save_plan)

MODELS = {"generation": {"backend": "anthropic", "model": "m"},
          "consistency": {"backend": "dgx", "model": "q", "effort": "low"}}


def _mk(tmp_path, **kw):
    src = tmp_path / "012-chapter.md"
    src.write_text("hello", encoding="utf-8")
    args = dict(campaign_identity="camp", products=["npc"], stopping_point="plan",
                source_paths=[src], models=MODELS)
    args.update(kw)
    return create_plan(**args), src


def test_empty_sources_refuse_exit_2():
    with pytest.raises(DeltaRefusal) as e:
        create_plan(campaign_identity="c", products=["npc"], stopping_point="plan",
                    source_paths=[], models=MODELS)
    assert e.value.exit_code == EXIT_USAGE == 2
    assert "does not default to all chapters" in e.value.message


def test_sources_hashed_and_chapter_parsed(tmp_path):
    plan, src = _mk(tmp_path)
    s = plan.sources[0]
    assert s.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert s.chapter == 12 and s.kind == "new"


def test_missing_source_and_unparseable_chapter_refuse(tmp_path):
    with pytest.raises(DeltaRefusal) as e:
        create_plan(campaign_identity="c", products=["npc"], stopping_point="plan",
                    source_paths=[tmp_path / "nope.md"], models=MODELS)
    assert e.value.exit_code == 2
    bad = tmp_path / "chapter.md"
    bad.write_text("x")
    with pytest.raises(DeltaRefusal) as e:
        create_plan(campaign_identity="c", products=["npc"], stopping_point="plan",
                    source_paths=[bad], models=MODELS)
    assert e.value.exit_code == 2
    plan = create_plan(campaign_identity="c", products=["npc"], stopping_point="plan",
                       source_paths=[bad], models=MODELS, chapters={str(bad): 7})
    assert plan.sources[0].chapter == 7


def test_products_and_stop_validated(tmp_path):
    with pytest.raises(Exception):
        _mk(tmp_path, products=[])
    with pytest.raises(Exception):
        _mk(tmp_path, products=["bogus"])
    with pytest.raises(ValueError):
        _mk(tmp_path, stopping_point="nowhere")


def test_deterministic_id_and_digest_ignores_created_at(tmp_path):
    a, _ = _mk(tmp_path, created_at="2026-01-01T00:00:00+00:00")
    b, _ = _mk(tmp_path, created_at="2027-01-01T00:00:00+00:00")
    assert a.plan_id == b.plan_id
    assert plan_digest(a) == plan_digest(b)


def test_immutable_and_revision_writes_new_file(tmp_path):
    plan, _ = _mk(tmp_path)
    with pytest.raises(Exception):
        plan.revision = 5
    d = plans_dir(tmp_path)
    assert str(d).endswith(DELTA_ROOT_REL + "/plans")
    p1 = save_plan(plan, d)
    r2 = revise(plan, stopping_point="verify")
    assert r2.revision == 2 and plan.revision == 1 and r2.plan_id == plan.plan_id
    p2 = save_plan(r2, d)
    assert p1 != p2 and p1.exists() and p2.exists()
    assert load_plan(d, plan.plan_id).revision == 2
    assert load_plan(d, plan.plan_id, 1).stopping_point.value == "plan"
    assert plan_digest(r2) != plan_digest(plan)
    p1.write_text(json.dumps({"x": 1}))
    with pytest.raises(DeltaRefusal):
        save_plan(plan, d)


# ── campaign-root-relative sources (review fix 10) ──────────────────────────


def _campaign_with_source(tmp_path, name="003-x.md"):
    root = tmp_path / "camp"
    src = root / "docs/summaries" / name
    src.parent.mkdir(parents=True)
    src.write_text("hello", encoding="utf-8")
    return root, src


def test_plan_stores_campaign_relative_paths_and_loads_absolute(tmp_path):
    root, src = _campaign_with_source(tmp_path)
    plan = create_plan(campaign_identity="c", products=["npc"], stopping_point="plan", source_paths=[src],
                       models=MODELS, campaign_root=root)
    path = save_plan(plan, plans_dir(root))
    stored = json.loads(path.read_text())["sources"][0]["path"]
    assert stored == "docs/summaries/003-x.md" and str(root) not in path.read_text()
    loaded = load_plan(plans_dir(root), plan.plan_id)
    assert loaded.sources[0].path == str(src) and plan_digest(loaded) == plan_digest(plan)


def test_plan_id_and_digest_survive_a_moved_campaign_copy(tmp_path):
    a, src_a = _campaign_with_source(tmp_path / "a")
    b, src_b = _campaign_with_source(tmp_path / "b")
    pa, pb = (create_plan(campaign_identity="c", products=["npc"], stopping_point="plan", source_paths=[s],
                          models=MODELS, campaign_root=r, created_at="t") for r, s in ((a, src_a), (b, src_b)))
    assert pa.plan_id == pb.plan_id and plan_digest(pa) == plan_digest(pb)
    save_plan(pa, plans_dir(a))
    import shutil
    shutil.copytree(a, tmp_path / "moved")
    assert load_plan(plans_dir(tmp_path / "moved"), pa.plan_id).sources[0].path == str(tmp_path / "moved/docs/summaries/003-x.md")


def test_source_outside_the_campaign_root_refuses_exit_2(tmp_path):
    root, _src = _campaign_with_source(tmp_path)
    outside = tmp_path / "elsewhere" / "004-y.md"
    outside.parent.mkdir()
    outside.write_text("x")
    with pytest.raises(DeltaRefusal) as e:
        create_plan(campaign_identity="c", products=["npc"], stopping_point="plan", source_paths=[outside],
                    models=MODELS, campaign_root=root)
    assert e.value.exit_code == EXIT_USAGE and "outside the campaign root" in e.value.message


def test_revise_keeps_the_campaign_root(tmp_path):
    root, src = _campaign_with_source(tmp_path)
    plan = create_plan(campaign_identity="c", products=["npc"], stopping_point="plan", source_paths=[src],
                       models=MODELS, campaign_root=root)
    assert revise(plan, stopping_point="apply").campaign_root == str(root)


def test_cli_plan_refuses_a_source_outside_the_root_and_writes_nothing(tmp_path, capsys, monkeypatch):
    from pipelines.summary_native import cli as sn_cli
    from pipelines.summary_native.delta import cli_plan
    monkeypatch.setattr(cli_plan, "campaign_identity", lambda root: "c")
    root, _src = _campaign_with_source(tmp_path)
    outside = tmp_path / "004-y.md"
    outside.write_text("x")
    code = sn_cli.main(["delta", "plan", "--campaign-dir", str(root), "--source", str(outside), "--product", "npc",
                        "--backend", "claude-code", "--model", "m", "--json"])
    assert code == 2 and "outside the campaign root" in capsys.readouterr().err
    assert not plans_dir(root).exists()
