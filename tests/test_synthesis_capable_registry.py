"""``ensemble.SYNTHESIS_CAPABLE`` must track the model registry.

The synthesis-capability allow-list (FR-014 / R6) used to be a frozen literal
listing the Claude ids of the day. It drifted: by the time
``docs/config/platform-isolation.md`` Phase 5a refreshed ``server.config.MODELS``,
the allow-list still carried the retired ``claude-sonnet-4-20250514`` and knew
nothing of Opus 5 / Sonnet 5 / Fable 5 — so a GM who picked the strongest model
available got a spurious "not on the synthesis-capable list — output quality may
degrade" warning on every synthesize run.

``SYNTHESIS_CAPABLE`` is now derived from ``MODELS`` minus the Haiku tier, plus
an explicit set of frontier non-Anthropic ids that no registry covers. These
tests pin that derivation, because the failure mode is silent in exactly the way
the old literal's was: a wrong allow-list produces a *warning string*, never a
non-zero exit, so nothing looks broken without asserting on it directly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from campaignlib.constants import DEFAULT_MODEL
from server.config import MODELS
from server.main import app
from server.routers.ensemble import SYNTHESIS_CAPABLE

client = TestClient(app)

WARNING_FRAGMENT = "is not on the synthesis-capable list"


def _capture_cmd(monkeypatch) -> dict:
    """Patch the ensemble router's ``stream_subprocess`` so a run never spawns
    a real CLI. Mirrors ``tests/test_ensemble_gates.py``'s helper."""
    captured: dict = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        captured["env_extra"] = env_extra
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("server.routers.ensemble.stream_subprocess", fake_stream_subprocess)
    return captured


def _synthesize(monkeypatch, tmp_path, **params) -> str:
    _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "world_state", **params})
    assert r.status_code == 200, r.text
    return r.text


# ── The derivation itself ────────────────────────────────────────────────────

@pytest.mark.parametrize("model_id", [m for m in MODELS if "haiku" not in m])
def test_every_registry_model_above_haiku_is_synthesis_capable(model_id):
    """The registry is the source. Adding a model to ``server.config.MODELS``
    must make it synthesis-capable without a second edit here — that second
    edit is precisely what never happened last time."""
    assert model_id in SYNTHESIS_CAPABLE


@pytest.mark.parametrize("model_id", [m for m in MODELS if "haiku" in m])
def test_haiku_tier_is_excluded(model_id):
    """The one capability judgment this module makes: the stated bar is "at
    least as capable as Sonnet", which rules the Haiku tier out."""
    assert model_id not in SYNTHESIS_CAPABLE


def test_retired_date_suffixed_id_is_gone():
    """``claude-sonnet-4-20250514`` retired 2026-06-15 and Phase 5a dropped it
    from ``MODELS``; the derivation must drop it here too."""
    assert "claude-sonnet-4-20250514" not in SYNTHESIS_CAPABLE


@pytest.mark.parametrize("model_id", [
    "anthropic/claude-sonnet-4", "anthropic/claude-opus-4",
    "openai/gpt-5", "google/gemini-2.5-pro",
])
def test_frontier_third_party_ids_survive_the_derivation(model_id):
    """MODELS is the *Anthropic* registry, so the OpenRouter/frontier ids can't
    be derived from it. Deriving must not quietly drop them."""
    assert model_id in SYNTHESIS_CAPABLE


def test_platform_default_never_warns_about_itself():
    """The default a run falls back to must not be a model the same code path
    then flags as too weak — that combination is incoherent by construction."""
    assert DEFAULT_MODEL in SYNTHESIS_CAPABLE


# ── The behaviour the derivation exists to produce ───────────────────────────

@pytest.mark.parametrize("model_id", [m for m in MODELS if "haiku" not in m])
def test_no_warning_for_a_current_registry_model(monkeypatch, tmp_path, model_id):
    """A GM picking any current registry model for claude-code synthesis sees
    no capability warning. This is the regression that shipped: opus-5 warned."""
    body = _synthesize(monkeypatch, tmp_path, backend="claude-code", model=model_id)
    assert WARNING_FRAGMENT not in body


def test_warning_still_fires_for_a_local_open_model(monkeypatch, tmp_path):
    """The warning is not defanged — a local 80B open model still trips it."""
    body = _synthesize(monkeypatch, tmp_path, backend="dgx",
                       model="Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
                       endpoint="http://spark:8001/v1")
    assert WARNING_FRAGMENT in body


def test_warning_fires_for_the_haiku_tier(monkeypatch, tmp_path):
    """The excluded tier warns rather than silently passing."""
    haiku = next((m for m in MODELS if "haiku" in m), "claude-haiku-4-5")
    body = _synthesize(monkeypatch, tmp_path, backend="claude-code", model=haiku)
    assert WARNING_FRAGMENT in body


def test_anthropic_backend_never_warns(monkeypatch, tmp_path):
    """Pre-existing behaviour, pinned so this change doesn't alter it: the
    warning is gated on ``backend != "anthropic"`` because the anthropic path
    drops the model entirely (see test_ensemble_gates.py's
    ``test_synthesize_ignores_stale_model_for_anthropic``)."""
    body = _synthesize(monkeypatch, tmp_path, backend="anthropic",
                       model="Qwen/Qwen3-Next-80B-A3B-Instruct-FP8")
    assert WARNING_FRAGMENT not in body
