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


def _write_report(tmp_path, *, markdown=REPORT, sidecar=REPORT_JSON):
    """A narration dir's report pair. ``sidecar=None`` writes markdown only —
    a pre-#264 report, which no longer yields counts."""
    md = tmp_path / "quote_report.md"
    if markdown is not None:
        md.write_text(markdown, encoding="utf-8")
    if sidecar is not None:
        md.with_suffix(".json").write_text(
            sidecar if isinstance(sidecar, str) else json.dumps(sidecar),
            encoding="utf-8")
    return md


def test_counts_come_from_the_json_sidecar(tmp_path):
    counts = _parse_quote_report_counts(_write_report(tmp_path))
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
    """The other half of the contract: a run that genuinely found nothing
    reports 0, not None. Only *absence of knowledge* is None."""
    clean = dict(REPORT_JSON)
    clean["counts"] = {"verified": 10, "near": 0, "unverified": 0,
                       "unscored": 0, "exempt": 0}
    counts = _parse_quote_report_counts(_write_report(tmp_path, sidecar=clean))
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

def test_refusal_count_parses(tmp_path):
    from server.routers.scene_editor import _parse_quote_report_refusals
    assert _parse_quote_report_refusals(_write_report(tmp_path)) == 16


def test_refusal_count_is_none_not_zero_when_absent(tmp_path):
    """A sidecar written before refusals existed must not read as 'found none'
    — the same distinction the verdict counts make."""
    from server.routers.scene_editor import _parse_quote_report_refusals
    without = {k: v for k, v in REPORT_JSON.items() if k != "refusals"}
    assert _parse_quote_report_refusals(
        _write_report(tmp_path, sidecar=without)) is None
    assert _parse_quote_report_refusals(tmp_path / "nope.md") is None


def test_refusal_count_of_zero_is_not_none(tmp_path):
    """...and a run that refused nothing reports 0, not None."""
    from server.routers.scene_editor import _parse_quote_report_refusals
    none_refused = dict(REPORT_JSON)
    none_refused["refusals"] = {"total": 0, "by_rule": {}}
    assert _parse_quote_report_refusals(
        _write_report(tmp_path, sidecar=none_refused)) == 0


def test_refusals_do_not_disturb_the_verdict_counts(tmp_path):
    assert _parse_quote_report_counts(_write_report(tmp_path)) == {
        "verified": 339, "near": 139, "unverified": 39, "unscored": 3,
        "exempt": 2}


# ── The sidecar is the only source (#264) ───────────────────────────────────
#
# sd_verify_quotes writes quote_report.json beside quote_report.md, and these
# functions read *only* the sidecar. The markdown-regex fallback was a
# compatibility shim for narration dirs that ran verify before the sidecar
# existed; it has been deleted. The tests below pin the consequence: markdown
# alone now means "we could not tell" (None), never a count — and never 0.

def test_markdown_without_a_sidecar_yields_none_not_counts(tmp_path):
    """The deleted shim's case. A pre-#264 report still on disk parses to
    None, so the status strip goes amber instead of quoting stale numbers."""
    from server.routers.scene_editor import _parse_quote_report_refusals
    md = _write_report(tmp_path, sidecar=None)
    assert md.exists() and not md.with_suffix(".json").exists()
    assert all(v is None for v in _parse_quote_report_counts(md).values())
    assert _parse_quote_report_refusals(md) is None


def test_the_markdown_table_is_never_read(tmp_path):
    """Even a perfectly well-formed table beside a sidecar that disagrees:
    the sidecar wins outright, so no regex can be quietly reintroduced."""
    stale = dict(REPORT_JSON)
    stale["counts"] = {"verified": 1, "near": 0, "unverified": 0,
                       "unscored": 0, "exempt": 0}
    md = _write_report(tmp_path, sidecar=stale)  # markdown says 339/139/39
    assert _parse_quote_report_counts(md) == stale["counts"]


def test_refusals_come_from_the_sidecar_not_the_markdown(tmp_path):
    from server.routers.scene_editor import _parse_quote_report_refusals
    stale = dict(REPORT_JSON)
    stale["refusals"] = {"total": 99, "by_rule": {"R1": 50, "R3": 49}}
    assert _parse_quote_report_refusals(
        _write_report(tmp_path, sidecar=stale)) == 99


