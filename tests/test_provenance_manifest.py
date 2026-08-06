"""T019 — the manifest schema, its validation rules, and loud failure (FR-030).

The manifest is the only enumeration of which campaigns exist (FR-023) and the
only declaration of which files are canon. Everything downstream — the tier on a
hit, the generated-by warning, the refusal that names the known campaigns — is
built on it having loaded correctly and completely.

So the assertions here are mostly about *refusing*, not accepting. A manifest
that half-loads answers "which campaigns exist" wrongly, and a manifest with a
typo'd key that loads anyway serves a defaulted tier to someone with no way to
know they got one.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from provenance.manifest import (
    Campaign,
    ManifestError,
    ProvenanceManifest,
    load_manifest,
    resolve_workspace_root,
    tier_keys,
)

# ── a minimal valid manifest, mutated per test ───────────────────────────────

TIERS = {
    "authoritative": ["summaries/**/*.md"],
    "search_accelerator": [],
    "working_reference": ["docs/*.md"],
    "staging": [],
}


def base() -> dict:
    return {
        "version": 1,
        "campaigns": {
            "alpha": {
                "root": "alpha",
                "tiers": dict(TIERS),
                "identity": {"registry": None, "aliases": None},
            }
        },
    }


def write(tmp_path: Path, data) -> Path:
    path = tmp_path / "provenance.yaml"
    path.write_text(
        data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    return path


def refuses(tmp_path: Path, data, fragment: str) -> str:
    with pytest.raises(ManifestError) as excinfo:
        load_manifest(write(tmp_path, data))
    message = str(excinfo.value)
    assert fragment in message, f"expected {fragment!r} in:\n{message}"
    return message


# ── acceptance ───────────────────────────────────────────────────────────────


def test_minimal_manifest_loads(tmp_path):
    manifest = load_manifest(write(tmp_path, base()))
    assert manifest.campaign_names == ["alpha"]
    assert manifest.get("alpha").root == "alpha"


def test_the_pinned_fixture_loads(fixture_manifest):
    assert fixture_manifest.campaign_names == ["alpha", "beta"]


def test_campaign_name_comes_from_the_key(fixture_manifest):
    """One name, in one place. ``.name`` is stamped from the mapping key."""
    for key, campaign in fixture_manifest.campaigns.items():
        assert campaign.name == key


def test_a_name_field_in_the_block_is_refused(tmp_path):
    data = base()
    data["campaigns"]["alpha"]["name"] = "not-alpha"
    refuses(tmp_path, data, "a campaign's name is its manifest key")


def test_omitted_optional_blocks_default_to_absent(tmp_path):
    campaign = load_manifest(write(tmp_path, base())).get("alpha")
    assert campaign.horizon is None
    assert campaign.corrections is None
    assert campaign.generated == []
    assert campaign.provenance_ranges == []
    assert campaign.identity.has_store is False


# ── FR-030: unknown keys are load errors, not ignored lines ──────────────────


@pytest.mark.parametrize(
    "where, key",
    [
        ("root", "campaigns_"),
        ("campaign", "tier"),
        ("campaign", "corrections_file"),
        ("tiers", "authorative"),
        ("identity", "register"),
    ],
)
def test_an_unrecognised_key_is_a_load_error(tmp_path, where, key):
    """A typo must not be a line nobody notices.

    ``authorative`` for ``authoritative`` is the case that motivates this: with
    ``extra="allow"`` the misspelling would be ignored, the real key would be
    missing, and every summary in the campaign would silently drop a tier.
    """
    data = base()
    target = {
        "root": data,
        "campaign": data["campaigns"]["alpha"],
        "tiers": data["campaigns"]["alpha"]["tiers"],
        "identity": data["campaigns"]["alpha"]["identity"],
    }[where]
    target[key] = "whatever"
    refuses(tmp_path, data, key)


def test_duplicate_yaml_keys_are_refused(tmp_path):
    """``yaml.safe_load`` keeps the last duplicate in silence.

    A duplicated campaign key is a whole game shadowed by a copy-paste; a
    duplicated tier key is a whole tier's globs replaced. Neither is visible in
    a diff review of a long file.
    """
    text = """
version: 1
campaigns:
  alpha:
    root: alpha
    tiers:
      authoritative: ["summaries/**/*.md"]
      search_accelerator: []
      working_reference: ["docs/*.md"]
      authoritative: ["notes/**"]
      staging: []
    identity: {registry: null, aliases: null}
