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
from campaignlib.selection import BACKENDS


from repo_sources import repo_python_files  # noqa: E402

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


def test_add_backend_args_accepts_claude_code():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="claude-sonnet-4-6")
    campaignlib.add_backend_args(p)
    ns = p.parse_args(["--backend", "claude-code"])
    assert ns.backend == "claude-code"


def test_client_from_args_claude_code_passes_model(monkeypatch):
    """A stale/omitted model must not be dropped for claude-code the way it is
    for anthropic — the subscription still needs to know which Claude model."""
    seen = {}
    monkeypatch.setattr(client_mod, "make_client",
                        lambda backend=None, endpoint=None, model_override=None:
                        seen.update(backend=backend, endpoint=endpoint, model_override=model_override))
    ns = argparse.Namespace(backend="claude-code", endpoint=None, model="claude-opus-4-8")
    client_mod.client_from_args(ns)
    assert seen == {"backend": "claude-code", "endpoint": None,
                    "model_override": "claude-opus-4-8"}


def test_add_backend_args_accepts_codex_cli():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=None)
    campaignlib.add_backend_args(p)
    ns = p.parse_args(["--backend", "codex-cli"])
    assert ns.backend == "codex-cli"


def test_add_backend_args_consumes_the_canonical_backend_tuple():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=None)
    campaignlib.add_backend_args(p)
    backend_action = next(a for a in p._actions if a.dest == "backend")
    assert tuple(backend_action.choices) == BACKENDS


def _intent_field(intent, field):
    """Read the resolver's documented intent fields from a model or mapping."""
    if isinstance(intent, dict):
        return intent[field]
    return getattr(intent, field)


@pytest.mark.parametrize(
    ("backend", "model", "legacy_default", "expected", "explicit"),
    [
        # Omitted Codex models stay omitted so CG_CODEX_MODEL/subscription
        # defaults remain in charge; a Claude legacy default must not leak.
        ("codex-cli", None, "claude-fable-5", None, False),
        # An explicit compatible model is retained unchanged.
        ("codex-cli", "gpt-5-codex", "claude-fable-5", "gpt-5-codex", True),
        # Empty input is the same as omission for Codex.
        ("codex-cli", "   ", "claude-fable-5", None, False),
        # Existing backends retain their command-specific legacy default.
        ("anthropic", None, "claude-fable-5", "claude-fable-5", False),
        ("anthropic", "claude-opus-4-6", "claude-fable-5", "claude-opus-4-6", True),
        ("openrouter", "qwen/qwen3-next-80b", "claude-fable-5", "qwen/qwen3-next-80b", True),
        # Some DGX/dispatcher commands intentionally have no legacy model.
        ("dgx", None, None, None, False),
    ],
)
def test_resolve_cli_model_preserves_omission_and_legacy_default_intent(
    backend, model, legacy_default, expected, explicit
):
    args = argparse.Namespace(backend=backend, model=model)
    intent = client_mod.resolve_cli_model(args, legacy_default=legacy_default)
    assert _intent_field(intent, "effective_model") == expected
    assert _intent_field(intent, "explicit") is explicit


def test_resolve_cli_model_rejects_explicit_incompatible_codex_model():
    args = argparse.Namespace(backend="codex-cli", model="CLAUDE-SONNET-4-6")
    with pytest.raises((ValueError, RuntimeError, SystemExit), match="incompatible|Claude"):
        client_mod.resolve_cli_model(args, legacy_default="claude-fable-5")


def test_make_client_routes_codex_cli(monkeypatch):
    sentinel = object()
    seen = {}
    monkeypatch.setattr(
        client_mod,
        "_CodexCliClient",
        lambda model_override=None: seen.update(model=model_override) or sentinel,
    )
    assert client_mod.make_client(backend="codex-cli", model_override="codex-model") is sentinel
    assert seen == {"model": "codex-model"}


def test_add_backend_args_default_backend_override():
    """A script whose endpoint always resolves (e.g. extract_facts.py) can
    default to dgx instead of anthropic without changing the flag surface."""
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="claude-sonnet-4-6")
    campaignlib.add_backend_args(p, default_backend="dgx")
    ns = p.parse_args([])
    assert ns.backend == "dgx"
    # Still a full opt-out, unlike the old bespoke --dgx-endpoint flags.
    ns_anthropic = p.parse_args(["--backend", "anthropic"])
    assert ns_anthropic.backend == "anthropic"


def test_client_from_args_endpoint_override_wins(monkeypatch):
    """facts_to_state.py's per-thread worker resolves one endpoint from a
    fan-out pool at call time — the explicit override must win over
    args.endpoint (which is None/unused in that path)."""
    seen = {}
    monkeypatch.setattr(client_mod, "make_client",
                        lambda backend=None, endpoint=None, model_override=None:
                        seen.update(backend=backend, endpoint=endpoint, model_override=model_override))
    ns = argparse.Namespace(backend="dgx", endpoint=None, model="Qwen/Qwen2.5-14B-Instruct-AWQ")
    client_mod.client_from_args(ns, endpoint="http://192.168.1.147:8001/v1")
    assert seen["endpoint"] == "http://192.168.1.147:8001/v1"

    # An explicit override still wins even when args.endpoint is also set.
    ns2 = argparse.Namespace(backend="dgx", endpoint="http://stale:8000", model=None)
    client_mod.client_from_args(ns2, endpoint="http://fresh:8001/v1")
    assert seen["endpoint"] == "http://fresh:8001/v1"


# ── Principle V: OpenRouter constructed only inside campaignlib/api ──────────

def test_no_out_of_seam_openrouter_construction():
    """No module outside campaignlib/api may hard-wire OpenRouter's base URL or
    construct the client directly — selection goes through make_client / env."""
    offenders = []
    seam = (REPO_ROOT / "campaignlib" / "api").resolve()
    for py in repo_python_files(REPO_ROOT):
        rp = py.resolve()
        if seam in rp.parents or rp.parent == seam:
            continue
        if "/tests/" in str(rp) or rp.name.startswith("test_"):
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "openrouter.ai" in text or "_OpenRouterClient(" in text:
            offenders.append(str(rp.relative_to(REPO_ROOT)))
    assert not offenders, f"OpenRouter referenced outside the seam: {offenders}"