@pytest.mark.parametrize("payload", ["{not valid json", "[]", '"a string"'])
def test_unusable_sidecar_yields_none_not_stale_markdown_counts(tmp_path, payload):
    """Corrupt, wrong-shaped, or not-an-object — each must read as "could not
    tell" rather than silently falling back to the markdown beside it."""
    from server.routers.scene_editor import _parse_quote_report_refusals
    md = _write_report(tmp_path, sidecar=payload)
    assert all(v is None for v in _parse_quote_report_counts(md).values())
    assert _parse_quote_report_refusals(md) is None


def test_missing_report_and_json_still_yields_none_not_zero(tmp_path):
    """Neither file exists — a missing report, not a clean one."""
    from server.routers.scene_editor import _parse_quote_report_refusals
    counts = _parse_quote_report_counts(tmp_path / "absent.md")
    assert all(v is None for v in counts.values())
    assert _parse_quote_report_refusals(tmp_path / "absent.md") is None


def _status_for(narration_dir):
    """``/pipeline-status``'s verify entry for a campaign whose only
    configured path is the narration dir holding the report."""
    from server.routers.scene_editor import api_pipeline_status
    from server.session_editor_config_service import ResolvedEditorConfig
    base = SessionEditorConfig()
    cfg = ResolvedEditorConfig(
        paths=base.paths.model_copy(
            update={"narration_dir": str(narration_dir)}),
        extract=base.extract, narrate=base.narrate, scrub=base.scrub,
        backends=base.backends, session_name=None, profiles=[],
        active_profile=None, model=None,
        work_dir=str(narration_dir), campaign_dir=str(narration_dir),
        config_dir=str(narration_dir),
    )
    return api_pipeline_status(cfg)["verify"]


def test_report_without_a_sidecar_shows_amber_not_a_clean_run(tmp_path):
    """The whole point of deleting the shim: a pre-#264 report is reported as
    'we could not tell' (amber) rather than quoting numbers off the markdown.
    Nothing here is auto-corrected — the GM is told to re-run verify."""
    _write_report(tmp_path, sidecar=None)
    status = _status_for(tmp_path)
    assert status["status"] == "warn"
    assert status["unverified"] is None
    assert status["refused"] is None


def test_report_with_a_clean_sidecar_shows_green(tmp_path):
    """The contrast case — 0 findings really is green, so the amber above is
    a real signal and not just 'verify always warns now'."""
    clean = dict(REPORT_JSON)
    clean["counts"] = {"verified": 10, "near": 0, "unverified": 0,
                       "unscored": 0, "exempt": 0}
    clean["refusals"] = {"total": 0, "by_rule": {}}
    _write_report(tmp_path, sidecar=clean)
    status = _status_for(tmp_path)
    assert status["status"] == "ok"
    assert status["unverified"] == 0
    assert status["refused"] == 0


def test_no_regex_over_the_report_survives_in_the_module():
    """The shim is gone for good — a future edit that reintroduces a regex
    over the markdown report fails here rather than silently restoring the
    two-source ambiguity this deletion removed (#264)."""
    import inspect
    from server.routers import scene_editor

    src = inspect.getsource(scene_editor)
    assert "_REPORT_ROW_RE" not in src
    assert "_REPORT_REFUSED_RE" not in src
    for fn in (scene_editor._parse_quote_report_counts,
               scene_editor._parse_quote_report_refusals):
        body = inspect.getsource(fn)
        assert "read_text" not in body, f"{fn.__name__} reads the markdown again"


def test_a_run_that_checked_nothing_is_not_green(tmp_path):
    """The report says it itself: "No quotes found. Nothing was checked — this
    is not the same as everything passing." The strip has to agree. A wrong
    input file, or a summary using inline "…" where the parser wants > "…"
    blockquotes, both serialise as all-zero counts."""
    nothing = dict(REPORT_JSON)
    nothing["counts"] = {"verified": 0, "near": 0, "unverified": 0,
                         "unscored": 0, "exempt": 0}
    nothing["refusals"] = {"total": 0, "by_rule": {}}
    _write_report(tmp_path, sidecar=nothing)
    assert _status_for(tmp_path)["status"] == "warn"


def test_unknown_refusal_count_is_not_green(tmp_path):
    """The None-vs-0 rule the verdict counts get, applied to refusals. A
    sidecar written before refusals existed knows nothing about them, and
    `(refused or 0) > 0` used to read that as "none refused"."""
    without = {k: v for k, v in REPORT_JSON.items() if k != "refusals"}
    without["counts"] = {"verified": 10, "near": 0, "unverified": 0,
                         "unscored": 0, "exempt": 0}
    _write_report(tmp_path, sidecar=without)
    status = _status_for(tmp_path)
    assert status["refused"] is None
    assert status["status"] == "warn"
