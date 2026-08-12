"""Tests for the Session Doc Editor verification surface (spec 007, Phase 6)."""

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import campaignlib  # noqa: E402

# See tests/test_locate_quote_parity.py for why this guard exists.
_resolved = Path(campaignlib.__file__).resolve().parent.parent
if _resolved != _REPO_ROOT:
    pytest.skip(
        f"campaignlib resolved to {_resolved}, not this worktree ({_REPO_ROOT}).",
        allow_module_level=True,
    )

from server.session_editor_config_shared import (  # noqa: E402
    SessionEditorConfig,
    VerifyKnobs,
)
from server.routers.scene_editor import _parse_quote_report_counts  # noqa: E402


# ── Config schema ────────────────────────────────────────────────────────────

def test_verify_defaults():
    cfg = SessionEditorConfig()
    assert cfg.verify.threshold == 0.85
    assert cfg.verify.min_tokens == 4
    assert cfg.verify.report_only is False


def test_verify_has_no_enabled_flag():
    """A check you can switch off in config is off exactly when it matters."""
    assert "enabled" not in VerifyKnobs.model_fields


def test_unknown_verify_key_is_rejected():
    """extra='forbid' — a typo must fail loudly, not be silently ignored."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SessionEditorConfig(verify={"threshhold": 0.9})


def test_verify_round_trips_through_yaml():
    cfg = SessionEditorConfig(verify={"threshold": 0.91, "report_only": True})
    dumped = cfg.model_dump(mode="json", by_alias=True)
    assert dumped["verify"]["threshold"] == 0.91
    assert SessionEditorConfig(**dumped).verify.report_only is True


# ── Report-count parsing ─────────────────────────────────────────────────────

REPORT = """# Quote Verification Report

**Threshold**: 0.85 (near/unverified boundary)

| verdict | count | share |
|---|---|---|
| verified | 339 | 65% |
| near | 139 | 27% |
| **unverified** | **39** | 7% |
| unscored | 3 | 1% |
| exempt | 2 | 0% |