"""
    refuses(tmp_path, text, "duplicate key")


# ── version ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("version", [0, 2, 99])
def test_unknown_version_is_refused(tmp_path, version):
    data = base()
    data["version"] = version
    refuses(tmp_path, data, "understands version 1")


# ── campaigns ────────────────────────────────────────────────────────────────


def test_empty_campaigns_is_refused(tmp_path):
    data = base()
    data["campaigns"] = {}
    refuses(tmp_path, data, "must not be empty")


def test_one_bad_block_fails_the_whole_load(tmp_path):
    """All-or-nothing (FR-030).

    Skipping the broken entry and carrying on is exactly how a partial
    enumeration gets served: the caller asks for the campaign that failed to
    parse and is told it does not exist.
    """
    data = base()
    data["campaigns"]["beta"] = {"root": "beta", "tiers": dict(TIERS), "identity": {},
                                 "horizon": {"latest": 1, "path_pattern": "no-groups-here"}}
    message = refuses(tmp_path, data, "exactly one capture group")
    assert "beta" in message
    # and the *good* block did not load either
    with pytest.raises(ManifestError):
        load_manifest(write(tmp_path, data))


# ── root ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("root", ["../elsewhere", "alpha/../../etc", ".."])
def test_dotdot_in_root_is_an_error_never_a_clamp(tmp_path, root):
    """Rejected, not silently rewritten to something safe.

    Quietly clamping would hide an authoring mistake and leave the GM believing
    they had scoped a campaign somewhere they had not.
    """
    data = base()
    data["campaigns"]["alpha"]["root"] = root
    refuses(tmp_path, data, "escapes the workspace root")


def test_absolute_root_is_refused(tmp_path):
    data = base()
    data["campaigns"]["alpha"]["root"] = "/var/campaigns/alpha"
    refuses(tmp_path, data, "must be relative")


def test_empty_root_is_refused(tmp_path):
    data = base()
    data["campaigns"]["alpha"]["root"] = "   "
    refuses(tmp_path, data, "non-empty relative path")


# ── tiers ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("missing", tier_keys())
def test_every_tier_key_is_required(tmp_path, missing):
    """An omitted tier and an empty tier are different statements.

    Only one of them is something a GM meant to say, so the schema makes them
    look different rather than defaulting the omission into the other.
    """
    data = base()
    del data["campaigns"]["alpha"]["tiers"][missing]
    refuses(tmp_path, data, missing)


def test_an_empty_tier_list_is_legal(tmp_path):
    manifest = load_manifest(write(tmp_path, base()))
    assert manifest.get("alpha").tiers.staging == []


# ── horizon ──────────────────────────────────────────────────────────────────


def test_horizon_is_chapter_only(tmp_path):
    """No ``kind`` discriminator, no date branch — the schema promises only what it keeps."""
    assert "kind" not in Campaign.model_fields["horizon"].annotation.__args__[0].model_fields
    data = base()
    data["campaigns"]["alpha"]["horizon"] = {
        "kind": "chapter",
        "latest": 2,
        "path_pattern": r"docs/chapters/chapter_(\d+)_",
    }
    refuses(tmp_path, data, "kind")


@pytest.mark.parametrize(
    "pattern, groups",
    [(r"docs/chapters/chapter_\d+_", 0), (r"docs/(\w+)/chapter_(\d+)_", 2)],
)
def test_path_pattern_needs_exactly_one_capture_group(tmp_path, pattern, groups):
    data = base()
    data["campaigns"]["alpha"]["horizon"] = {"latest": 1, "path_pattern": pattern}
    refuses(tmp_path, data, f"has {groups}")


def test_uncompilable_path_pattern_is_refused(tmp_path):
    data = base()
    data["campaigns"]["alpha"]["horizon"] = {"latest": 1, "path_pattern": "chapter_([0-9+_"}
    refuses(tmp_path, data, "not a valid regex")


@pytest.mark.parametrize("latest", ["46", True])
def test_horizon_latest_must_be_an_integer(tmp_path, latest):
    """A string here means the author was thinking of dates; horizon is chapter-only."""
    data = base()
    data["campaigns"]["alpha"]["horizon"] = {"latest": latest, "path_pattern": r"c_(\d+)_"}
    refuses(tmp_path, data, "latest")


def test_horizon_pattern_reads_the_path_not_the_body(alpha):
    """FR-029: attribution comes from the filename. A body regex would be inference."""
    pattern = alpha.horizon.compiled()
    assert pattern.search("docs/chapters/chapter_01_arrival.md").group(1) == "01"
    assert pattern.search("docs/chapters/appendix_unnumbered.md") is None


# ── provenance ranges ────────────────────────────────────────────────────────


def test_overlapping_ranges_are_refused(tmp_path):
    data = base()
    data["campaigns"]["alpha"]["provenance_ranges"] = [
        {"from": 1, "to": 15, "authorship": "gm-written"},
        {"from": 10, "to": None, "authorship": "ai-assisted"},
    ]
    refuses(tmp_path, data, "overlap")


def test_an_open_ended_range_must_be_last(tmp_path):
    data = base()
    data["campaigns"]["alpha"]["provenance_ranges"] = [
        {"from": 1, "to": None, "authorship": "gm-written"},
        {"from": 16, "to": None, "authorship": "ai-assisted"},
    ]
    refuses(tmp_path, data, "overlap")


def test_a_backwards_range_is_refused(tmp_path):
    data = base()
    data["campaigns"]["alpha"]["provenance_ranges"] = [
        {"from": 15, "to": 1, "authorship": "gm-written"}
    ]
    refuses(tmp_path, data, "ends before it starts")


def test_range_lookup_never_guesses(alpha):
    """FR-026: outside every declared range the answer is ``None``, not a nearest match."""
    assert alpha.range_for(1) == "gm-written"
    assert alpha.range_for(2) == "ai-assisted"
    assert alpha.range_for(999) == "ai-assisted"   # the open-ended range genuinely covers it
    assert alpha.range_for(None) is None
    assert alpha.range_for(0) is None


# ── generated ────────────────────────────────────────────────────────────────


def test_generated_by_matches_globs_not_prefixes(alpha):
    assert alpha.generated_by("docs/world_state.md") == "distill"
    assert alpha.generated_by("docs/npcs/keeper.md") == "planning"
    assert alpha.generated_by("docs/chapters/chapter_01_arrival.md") is None
    assert alpha.generated_by("summaries/session_01_opening.md") is None


def test_generated_declaration_must_name_a_stage(tmp_path):
    data = base()
    data["campaigns"]["alpha"]["generated"] = [{"paths": ["docs/x.md"], "by": "  "}]
    refuses(tmp_path, data, "must name the generating stage")


def test_generated_declaration_needs_paths(tmp_path):
    data = base()
    data["campaigns"]["alpha"]["generated"] = [{"paths": [], "by": "distill"}]
    refuses(tmp_path, data, "must be non-empty")


# ── file-level failures ──────────────────────────────────────────────────────


def test_a_missing_manifest_is_a_load_error(tmp_path):
    with pytest.raises(ManifestError, match="no manifest at"):
        load_manifest(tmp_path / "provenance.yaml")


def test_an_empty_manifest_is_a_load_error(tmp_path):
    refuses(tmp_path, "", "is empty")


def test_a_non_mapping_manifest_is_a_load_error(tmp_path):
    refuses(tmp_path, "- just\n- a\n- list\n", "mapping at the top level")


def test_invalid_yaml_is_a_load_error(tmp_path):
    refuses(tmp_path, "version: 1\ncampaigns: [unclosed\n", "not valid YAML")


# ── T013: workspace-root resolution (Principle VIII) ─────────────────────────


def test_flag_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMPAIGNS_ROOT", "/env/path")
    resolved = resolve_workspace_root(tmp_path)
    assert resolved.path == tmp_path
    assert resolved.rule == "flag"


def test_env_beats_default(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMPAIGNS_ROOT", str(tmp_path))
    resolved = resolve_workspace_root(None)
    assert resolved.path == tmp_path
    assert resolved.rule == "env"


def test_default_is_the_shared_constant(monkeypatch):
    from campaignlib.constants import CAMPAIGNS_ROOT

    monkeypatch.delenv("CAMPAIGNS_ROOT", raising=False)
    resolved = resolve_workspace_root(None)
    assert resolved.path == Path(CAMPAIGNS_ROOT)
    assert resolved.rule == "default"


def test_resolution_always_reports_which_rule_fired(monkeypatch, tmp_path):
    """Story 3: the same command reads a different corpus depending on an env var.

    "State is discoverable" means the tool says which one, rather than leaving it
    to be inferred from surprising results.
    """
    monkeypatch.delenv("CAMPAIGNS_ROOT", raising=False)
    for explicit in (tmp_path, None):
        resolved = resolve_workspace_root(explicit)
        assert resolved.rule in {"flag", "env", "default"}
        assert resolved.detail.strip()


def test_tilde_is_expanded(monkeypatch):
    monkeypatch.setenv("CAMPAIGNS_ROOT", "~/somewhere")
    resolved = resolve_workspace_root(None)
    assert "~" not in str(resolved.path)
    assert resolved.path == Path(os.path.expanduser("~/somewhere"))
