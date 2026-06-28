"""Contract tests for the OpenRouter backend seam (spec 001-ensemble-workflow-ui).

Enforces Constitution Principle V (one seam per boundary): OpenRouter is reached
ONLY through campaignlib.api, selection is uniform across scripts, a missing key
fails loudly, and an empty model response is never silently accepted (M3).
"""

import argparse
from pathlib import Path

import pytest

import campaignlib
from campaignlib.api import client as client_mod
from campaignlib.api import backends as backends_mod


REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Routing: make_client dispatches to the OpenRouter client ────────────────

def test_make_client_routes_openrouter(monkeypatch):
    """backend='openrouter' must construct _OpenRouterClient (not Anthropic/DGX)."""
    sentinel = object()
    captured = {}

    def fake_ctor(model_override=None):
        captured["model_override"] = model_override
        return sentinel

    monkeypatch.setattr(client_mod, "_OpenRouterClient", fake_ctor)
    out = client_mod.make_client(backend="openrouter", model_override="anthropic/claude-sonnet-4")
    assert out is sentinel
    assert captured["model_override"] == "anthropic/claude-sonnet-4"


def test_cg_backend_env_selects_openrouter(monkeypatch):
    """CG_BACKEND=openrouter selects the branch with no explicit arg."""
    monkeypatch.setattr(client_mod, "_OpenRouterClient", lambda model_override=None: "OR")
    monkeypatch.setenv("CG_BACKEND", "openrouter")
    assert client_mod.make_client() == "OR"


# ── Missing key fails loudly (no silent fallback) ───────────────────────────

def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        backends_mod._OpenRouterClient()


# ── No-thinking mapping (M3 prevention) ─────────────────────────────────────

def test_extra_body_no_thinking_mapping(monkeypatch):
    """thinking=False maps to OpenRouter's reasoning-disable control."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    # Build only the method under test without constructing the SDK client.
    inst = backends_mod._OpenRouterClient.__new__(backends_mod._OpenRouterClient)
    assert inst.extra_body_for("m", thinking=False) == {"reasoning": {"enabled": False}}
    assert inst.extra_body_for("m", thinking=True) == {}
    monkeypatch.setenv("DGX_NO_THINKING", "1")
    assert inst.extra_body_for("m", thinking=None) == {"reasoning": {"enabled": False}}


# ── Empty-output guard (M3 detection) ───────────────────────────────────────

@pytest.mark.parametrize("bad", [None, "", "   ", "\n\t "])
def test_require_nonempty_raises(bad):
    with pytest.raises(RuntimeError, match="empty output"):
        client_mod._require_nonempty(bad)


def test_require_nonempty_passes_through():
    assert client_mod._require_nonempty("real text") == "real text"


# ── Uniform backend-selection vocabulary + backward compatibility ───────────

def test_add_backend_args_defaults_anthropic():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="claude-sonnet-4-6")
    campaignlib.add_backend_args(p)
    ns = p.parse_args([])
    assert ns.backend == "anthropic"
    assert ns.endpoint is None


def test_client_from_args_anthropic_is_backward_compatible(monkeypatch):
    """Default backend must call make_client(None, None, None) so env still applies."""
    seen = {}
    monkeypatch.setattr(client_mod, "make_client",
                        lambda backend=None, endpoint=None, model_override=None:
                        seen.update(backend=backend, endpoint=endpoint, model_override=model_override))
    ns = argparse.Namespace(backend="anthropic", endpoint=None, model="claude-sonnet-4-6")
    client_mod.client_from_args(ns)
    assert seen == {"backend": None, "endpoint": None, "model_override": None}


def test_client_from_args_openrouter_passes_model(monkeypatch):
    seen = {}
    monkeypatch.setattr(client_mod, "make_client",
                        lambda backend=None, endpoint=None, model_override=None:
                        seen.update(backend=backend, endpoint=endpoint, model_override=model_override))
    ns = argparse.Namespace(backend="openrouter", endpoint=None, model="anthropic/claude-sonnet-4")
    client_mod.client_from_args(ns)
    assert seen == {"backend": "openrouter", "endpoint": None,
                    "model_override": "anthropic/claude-sonnet-4"}


# ── Principle V: OpenRouter constructed only inside campaignlib/api ──────────

def test_no_out_of_seam_openrouter_construction():
    """No module outside campaignlib/api may hard-wire OpenRouter's base URL or
    construct the client directly — selection goes through make_client / env."""
    offenders = []
    seam = (REPO_ROOT / "campaignlib" / "api").resolve()
    for py in REPO_ROOT.rglob("*.py"):
        rp = py.resolve()
        if seam in rp.parents or rp.parent == seam:
            continue
        if "/tests/" in str(rp) or rp.name.startswith("test_"):
            continue
        if ".specify" in rp.parts or "node_modules" in rp.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "openrouter.ai" in text or "_OpenRouterClient(" in text:
            offenders.append(str(rp.relative_to(REPO_ROOT)))
    assert not offenders, f"OpenRouter referenced outside the seam: {offenders}"
