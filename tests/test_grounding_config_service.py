"""Tests for grounding.yaml — schema, service, and the isolation guarantee.

Phases 6–7 of ``docs/config/grounding-isolation.md``. Mirrors
``test_ensemble_config_service.py`` / ``test_ensemble_config_shared.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.grounding_config_service import GroundingConfigService  # noqa: E402
from server.grounding_config_shared import (  # noqa: E402
    DEFAULT_CHUNK_SIZE,
    DEFAULT_SPLIT_CHAPTERS,
    GROUNDING_DOCS,
    GroundingConfig,
    load_grounding_config,
    save_grounding_config,
)


def _service(tmp_path: Path) -> GroundingConfigService:
    (tmp_path / "config").mkdir(exist_ok=True)
    return GroundingConfigService(tmp_path / "config")


# ── Schema ─────────────────────────────────────────────────────────────────

def test_missing_file_loads_all_defaults(tmp_path):
    cfg = load_grounding_config(tmp_path / "nope.yaml")
    assert cfg.summaries is None
    assert cfg.campaign_state.split_chapters == DEFAULT_SPLIT_CHAPTERS
    assert cfg.distill.chunk_size == DEFAULT_CHUNK_SIZE


def test_empty_file_loads_all_defaults(tmp_path):
    p = tmp_path / "grounding.yaml"
    p.write_text("", encoding="utf-8")
    assert load_grounding_config(p).summaries is None


def test_malformed_yaml_raises(tmp_path):
    p = tmp_path / "grounding.yaml"
    p.write_text("campaign_state: [oops\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_grounding_config(p)


def test_schema_is_strict(tmp_path):
    p = tmp_path / "grounding.yaml"
    p.write_text("campaign_state:\n  typo_key: x\n", encoding="utf-8")
    with pytest.raises(Exception):
        load_grounding_config(p)


def test_round_trip_preserves_values(tmp_path):
    p = tmp_path / "grounding.yaml"
    cfg = GroundingConfig.model_validate({
        "summaries": "docs/summaries.md",
        "campaign_state": {
            "output": "docs/campaign_state.md",
            "track_files": ["notes/a.txt", "notes/b.txt"],
            "track_items": ["Party freed the sovereign"],
        },
        "planning": {"dossiers": {"dossier_dir": "docs/npcs/", "since": 3}},
    })
    save_grounding_config(p, cfg)
    back = load_grounding_config(p)
    assert back.summaries == "docs/summaries.md"
    assert back.campaign_state.track_files == ["notes/a.txt", "notes/b.txt"]
    assert back.campaign_state.track_items == ["Party freed the sovereign"]
    assert back.planning.dossiers.since == 3


def test_all_four_docs_are_declared():
    cfg = GroundingConfig()
    for doc in GROUNDING_DOCS:
        assert getattr(cfg, doc) is not None


# ── input_for: the summaries-inheritance rule (D2) ─────────────────────────

def test_input_for_inherits_shared_summaries():
    cfg = GroundingConfig.model_validate({"summaries": "docs/summaries.md"})
    assert cfg.input_for("campaign_state") == "docs/summaries.md"
    assert cfg.input_for("distill") == "docs/summaries.md"


def test_per_doc_input_overrides_shared():
    cfg = GroundingConfig.model_validate({
        "summaries": "docs/summaries.md",
        "distill": {"input": "docs/other.md"},
    })
    assert cfg.input_for("distill") == "docs/other.md"
    assert cfg.input_for("campaign_state") == "docs/summaries.md"


def test_input_for_returns_none_when_nothing_set():
    """No silent fallback — the caller refuses to run."""
    assert GroundingConfig().input_for("distill") is None


def test_input_for_unknown_doc_raises():
    with pytest.raises(KeyError):
        GroundingConfig().input_for("not_a_doc")


# ── Service ────────────────────────────────────────────────────────────────

def test_update_creates_file_lazily(tmp_path):
    svc = _service(tmp_path)
    assert not svc.grounding_config_path.exists()
    svc.update_config({"summaries": "docs/summaries.md"})
    assert svc.grounding_config_path.exists()


def test_nested_partial_updates_one_field(tmp_path):
    svc = _service(tmp_path)
    svc.update_config({"campaign_state": {"output": "docs/cs.md",
                                          "extract_dir": "docs/x"}})
    svc.update_config({"campaign_state": {"output": "docs/other.md"}})
    cs = svc.resolved().campaign_state
    assert cs.output == "docs/other.md"
    assert cs.extract_dir == "docs/x"  # untouched sibling survives


def test_lists_are_replaced_not_concatenated(tmp_path):
    """track_files is a selection; appending would make removal impossible."""
    svc = _service(tmp_path)
    svc.update_config({"campaign_state": {"track_files": ["a.txt", "b.txt"]}})
    svc.update_config({"campaign_state": {"track_files": ["a.txt"]}})
    assert svc.resolved().campaign_state.track_files == ["a.txt"]


def test_unknown_key_is_400(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.update_config({"campaign_state": {"nonsense": 1}})
    assert exc.value.status_code == 400


def test_malformed_file_is_400_not_crash(tmp_path):
    svc = _service(tmp_path)
    svc.grounding_config_path.write_text("party: [oops\n", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        svc.resolved()
    assert exc.value.status_code == 400


def test_save_is_atomic_leaving_no_tmp_file(tmp_path):
    svc = _service(tmp_path)
    svc.update_config({"summaries": "docs/summaries.md"})
    assert not list(svc.grounding_config_path.parent.glob("*.tmp*"))


# ── Isolation: the point of the whole exercise ─────────────────────────────

def test_grounding_write_cannot_touch_sibling_documents(tmp_path):
    """Mirrors test_ui_section_write_cannot_touch_platform_yaml.

    A grounding write re-serializes only grounding.yaml — it cannot corrupt
    ui_state.yaml, platform.yaml or ensemble.yaml, which is what sharing one
    document made possible before.
    """
    cfgdir = tmp_path / "config"
    cfgdir.mkdir()
    siblings = {}
    for name, body in [
        ("ui_state.yaml", "version: 4\nui: {}\n"),
        ("platform.yaml", "runtime:\n  default_model: claude-sonnet-4-6\n"),
        ("ensemble.yaml", "chapters_selected: []\n"),
    ]:
        p = cfgdir / name
        p.write_text(body, encoding="utf-8")
        siblings[p] = p.read_bytes()

    GroundingConfigService(cfgdir).update_config(
        {"summaries": "docs/summaries.md", "distill": {"output": "docs/ws.md"}}
    )

    for p, before in siblings.items():
        assert p.read_bytes() == before, f"{p.name} was modified by a grounding write"


def test_grounding_yaml_is_its_own_file(tmp_path):
    svc = _service(tmp_path)
    svc.update_config({"summaries": "docs/summaries.md"})
    assert svc.grounding_config_path.name == "grounding.yaml"
    raw = yaml.safe_load(svc.grounding_config_path.read_text(encoding="utf-8"))
    # Not nested under a ui.<section> wrapper — it is a top-level document.
    assert raw["summaries"] == "docs/summaries.md"
    assert "ui" not in raw
