"""The rg flag set is pinned, and `.gitignore` never scopes a search (D17).

Three of these flags exist for correctness, not speed, and every one of them is
easy to drop by accident while "cleaning up" an argv builder:

- `--no-ignore --hidden` — without them **230 real files vanish** from the live
  workspace, 217 of them working-reference tier. `.gitignore` is a
  version-control concern; the manifest's `exclude` list is the single authority
  on what is not searched.
- `--no-config` — rg reads `$RIPGREP_CONFIG_PATH`. A user config injecting
  `--smart-case` would change results per machine, silently.
- `--json` — this corpus has colons in paths and prose, so `path:line:text`
  parsing is a latent bug, and `--json` is also what defines the non-UTF-8 case
  instead of raising mid-scan.

And `--smart-case` is forbidden outright: it makes `Ilvara` and `ilvara` search
differently based on the query's own casing, which is a behaviour nobody asked
for and nobody would notice.
"""

from __future__ import annotations

import pytest

from provenance.scan import (
    RG_FORBIDDEN_FLAGS,
    RG_REQUIRED_FLAGS,
    build_rg_argv,
    scan,
    select_scanner,
)
from provenance.search import SearchRequest, run_search

pytestmark = pytest.mark.usefixtures("rg_or_skip")


@pytest.fixture()
def argv(fixture_manifest, fixture_workspace):
    return build_rg_argv(
        fixture_manifest.campaigns["alpha"], "Silver Lantern", regex=False, case_sensitive=False
    )


def test_every_required_flag_is_present(argv) -> None:
    for flag in RG_REQUIRED_FLAGS:
        assert flag in argv, f"{flag} missing — see the table in research D17"


def test_no_forbidden_flag_is_present(argv) -> None:
    for flag in RG_FORBIDDEN_FLAGS:
        assert flag not in argv


def test_smart_case_is_never_used(argv) -> None:
    assert "--smart-case" not in argv
    assert "-S" not in argv


def test_casing_is_stated_explicitly(fixture_manifest) -> None:
    """`-i` or `-s`, never left to rg's default or to the query's own shape."""
    campaign = fixture_manifest.campaigns["alpha"]
    insensitive = build_rg_argv(campaign, "x", regex=False, case_sensitive=False)
    sensitive = build_rg_argv(campaign, "x", regex=False, case_sensitive=True)
    assert "-i" in insensitive and "-s" not in insensitive
    assert "-s" in sensitive and "-i" not in sensitive


def test_git_object_store_is_re_excluded(argv) -> None:
    """`--hidden` would otherwise admit .git/, which is bytes, not content."""
    assert "!.git/**" in argv


def test_one_include_glob_per_search_extension(fixture_manifest) -> None:
    campaign = fixture_manifest.campaigns["alpha"]
    argv = build_rg_argv(campaign, "x", regex=False, case_sensitive=False)
    for ext in campaign.search_extensions:
        assert f"*{ext}" in argv


def test_manifest_exclude_globs_become_negated_globs(fixture_manifest) -> None:
    """One declaration drives both scanners; rg gets it as `-g '!…'`."""
    campaign = fixture_manifest.campaigns["alpha"]
    original = list(campaign.exclude)
    try:
        campaign.exclude = original + ["notes/**"]
        argv = build_rg_argv(campaign, "x", regex=False, case_sensitive=False)
        assert "!notes/**" in argv
    finally:
        campaign.exclude = original


def test_the_query_is_passed_after_dash_e(fixture_manifest) -> None:
    """A query beginning with `-` is a pattern, never a flag."""
    campaign = fixture_manifest.campaigns["alpha"]
    argv = build_rg_argv(campaign, "--not-a-flag", regex=False, case_sensitive=False)
    assert argv[argv.index("-e") + 1] == "--not-a-flag"


def test_literal_mode_passes_dash_f(fixture_manifest) -> None:
    campaign = fixture_manifest.campaigns["alpha"]
    assert "-F" in build_rg_argv(campaign, "a.b", regex=False, case_sensitive=False)
    assert "-F" not in build_rg_argv(campaign, "a.b", regex=True, case_sensitive=False)


# ── the behavioural half: .gitignore must not scope ──────────────────────────


def test_a_gitignored_file_is_still_returned(fixture_manifest, fixture_workspace) -> None:
    """alpha/.gitignore hides docs/hidden_reference.md. It is working-reference tier."""
    result = scan(
        fixture_manifest.campaigns["alpha"],
        fixture_workspace / "alpha",
        "Silver Lantern",
        impl=select_scanner("rg"),
    )
    assert any(m.path == "docs/hidden_reference.md" for m in result.matches)


def test_the_gitignored_file_survives_to_the_response(
    fixture_manifest, fixture_workspace
) -> None:
    response = run_search(
        SearchRequest(query="Silver Lantern", campaigns=["alpha"], scanner="rg"),
        fixture_manifest,
        fixture_workspace,
    )
    hidden = next(h for h in response.hits if h.path == "docs/hidden_reference.md")
    assert hidden.tier.value == "working_reference"


def test_both_scanners_see_the_gitignored_file(fixture_manifest, fixture_workspace) -> None:
    for impl in ("rg", "python"):
        result = scan(
            fixture_manifest.campaigns["alpha"],
            fixture_workspace / "alpha",
            "Silver Lantern",
            impl=select_scanner(impl),
        )
        assert any(m.path == "docs/hidden_reference.md" for m in result.matches), impl


def test_a_user_rg_config_cannot_change_results(
    fixture_manifest, fixture_workspace, tmp_path, monkeypatch
) -> None:
    """`--no-config` is why this passes. Without it, the config below wins."""
    config = tmp_path / "rgconfig"
    config.write_text("--smart-case\n-g=!docs/**\n", encoding="utf-8")
    monkeypatch.setenv("RIPGREP_CONFIG_PATH", str(config))
    result = scan(
        fixture_manifest.campaigns["alpha"],
        fixture_workspace / "alpha",
        "Silver Lantern",
        impl=select_scanner("rg"),
    )
    assert any(m.path.startswith("docs/") for m in result.matches)
