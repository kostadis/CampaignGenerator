from pathlib import Path

import pytest

from session_doc.narration_wiki.collect import build_manifest
from session_doc.narration_wiki.models import ScopeError
from session_doc.narration_wiki.paths import resolve_scope


def test_collection_refuses_an_escaping_file_symlink(tmp_path):
    campaign = tmp_path / "campaign"
    session = campaign / "sessions" / "one"
    narration = session / "narration"
    narration.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    (narration / "Aria.md").symlink_to(outside)
    scope = resolve_scope(campaign, session, "iter-001")
    with pytest.raises(ScopeError, match="escapes"):
        build_manifest(scope)


def test_two_campaign_scopes_never_share_evidence(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, text in ((first, "first"), (second, "second")):
        (root / "sessions" / "one" / "narration").mkdir(parents=True)
        (root / "sessions" / "one" / "narration" / "Aria.md").write_text(text)
    a = build_manifest(resolve_scope(first, first / "sessions" / "one", "iter-a"))
    b = build_manifest(resolve_scope(second, second / "sessions" / "one", "iter-b"))
    assert a.corpus_id != b.corpus_id
