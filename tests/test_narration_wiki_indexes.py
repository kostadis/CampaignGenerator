from dataclasses import replace
from pathlib import Path

import pytest

from session_doc.narration_wiki.indexes import index_check, parse_pattern_page, visible_confirmed_slugs
from session_doc.narration_wiki.models import ValidationError
from session_doc.narration_wiki.paths import resolve_scope


def _page(slug: str, tier: str = "campaign", status: str = "confirmed") -> str:
    return f"""---
slug: {slug}
title: A useful lesson
tier: {tier}
status: {status}
evidence: [source]
---

# A useful lesson

## Problem
The prose repeats one generic behavior everywhere.

## Root Cause
The prompt rewards a portable verbal shortcut.

## Corrective Strategy
Use a concrete observation grounded in this narrator.

## Evidence
- source
"""


def test_pattern_requires_full_lesson_and_normalized_filename(tmp_path):
    path = tmp_path / "lesson.md"
    path.write_text(_page("lesson"))
    assert parse_pattern_page(path, expected_slug="lesson").slug == "lesson"
    path.write_text("---\nslug: lesson\n---\n\n## Problem\nphrase\n")
    with pytest.raises(ValidationError, match="requires"):
        parse_pattern_page(path)


def test_index_check_reports_broken_links_and_cross_tier_collisions(tmp_path):
    campaign = tmp_path / "campaign"
    session = campaign / "sessions" / "one"
    session.mkdir(parents=True)
    portable = tmp_path / "portable"
    for root, tier in ((campaign / "wiki", "campaign"), (portable, "portable")):
        (root / "patterns").mkdir(parents=True)
        (root / "patterns" / "lesson.md").write_text(_page("lesson", tier))
        (root / "index.md").write_text("# Index\n\n- [Lesson](patterns/lesson.md)\n- [Missing](patterns/missing.md)\n")
    (portable / "capabilities.yaml").write_text(
        "schema_version: 1\nsource_repository: fixture\nsource_revision: rev\nnarration_wiki_contract: 1\nguidance_source: campaign-resolved\ncapabilities: [maintainer, proposer]\n"
    )
    scope = resolve_scope(campaign, session, "iter-001", portable_root=portable)
    result = index_check(scope)
    assert not result["valid"]
    assert any("broken index link" in problem for problem in result["problems"])
    assert any("cross-tier duplicate" in problem for problem in result["problems"])


def test_unconfirmed_pages_are_audited_but_never_become_confirmed_canon(tmp_path):
    """A page that failed its own audit must not authorize a guidance change.

    _audit_tier reported the problem and then filed the page anyway, so
    visible_confirmed_slugs handed Gate 2 a slug whose page was still pending --
    a pattern that never passed Gate 1 could authorise a guidance mutation.
    """
    campaign = tmp_path / "campaign"
    session = campaign / "sessions" / "one"
    session.mkdir(parents=True)
    portable = tmp_path / "portable"
    portable.mkdir()
    patterns = campaign / "wiki" / "patterns"
    patterns.mkdir(parents=True)
    (patterns / "settled.md").write_text(_page("settled"))
    (patterns / "pending.md").write_text(_page("pending", status="pending_portable_sync"))
    (campaign / "wiki" / "index.md").write_text(
        "# Index\n\n- [Settled](patterns/settled.md)\n- [Pending](patterns/pending.md)\n"
    )
    scope = resolve_scope(campaign, session, "iter-001", portable_root=portable)

    result = index_check(scope)
    # The page still exists on disk, so index cross-checks keep seeing it.
    assert result["campaign_slugs"] == ["pending", "settled"]
    assert result["confirmed_slugs"] == ["settled"]
    assert visible_confirmed_slugs(scope) == {"settled"}
    assert any("unresolved promotion state" in problem for problem in result["problems"])
    assert not any("broken index link" in problem for problem in result["problems"])
