"""T045: authored Secrets never reach a prompt or an intermediate artifact (spec 039 SC-007, FR-012).

The fixture's Brannoc Ironvein authored file carries the canary. The only files allowed to hold it
are the ones that are SUPPOSED to: the authored file itself, the GM composition (which appends
Secrets by design) and the published dossier (GM-only). Everything else the delta writes -- prompts,
drafts, evidence packs, verify reports, run records, spans, freshness, receipts -- must not.
A player-audience request is refused before any evidence is read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _delta_npc_support import CANARY, FakeModel, census_for, copy_fixture, install_fake, make_plan, sign_drafts
from pipelines.summary_native import cli as sn_cli
from pipelines.summary_native.delta import npc_update
from pipelines.summary_native.delta.errors import DeltaRefusal


def _exempt(root: Path, p: Path) -> bool:
    rel = p.relative_to(root).as_posix()
    return (
        rel.startswith("docs/npcs/authored/")  # the GM's own file
        or "/gm/" in rel  # the GM composition appends Secrets on purpose
        or (p.parent == root / "docs" / "npcs" and p.suffix == ".md")  # published, GM-only
    )


def _leaks(root: Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not _exempt(root, p) and CANARY.encode() in p.read_bytes():
            out.append(p.relative_to(root).as_posix())
    return out


def test_fixture_really_carries_the_canary(tmp_path):
    root = copy_fixture(tmp_path)
    assert CANARY in (root / "docs/npcs/authored/brannoc-ironvein.authored.yaml").read_text()


def test_canary_is_in_no_prompt_and_no_intermediate_artifact(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    fake = install_fake(monkeypatch)

    out = npc_update.draft(root, plan)
    assert out.exit_code == 0 and len(fake.prompts) == 2
    assert all(CANARY not in system + user for system, user in fake.prompts)
    # the GM composition is the one generated file that does carry it, by design
    gm = (out.range_dir / "gm" / "npc_brannoc_ironvein.md").read_text()
    assert CANARY in gm

    npc_update.verify(root, plan)
    signed = sign_drafts(root, out.range_dir,
                         {"npc_brannoc_ironvein": "Brannoc Ironvein", "npc_tobin_fenwick": "Tobin Fenwick"}, capsys)
    assert set(signed) == {"npc_brannoc_ironvein", "npc_tobin_fenwick"}
    pv = npc_update.publish_preview(root, plan, ["Brannoc Ironvein", "Tobin Fenwick"])
    results = npc_update.publish(root, plan, ["Brannoc Ironvein", "Tobin Fenwick"], pv["preview_sha256"])
    assert [r.outcome for r in results] == ["published", "published"]

    assert _leaks(root) == []
    receipts = list((root / "docs/summaries/delta" / plan.plan_id / "npc/receipts").glob("*.json"))
    assert receipts and all(CANARY not in r.read_text() for r in receipts)


def test_drafting_reads_manual_edits_but_never_secrets(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    auth = root / "docs/npcs/authored/brannoc-ironvein.authored.yaml"
    auth.write_text("subject: Brannoc Ironvein\nmanual:\n  - Brannoc is left-handed.\nsecrets: 'x " + CANARY + "'\n")
    plan = make_plan(root)
    census_for(root, plan)
    fake = install_fake(monkeypatch)
    npc_update.draft(root, plan)
    brannoc = next(u for _s, u in fake.prompts if "subject: Brannoc Ironvein" in u)
    assert "[manual 1] Brannoc is left-handed." in brannoc
    assert all(CANARY not in s + u for s, u in fake.prompts)


def test_module_cannot_read_secrets():
    src = Path(npc_update.__file__).read_text(encoding="utf-8")
    assert "load_secrets" not in src


def test_player_audience_is_refused_before_any_content_is_exposed(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)  # NOTE: no census was run, so a refusal here proves nothing was read first
    fake = install_fake(monkeypatch)
    before = {p for p in root.rglob("*") if p.is_file()}
    with pytest.raises(DeltaRefusal) as e:
        npc_update.draft(root, plan, audience="player")
    assert e.value.exit_code == 1 and "GM-only" in e.value.message
    assert fake.prompts == []
    assert {p for p in root.rglob("*") if p.is_file()} == before  # nothing written either


def test_player_audience_refused_through_the_public_cli(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    fake = install_fake(monkeypatch)
    rc = sn_cli.main(["delta", "npc", "draft", "--campaign-dir", str(root), "--plan", plan.plan_id,
                      "--audience", "player", "--json"])
    out = capsys.readouterr()
    assert rc == 1 and json.loads(out.out)["exit_code"] == 1
    assert fake.prompts == [] and CANARY not in out.out + out.err
    with pytest.raises(SystemExit) as e:
        sn_cli.main(["delta", "npc", "draft", "--campaign-dir", str(root), "--plan", plan.plan_id,
                     "--audience", "wizard"])
    assert e.value.code == 2  # argparse rejects an unknown audience
