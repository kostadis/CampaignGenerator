"""Every backend option a ``delta`` leaf accepts reaches the client, and a recorded backend is honoured (#644).

``add_backend_args`` registers ``--endpoint`` and the effort / thinking options on the delta leaves; they
must take effect at each model call site, and an explicit ``anthropic`` must beat ``CG_BACKEND``.
"""

from __future__ import annotations

import argparse
import os

import pytest

import campaignlib

from _delta_us2 import copy_fixture, make_plan
from campaignlib.api import client as client_mod
from pipelines.summary_native.delta import (
    associations, census as cs, grounding_check as gc, grounding_edits as ge, rebase_propose)
from pipelines.summary_native.delta.client import client_options, delta_client


class _Stop(Exception):
    pass


@pytest.fixture
def made(monkeypatch):
    """Record every ``make_client`` kwargs set the seam builds."""
    calls: list[dict] = []
    monkeypatch.setattr(client_mod, "make_client",
                        lambda **k: calls.append({**k, "_env": os.environ.get("CG_BACKEND")}) or object())
    monkeypatch.delenv("CG_BACKEND", raising=False)
    return calls


def _stop(*a, **k):
    raise _Stop


DGX = dict(endpoint="http://boxB:8001", codex_reasoning_effort=None, claude_code_effort=None,
           claude_code_thinking=None, batch=False)


def test_client_options_collects_only_what_the_leaf_parsed():
    ns = argparse.Namespace(endpoint="http://x", batch=False, backend="dgx", model="m")
    assert client_options(ns) == {"endpoint": "http://x", "batch": False}


def test_endpoint_and_codex_effort_reach_the_client(made):
    delta_client("codex-cli", "m", {"endpoint": None, "codex_reasoning_effort": "high"})
    assert made[-1]["reasoning_effort"] == "high"
    delta_client("dgx", "m", {"endpoint": "http://boxB:8001"})
    assert made[-1]["endpoint"] == "http://boxB:8001" and made[-1]["backend"] == "dgx"


def test_claude_code_effort_reaches_the_client(made):
    delta_client("claude-code", "claude-opus-5-5", {"claude_code_effort": "high", "claude_code_thinking": None})
    assert made[-1]["claude_code_effort"] == "high"


def test_explicit_anthropic_beats_cg_backend(made, monkeypatch):
    monkeypatch.setenv("CG_BACKEND", "claude-code")
    delta_client("anthropic", "m")
    # make_client resolves `backend or CG_BACKEND`: with the variable masked it can only pick anthropic.
    assert made[-1]["backend"] is None and made[-1]["_env"] is None
    assert os.environ["CG_BACKEND"] == "claude-code"  # restored afterwards


def test_an_unrecorded_backend_still_defers_to_cg_backend(made, monkeypatch):
    monkeypatch.setenv("CG_BACKEND", "claude-code")
    delta_client(None, "m")
    assert made[-1]["backend"] is None  # make_client reads CG_BACKEND itself


# ── each call site hands its options on ─────────────────────────────────────────────────────────

def test_grounding_edits_site(made, monkeypatch):
    monkeypatch.setattr(ge, "stream_api", _stop)
    with pytest.raises(_Stop):
        ge.propose_edits({"party": b"a\n"}, {"s.md": "t"}, plan_id="p", baseline_ref="r", backend="dgx",
                         model="m", client_options=DGX)
    assert made[-1]["endpoint"] == "http://boxB:8001" and made[-1]["backend"] == "dgx"


def test_grounding_check_site(made, monkeypatch):
    monkeypatch.setattr(gc, "stream_api", _stop)
    with pytest.raises(_Stop):
        gc.propose_consistency_findings({"party": b"a\n"}, {"party": b"b\n"}, {"s.md": "t"}, backend="dgx",
                                        model="m", client_options=DGX)
    assert made[-1]["endpoint"] == "http://boxB:8001"


def test_associations_site(made, tmp_path, monkeypatch):
    monkeypatch.setattr(campaignlib, "call_api", _stop)
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    with pytest.raises(_Stop):
        associations.propose(root, plan, [], backend="dgx", model="m", client_options=DGX)
    assert made[-1]["endpoint"] == "http://boxB:8001" and made[-1]["backend"] == "dgx"


def test_census_site(made, tmp_path, monkeypatch):
    monkeypatch.setattr(campaignlib, "call_api", _stop)
    root = copy_fixture(tmp_path)
    c = cs.build_census(root, make_plan(root))
    with pytest.raises(_Stop):
        cs.propose_triage_hints(c, backend="dgx", model="m", client_options=DGX)
    assert made[-1]["endpoint"] == "http://boxB:8001"


def test_rebase_propose_site_uses_the_shared_factory(monkeypatch):
    """rebase_propose has no cheap fixture here; its call site is the same one-line delta_client call."""
    import inspect
    src = inspect.getsource(rebase_propose.propose)
    assert "delta_client(backend, model, client_options)" in src
