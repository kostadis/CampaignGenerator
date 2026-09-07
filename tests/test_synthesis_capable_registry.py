"""``ensemble.synthesis_capable`` must judge capability, not familiarity.

The synthesis-capability rule (FR-014 / R6) has been three things. A frozen
literal listing the Claude ids of the day, which drifted: by the time
``docs/config/platform-isolation.md`` Phase 5a refreshed ``server.config.MODELS``,
it still carried the retired ``claude-sonnet-4-20250514`` and knew nothing of
Opus 5 / Sonnet 5 / Fable 5 — so a GM who picked the strongest model available
got a spurious "not on the synthesis-capable list — output quality may degrade"
warning on every synthesize run. Then a set *derived* from ``MODELS`` minus the
Haiku tier, which narrowed that window without closing it: a registry refresh
fixed the drift, and the next model release reopened it.

Feature 024 (``specs/024-claude-model-freetext/``) replaced the set with a
predicate over the id's shape. A membership test answers "have I heard of this
id" and then reports the answer as though it were "is this id strong enough" —
two different claims that come apart on precisely the day it matters.

These tests pin that predicate, because the failure mode is silent in exactly
the way the old literal's was: a wrong answer produces a *warning string*, never
a non-zero exit, so nothing looks broken without asserting on it directly.

The tests below the fold are the ones that can catch a *future* regression;
everything above it can only catch a present one, since every id it knows about
is in ``MODELS`` by construction.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from campaignlib.constants import DEFAULT_MODEL
from server.config import MODELS
from server.main import app
from server.routers.ensemble import synthesis_capable

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
    # world_state synthesis now requires an entity registry (Phase 2 of the
    # registry migration) — this module is about the capability warning, not
    # the registry gate, so give every call one for free.
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "entity_registry.yaml").write_text("version: 1\nentities: []\n")
    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "world_state", **params})
    assert r.status_code == 200, r.text
    return r.text


# ── The derivation itself ────────────────────────────────────────────────────

@pytest.mark.parametrize("model_id", [m for m in MODELS if "haiku" not in m])
def test_every_registry_model_above_haiku_is_synthesis_capable(model_id):
    """Every model the app suggests must be one it does not then disparage.
    Adding a model to ``server.config.MODELS`` must make it synthesis-capable
    without a second edit anywhere — that second edit is precisely what never
    happened last time, and the predicate now makes it impossible to need."""
    assert synthesis_capable(model_id)


@pytest.mark.parametrize("model_id", [m for m in MODELS if "haiku" in m])
def test_haiku_tier_is_excluded(model_id):
    """The one capability judgment this module makes: the stated bar is "at
    least as capable as Sonnet", which rules the Haiku tier out. It survived
    the move to a predicate — that was the point of keeping one."""
    assert not synthesis_capable(model_id)


def test_a_retired_sonnet_is_not_reported_as_weak():
    """Replaces ``test_retired_date_suffixed_id_is_gone`` (feature 024).

    That test asserted ``claude-sonnet-4-20250514`` was absent from the derived
    set — it pinned *snapshot freshness*, a property that stops existing once
    nothing is snapshotted. Under the predicate the id is capable, and that is
    right twice over: it is a Sonnet, and the bar is "at least as capable as
    Sonnet"; and "may be too weak" was always the wrong diagnosis for a retired
    model. Retirement is reported by the provider refusing the call. Answering
    it with a capability warning sends the GM to change a knob that is not the
    problem.
    """
    assert synthesis_capable("claude-sonnet-4-20250514")


@pytest.mark.parametrize("model_id", ["openai/gpt-5", "google/gemini-2.5-pro"])
def test_frontier_third_party_ids_survive_the_derivation(model_id):
    """MODELS is the *Anthropic* registry, so the frontier non-Anthropic ids
    can't be derived from it. The predicate must not quietly drop them.

    Narrowed to two ids. This used to parametrise over four, including
    ``anthropic/claude-sonnet-4`` and ``anthropic/claude-opus-4`` — but once
    the predicate grew its ``anthropic/claude-`` rule those two passed via the
    prefix and would have kept passing with the set emptied, so the test read
    as twice the coverage it had. These two are the ones that actually exercise
    ``_THIRD_PARTY_SYNTHESIS_CAPABLE``; the vendor-prefixed pair is covered by
    ``test_an_unreleased_anthropic_id_via_openrouter_is_capable``, which is
    where that rule belongs.
    """
    assert synthesis_capable(model_id)


def test_platform_default_never_warns_about_itself():
    """The default a run falls back to must not be a model the same code path
    then flags as too weak — that combination is incoherent by construction."""
    assert synthesis_capable(DEFAULT_MODEL)


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
    """The warning is gated on ``backend != "anthropic"``, so the Anthropic
    path never emits it whatever model is chosen.

    Updated by feature 003. This used to demonstrate the gate by passing a
    *Qwen* id on the anthropic backend and relying on the router silently
    dropping it — the substitution FR-011 removed, so that request is now a
    409 and cannot reach the warning logic at all. The gate itself is
    unchanged; the test now shows it with a model that legitimately belongs
    to the backend, which is what it was always trying to assert.
    """
    haiku = next((m for m in MODELS if "haiku" in m), "claude-haiku-4-5")
    body = _synthesize(monkeypatch, tmp_path, backend="anthropic", model=haiku)
    assert WARNING_FRAGMENT not in body


# ── Feature 024: "unlisted" and "weak" are different claims ──────────────────
#
# The tests above pin the derivation against the *current* registry. They cannot
# catch the failure this feature exists to fix, because every id they know about
# is by definition already in MODELS. These use ids that are not, and will not
# be until Anthropic ships them.

UNRELEASED_OPUS = "claude-opus-6"
UNRELEASED_HAIKU = "claude-haiku-6"


def test_an_unreleased_anthropic_id_is_capable():
    """The whole feature, in one assertion.

    ``MODELS`` is a hand-maintained snapshot, so the day a model ships it is
    absent from it — and that absence used to read as "too weak", warning the GM
    about the strongest model they had. Capability is judged from the id's shape
    now, exactly as ``campaignlib.selection.compatible`` already judges
    backend fit.
    """
    assert synthesis_capable(UNRELEASED_OPUS)


def test_an_unreleased_haiku_id_is_not_capable():
    """S1 — the ordering, and the only test that can catch a reversal.

    ``claude-haiku-6`` satisfies *both* the tier exclusion and the ``claude-``
    prefix. If the prefix check runs first it wins and every future Haiku id is
    silently promoted to synthesis-capable — FR-013 gone, with no failing test,
    because every Haiku id the other tests know about is in ``MODELS`` and would
    still be caught by substring there.
    """
    assert not synthesis_capable(UNRELEASED_HAIKU)


def test_an_unreleased_anthropic_id_via_openrouter_is_capable():
    """Rule 4. ``_THIRD_PARTY_SYNTHESIS_CAPABLE`` lists ``anthropic/claude-*``
    ids by hand, so the OpenRouter spelling goes stale on the same schedule the
    bare one did. The vendor prefix makes it unambiguously Anthropic."""
    assert synthesis_capable("anthropic/" + UNRELEASED_OPUS)


def test_absent_model_is_capable():
    """Nothing chosen is not a weak choice. Resolution falls back; it does not
    warn about a model the GM never named."""
    assert synthesis_capable(None)
    assert synthesis_capable("")
    assert synthesis_capable("   ")


def test_a_local_model_is_still_not_capable():
    """Rule 6, unchanged. This feature widens the capable set; it must never
    widen the *incapable* set, and must not empty it either."""
    assert not synthesis_capable("Qwen/Qwen3-Next-80B-A3B-Instruct-FP8")


def test_no_warning_for_an_unreleased_anthropic_model(monkeypatch, tmp_path):
    """End to end, on the backend where this actually misfired.

    The warning is gated on ``backend != "anthropic"``, so it never fired on the
    metered API at all — it fired on ``claude-code``, the *subscription* backend,
    which is precisely where a GM reaches for a model that shipped this morning.
    """
    body = _synthesize(monkeypatch, tmp_path, backend="claude-code", model=UNRELEASED_OPUS)
    assert WARNING_FRAGMENT not in body


def test_warning_still_fires_for_an_unreleased_haiku_model(monkeypatch, tmp_path):
    """The other half of FR-013: opening the gate to unknown ids must not
    silence it for weak ones, including weak ones nobody has published yet."""
    body = _synthesize(monkeypatch, tmp_path, backend="claude-code", model=UNRELEASED_HAIKU)
    assert WARNING_FRAGMENT in body


def test_capability_is_judged_case_insensitively():
    """A pasted id with vendor-doc capitalisation is the same model.

    ``Anthropic/Claude-Opus-5`` is a legal OpenRouter pair (``compatible``
    accepts it — it is vendor-namespaced), so it reaches the warning. The
    predicate folded case for the tier exclusion but not for the prefix rules,
    so it fell through to the hand-maintained set and earned the exact spurious
    "may be too weak" warning this feature exists to remove.

    The tier exclusion must survive folding too, in both spellings.
    """
    assert synthesis_capable("Anthropic/Claude-Opus-5")
    assert synthesis_capable("CLAUDE-OPUS-6")
    assert not synthesis_capable("Claude-Haiku-6")
    assert not synthesis_capable("Anthropic/Claude-Haiku-6")