## Not checked
"""


def test_counts_parse_including_the_bolded_row(tmp_path):
    p = tmp_path / "quote_report.md"
    p.write_text(REPORT, encoding="utf-8")
    counts = _parse_quote_report_counts(p)
    assert counts == {"verified": 339, "near": 139, "unverified": 39,
                      "unscored": 3, "exempt": 2}


def test_missing_report_yields_none_not_zero(tmp_path):
    """'no unverified quotes' and 'we could not tell' must not look alike."""
    counts = _parse_quote_report_counts(tmp_path / "absent.md")
    assert all(v is None for v in counts.values())


def test_unparseable_report_yields_none_not_zero(tmp_path):
    p = tmp_path / "quote_report.md"
    p.write_text("# Not a report\n\nnothing here\n", encoding="utf-8")
    assert _parse_quote_report_counts(p)["unverified"] is None


def test_none_path_is_handled():
    assert _parse_quote_report_counts(None)["verified"] is None


def test_clean_report_parses_as_zero_not_none(tmp_path):
    p = tmp_path / "quote_report.md"
    p.write_text(
        "| verdict | count | share |\n|---|---|---|\n"
        "| verified | 10 | 100% |\n", encoding="utf-8")
    counts = _parse_quote_report_counts(p)
    assert counts["verified"] == 10
    assert counts["unverified"] == 0


# ── Route wiring ─────────────────────────────────────────────────────────────

def test_verify_route_is_registered():
    from server.routers.scene_editor import router
    paths = {r.path for r in router.routes}
    assert "/verify" in paths


def test_verify_cmd_forwards_no_model_selection():
    """FR-003 — verification calls no model, so no backend/batch may be sent.

    Checks the function *body*, not its source text: the docstring explains
    why ``_selection_args`` is absent and would otherwise match the grep.
    """
    import ast
    import inspect
    from server.routers import scene_editor

    fn = ast.parse(inspect.getsource(scene_editor._build_verify_cmd)).body[0]
    if ast.get_docstring(fn):
        fn.body = fn.body[1:]
    body = ast.unparse(fn)

    assert "_selection_args" not in body
    for flag in ("--backend", "--model", "--batch", "--fast", "--endpoint"):
        assert flag not in body


# ── Refusal count (extraction contract #250) ─────────────────────────────────

REPORT_WITH_REFUSALS = REPORT.replace(
    "\n## Not checked",
    "\n**Refused by the extraction contract (#250)**: 16 — R1 4, R3 12.\n"
    "\n## Not checked",
)


def test_refusal_count_parses(tmp_path):
    from server.routers.scene_editor import _parse_quote_report_refusals
    p = tmp_path / "quote_report.md"
    p.write_text(REPORT_WITH_REFUSALS, encoding="utf-8")
    assert _parse_quote_report_refusals(p) == 16


def test_refusal_count_is_none_not_zero_when_absent(tmp_path):
    """A report written before refusals existed must not read as 'found none'
    — the same distinction the verdict counts make."""
    from server.routers.scene_editor import _parse_quote_report_refusals
    p = tmp_path / "quote_report.md"
    p.write_text(REPORT, encoding="utf-8")
    assert _parse_quote_report_refusals(p) is None
    assert _parse_quote_report_refusals(tmp_path / "nope.md") is None


def test_refusals_do_not_disturb_the_verdict_counts(tmp_path):
    p = tmp_path / "quote_report.md"
    p.write_text(REPORT_WITH_REFUSALS, encoding="utf-8")
    assert _parse_quote_report_counts(p) == {"verified": 339, "near": 139,
                                            "unverified": 39, "unscored": 3,
                                            "exempt": 2}


# ── JSON sidecar preference (#264) ──────────────────────────────────────────
#
# sd_verify_quotes now writes quote_report.json beside quote_report.md. These
# functions must prefer it when it exists and parses, and fall back to the
# markdown-regex path — a one-release compatibility shim — otherwise. The
# "no unverified quotes" vs "we could not tell" distinction (None, never 0)
# must hold on both paths.

REPORT_JSON = {
    "schema_version": 1,
    "generated_at": "2026-01-01T00:00:00",
    "transcript": "/tmp/s.vtt",
    "threshold": 0.85,
    "min_tokens": 4,
    "artifacts": ["/tmp/session-summary.md"],
    "counts": {"verified": 339, "near": 139, "unverified": 39,
               "unscored": 3, "exempt": 2},
    "refusals": {"total": 16, "by_rule": {"R1": 4, "R3": 12}},
    "not_checked": [],
    "claims": {},
}


def test_json_preferred_over_regex_when_both_present(tmp_path):
    """The JSON sidecar wins even when it disagrees with the markdown table
    beside it — proof this is a real preference, not a coincidence of
    identical fixtures."""
    md = tmp_path / "quote_report.md"
    md.write_text(REPORT, encoding="utf-8")
    stale = dict(REPORT_JSON)
    stale["counts"] = {"verified": 1, "near": 0, "unverified": 0,
                       "unscored": 0, "exempt": 0}
    md.with_suffix(".json").write_text(json.dumps(stale), encoding="utf-8")
    assert _parse_quote_report_counts(md) == stale["counts"]


def test_regex_fallback_when_json_sidecar_absent(tmp_path):
    md = tmp_path / "quote_report.md"
    md.write_text(REPORT, encoding="utf-8")
    assert not md.with_suffix(".json").exists()
    assert _parse_quote_report_counts(md) == {"verified": 339, "near": 139,
                                              "unverified": 39, "unscored": 3,
                                              "exempt": 2}


def test_corrupt_json_sidecar_falls_back_to_regex(tmp_path):
    md = tmp_path / "quote_report.md"
    md.write_text(REPORT, encoding="utf-8")
    md.with_suffix(".json").write_text("{not valid json", encoding="utf-8")
    assert _parse_quote_report_counts(md) == {"verified": 339, "near": 139,
                                              "unverified": 39, "unscored": 3,
                                              "exempt": 2}


def test_missing_report_and_json_still_yields_none_not_zero(tmp_path):
    """Neither file exists — a missing report, not a clean one."""
    from server.routers.scene_editor import _parse_quote_report_refusals
    counts = _parse_quote_report_counts(tmp_path / "absent.md")
    assert all(v is None for v in counts.values())
    assert _parse_quote_report_refusals(tmp_path / "absent.md") is None


def test_json_and_regex_agree_on_the_same_underlying_report(tmp_path):
    """quote_report.md and quote_report.json describe the same run (as
    sd_verify_quotes always writes them); either parsing path must recover
    the same counts and refusal total."""
    from server.routers.scene_editor import _parse_quote_report_refusals
    md = tmp_path / "quote_report.md"
    md.write_text(REPORT_WITH_REFUSALS, encoding="utf-8")
    md.with_suffix(".json").write_text(json.dumps(REPORT_JSON), encoding="utf-8")

    counts_via_json = _parse_quote_report_counts(md)
    refused_via_json = _parse_quote_report_refusals(md)

    md.with_suffix(".json").unlink()
    counts_via_regex = _parse_quote_report_counts(md)
    refused_via_regex = _parse_quote_report_refusals(md)

    expected_counts = {"verified": 339, "near": 139, "unverified": 39,
                       "unscored": 3, "exempt": 2}
    assert counts_via_json == counts_via_regex == expected_counts
    assert refused_via_json == refused_via_regex == 16


def test_refusals_json_preferred_over_regex(tmp_path):
    from server.routers.scene_editor import _parse_quote_report_refusals
    md = tmp_path / "quote_report.md"
    md.write_text(REPORT_WITH_REFUSALS, encoding="utf-8")  # says 16
    stale = dict(REPORT_JSON)
    stale["refusals"] = {"total": 99, "by_rule": {"R1": 50, "R3": 49}}
    md.with_suffix(".json").write_text(json.dumps(stale), encoding="utf-8")
    assert _parse_quote_report_refusals(md) == 99


def test_refusals_corrupt_json_falls_back_to_regex(tmp_path):
    from server.routers.scene_editor import _parse_quote_report_refusals
    md = tmp_path / "quote_report.md"
    md.write_text(REPORT_WITH_REFUSALS, encoding="utf-8")
    md.with_suffix(".json").write_text("[]", encoding="utf-8")  # valid JSON, wrong shape
    assert _parse_quote_report_refusals(md) == 16
