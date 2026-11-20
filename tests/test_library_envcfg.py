import pytest

from pipelines.library.envcfg import hypostasis_env

YAML = """env:
  MEMPALACE_BACKEND: turbovec
  MEMPALACE_EMBEDDING_MODEL: qwen3-embedding:0.6b
  OTHER: ignored
"""


def _y(tmp_path, text=YAML):
    p = tmp_path / "h.yaml"
    p.write_text(text)
    return p


def test_fills_missing_mempalace_keys(tmp_path):
    out = hypostasis_env(_y(tmp_path), {"A": "1"})
    assert out["MEMPALACE_BACKEND"] == "turbovec"
    assert out["MEMPALACE_EMBEDDING_MODEL"] == "qwen3-embedding:0.6b"
    assert out["A"] == "1" and "OTHER" not in out


def test_does_not_override_set(tmp_path):
    out = hypostasis_env(_y(tmp_path), {"MEMPALACE_BACKEND": "chroma"})
    assert out["MEMPALACE_BACKEND"] == "chroma"


def test_missing_file_errors(tmp_path):
    with pytest.raises(RuntimeError, match="hypostasis"):
        hypostasis_env(tmp_path / "nope.yaml", {})


def test_missing_backend_errors(tmp_path):
    with pytest.raises(RuntimeError, match="MEMPALACE_BACKEND"):
        hypostasis_env(_y(tmp_path, "env:\n  MEMPALACE_X: 1\n"), {})


def test_mine_passes_merged_env(tmp_path, monkeypatch):
    from pipelines.library import cli

    merged = {"MEMPALACE_BACKEND": "turbovec", "X": "y"}
    monkeypatch.setattr(cli, "hypostasis_env", lambda *a, **k: merged)
    monkeypatch.setattr(cli, "require_pilot_palace", lambda *a, **k: tmp_path / "palace")
    seen = {}
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: seen.update(kw))
    assert cli.main(["--workdir", str(tmp_path), "mine"]) == 0
    assert seen["env"] is merged
