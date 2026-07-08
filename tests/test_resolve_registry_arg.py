"""Tests for campaignlib.registry.resolve_registry_arg — the shared --registry
precedence resolver used by facts_to_state and the synthesise_* scripts.

No API / model calls: pure argument-precedence logic.
"""
import argparse
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campaignlib.registry import resolve_registry_arg  # noqa: E402


def _parser():
    return argparse.ArgumentParser()


def _write_registry(dir_: Path) -> Path:
    (dir_ / "docs").mkdir(parents=True, exist_ok=True)
    reg = dir_ / "docs" / "entity_registry.yaml"
    reg.write_text("version: 1\nentities: []\n", encoding="utf-8")
    return reg


def test_explicit_dir_resolves_to_its_registry(tmp_path):
    reg = _write_registry(tmp_path)
    path, campaign_dir, explicit = resolve_registry_arg(str(tmp_path), False, _parser())
    assert path == reg
    assert campaign_dir == Path(str(tmp_path))
    assert explicit is True


def test_explicit_dir_without_registry_errors(tmp_path):
    # A directory that has no docs/entity_registry.yaml is a user error.
    with pytest.raises(SystemExit):
        resolve_registry_arg(str(tmp_path), False, _parser())


def test_explicit_file_used_as_is(tmp_path):
    reg = tmp_path / "custom_registry.yaml"
    reg.write_text("version: 1\nentities: []\n", encoding="utf-8")
    path, campaign_dir, explicit = resolve_registry_arg(str(reg), False, _parser())
    assert path == reg
    assert campaign_dir == reg.parent.parent
    assert explicit is True


def test_legacy_flag_opts_out_of_autodiscovery(tmp_path, monkeypatch):
    # Even with a registry sitting in CWD, an explicit legacy flag wins.
    _write_registry(tmp_path)
    monkeypatch.chdir(tmp_path)
    path, campaign_dir, explicit = resolve_registry_arg(None, True, _parser())
    assert path is None and campaign_dir is None and explicit is False


def test_autodiscovers_registry_from_cwd(tmp_path, monkeypatch):
    reg = _write_registry(tmp_path)
    monkeypatch.chdir(tmp_path)
    path, campaign_dir, explicit = resolve_registry_arg(None, False, _parser())
    assert path == reg
    assert campaign_dir == Path.cwd()
    assert explicit is False


def test_autodiscover_returns_none_when_no_registry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path, campaign_dir, explicit = resolve_registry_arg(None, False, _parser())
    assert path is None
    assert campaign_dir == Path.cwd()
    assert explicit is False
