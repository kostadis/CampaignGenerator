from pathlib import Path

import pytest

from session_doc.narration_wiki.models import ScopeError, canonical_json, normalize_slug, proposal_fingerprint, require_stable_id
from session_doc.narration_wiki.paths import contained_path, resolve_scope


def test_stable_ids_slugs_and_json_are_deterministic():
    assert require_stable_id("iter-001") == "iter-001"
    assert normalize_slug("  Héllo, WORLD! ") == "hello-world"
    assert canonical_json({"b": 1, "a": "é"}) == '{\n  "a": "é",\n  "b": 1\n}\n'
    with pytest.raises(Exception):
        require_stable_id("Not Stable")


def test_scope_requires_one_proper_contained_session(tmp_path):
    campaign = tmp_path / "campaign"
    session = campaign / "sessions" / "one"
    session.mkdir(parents=True)
    scope = resolve_scope(campaign, session, "iter-001")
    assert scope.session_relative == "sessions/one"
    with pytest.raises(ScopeError):
        resolve_scope(campaign, campaign, "iter-001")
    with pytest.raises(ScopeError):
        resolve_scope(campaign, tmp_path, "iter-001")


def test_contained_mutation_refuses_every_symlink_component(tmp_path):
    root = tmp_path / "root"
    real = root / "real"
    real.mkdir(parents=True)
    (root / "link").symlink_to(real, target_is_directory=True)
    with pytest.raises(ScopeError, match="symlink"):
        contained_path(root, "link/file.md", mutation=True)


def test_proposal_fingerprint_is_deterministic():
    digest = "a" * 64
    first = proposal_fingerprint("rulebook", "voice/_genre.md", "rule-one", digest, "b" * 64)
    second = proposal_fingerprint("rulebook", "voice/_genre.md", "rule-one", digest, "b" * 64)
    assert first == second
