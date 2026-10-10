"""The chunked state steps write only under ``<range>/state/`` (spec 033 T058, FR-028).

Same idea as 032's ``test_no_writes_to_authored.py``, but behavioural: on a copy of the fixture
campaign, run ``extract``, ``synth world_state``, ``synth campaign_state``, ``annotate`` (both
documents) and ``audit`` with a fake model client, then compare the whole campaign tree with its
state before them. Promotion into the live ``docs/`` is the GM's act, so after the run:

* the live ``docs/`` tree (published dossiers in ``docs/npcs/`` included) is byte-identical;
* the 031 corpus files (``manifest.json``, ``chronology.md``, ``memorable_moments.md``,
  ``dossiers/``) are byte-identical;
* every file that is new or changed anywhere is under ``<range>/state/``.

The fixture is built (``build``, an 031 step) before the snapshot is taken, so the corpus is part
of what must not move.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pipelines.summary_native import schema
from tests import conftest_state as cs


def snapshot(root: Path) -> dict[str, str]:
    """``relative path -> sha256`` of every file under ``root``."""
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.fixture
def ran(tmp_path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    fm = cs.fake_models(monkeypatch)
    before = snapshot(root)
    steps = [
        cs.extract_args(root),
        ["synth", "world_state", *cs.common(root), "--fallback-npc-lines"],
        ["synth", "campaign_state", *cs.common(root)],
        cs.audit_args(root),
        ["annotate", "world_state", *cs.common(root)],
        ["annotate", "campaign_state", *cs.common(root)],
        ["annotate", "world_state", *cs.common(root), "--dry-run"],
    ]
    for args in steps:
        rc, out, err = cs.run_cli(args)
        assert rc == 0, f"{args[0]} {args[1] if args[0] in ('synth', 'annotate') else ''} failed ({rc}):\n{out}\n{err}"
    return root, fm, before, snapshot(root)


def test_the_steps_ran_and_the_fake_client_was_the_only_model(ran):
    root, fm, before, after = ran
    # not vacuous: every step produced something, and no real backend was involved
    assert fm.extract_calls and fm.prose_calls and fm.audit_calls
    state = f"{cs.range_dir(root).relative_to(root).as_posix()}/{schema.STATE_DIR}/"
    for name in ("notes/manifest.json", "audit/audit.json", "drafts/world_state.draft.md",
                 "drafts/campaign_state.draft.md", "drafts/annotations.md"):
        assert state + name in after, name


def test_the_live_docs_tree_is_byte_identical(ran):
    _, _, before, after = ran
    live = {k: v for k, v in before.items() if k.startswith("docs/") and "/summary_native/" not in k
            and not k.startswith("docs/summary_native/")}
    assert any(k.startswith("docs/npcs/") for k in live), "the fixture must hold a published dossier"
    assert any(k.startswith("docs/summaries/") for k in live)
    for path, digest in live.items():
        assert after.get(path) == digest, f"{path} was changed or removed"
    # and nothing new appeared in the live tree either
    new_live = [k for k in after if k.startswith("docs/") and not k.startswith("docs/summary_native/") and k not in before]
    assert new_live == []


def test_the_031_corpus_files_are_byte_identical(ran):
    root, _, before, after = ran
    rng = cs.range_dir(root).relative_to(root).as_posix()
    corpus = {k: v for k, v in before.items() if k.startswith(rng + "/") and not k.startswith(f"{rng}/{schema.STATE_DIR}/")}
    names = {Path(k).name for k in corpus}
    assert {"manifest.json", "chronology.md", "memorable_moments.md"} <= names
    assert any(k.startswith(f"{rng}/dossiers/") for k in corpus)
    for path, digest in corpus.items():
        assert after.get(path) == digest, f"{path} was changed or removed"


def test_every_new_or_changed_file_is_under_the_ranges_state_directory(ran):
    root, _, before, after = ran
    state = cs.range_dir(root).relative_to(root).as_posix() + f"/{schema.STATE_DIR}/"
    touched = [k for k, v in after.items() if before.get(k) != v]
    assert touched, "the steps wrote nothing"
    outside = [k for k in touched if not k.startswith(state)]
    assert outside == []
    assert [k for k in before if k not in after] == [], "a file was deleted"


def test_claims_and_promotion_code_do_not_reintroduce_draft_live_writes():
    """The new release path may activate generations; draft/model modules still may not."""
    root = Path(__file__).resolve().parents[1] / "pipelines" / "summary_native"
    model_modules = ("extract.py", "synth.py", "audit.py")
    forbidden = ("docs/grounding", "docs/world_state", "docs/campaign_state", "docs/party", "docs/planning")
    for name in model_modules:
        text = (root / name).read_text(encoding="utf-8")
        assert all(fragment not in text for fragment in forbidden), name
