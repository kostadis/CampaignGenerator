"""Shared helpers for the US2 delta tests (not collected: no ``test_`` prefix)."""

from __future__ import annotations

import shutil
from pathlib import Path

from pipelines.summary_native.delta import plan as dplan

FIX = Path(__file__).parent / "fixtures" / "delta" / "campaign"
M = {"generation": {"backend": "claude-code", "model": "m"}, "consistency": {"backend": "claude-code", "model": "m"}}


def copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "camp"
    shutil.copytree(FIX, root)
    # The fixture's baselines kept no evidence packs, so reusing their history needs the GM's explicit,
    # recorded opt-in to read the cited historical chapters (SC-001 refuses it by default; see
    # tests/test_delta_fix_round.py for the refusal).
    from pipelines.summary_native.delta import npc_update
    npc_update.allow_historical_parse(root, "synthetic fixture: baselines kept no evidence packs")
    return root


def make_plan(root: Path, chapters=("003-the-new-fire.md",)):
    p = dplan.create_plan(campaign_identity="delta-fixture", products=["npc"], stopping_point="plan",
                          source_paths=[root / "docs" / "summaries" / c for c in chapters], models=M)
    dplan.save_plan(p, dplan.plans_dir(root))
    return p
