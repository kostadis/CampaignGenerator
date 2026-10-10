from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from pipelines.summary_native import cli as summary_native_cli
from pipelines.summary_native.promotion.diff import proposed_bytes
from pipelines.summary_native.promotion.gates import check_copied_bundle
from pipelines.summary_native.promotion.manifest import build_bundle_selection


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
FACTORY_SPEC = importlib.util.spec_from_file_location("promotion_preview_factory", FACTORY_PATH)
assert FACTORY_SPEC and FACTORY_SPEC.loader
FACTORY = importlib.util.module_from_spec(FACTORY_SPEC)
FACTORY_SPEC.loader.exec_module(FACTORY)

DOCUMENTS = ("world_state", "campaign_state", "party", "planning")
TIMELINE = "canon_events_timeline.md"


def _tree(root: Path) -> tuple[tuple[str, str, str], ...]:
    """Identity of every entry, including directories and raw symlink targets."""
    entries: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path)))
        elif path.is_dir():
            entries.append((relative, "directory", ""))
        else:
            entries.append((relative, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(entries)


def _initialize_managed(root: Path) -> Path:
    """Adopt the fixture bytes into the planned managed shape for preview tests.

    Migration behavior has its own contract suite. These tests need a valid old
    generation so their assertions concern preview enumeration and differences.
    """
    return FACTORY.initialize_managed(root)


@pytest.fixture
def campaign(tmp_path: Path) -> Path:
    return _initialize_managed(FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy"))


def _argv(root: Path, *extra: str) -> list[str]:
    return [
        "promote",
        "--config", str(root / "config/config.yaml"),
        "--since", "1",
        "--until", "3",
        "--out-root", "docs/summary_native",
        "--review", "promotion-check",
        "--check-report", "claims-unavailable",
        "--dry-run",
        "--json",
        *extra,
    ]


def _preview(root: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, dict]:
    rc = summary_native_cli.main(_argv(root, *extra))
    captured = capsys.readouterr()
    assert captured.out.strip(), captured.err
    payload = json.loads(captured.out)
    assert payload["code"] in {"PROMOTION_BLOCKED", "OK"}
    return rc, payload["data"]


def _changes(data: dict) -> dict[str, dict]:
    return {entry["path"]: entry for entry in data["preview"]["changes"]}


def test_preview_manifest_contains_four_docs_real_timeline_and_every_nested_reference(
    campaign: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _rc, data = _preview(campaign, capsys)
    selection = data["selection"]
    assert {item["document_id"] for item in selection["documents"]} == set(DOCUMENTS)
    assert selection["timeline"]["path"].endswith(f"/state/drafts/{TIMELINE}")

    draft_reference = campaign / "docs/summary_native/ch001-003/state/drafts/reference"
    expected = {
        f"reference/{path.relative_to(draft_reference).as_posix()}"
        for path in draft_reference.rglob("*") if path.is_file()
    }
    proposed = {
        Path(item["path"]).as_posix().split("/state/drafts/", 1)[-1]
        for item in selection["references"]
    }
    assert proposed == expected
    assert "reference/nested/deeper/provenance.md" in proposed
    assert selection["retained_records"]
    assert all(item["sha256"] and item["size"] >= 0 for item in (
        *selection["documents"], selection["timeline"], *selection["references"],
        *selection["retained_records"], *selection["dependencies"],
    ))


def test_preview_reports_add_replace_remove_and_manual_live_drift(
    campaign: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live = campaign / "docs/grounding/generations/legacy-fixture/live"
    (live / "world_state.md").write_text(
        (live / "world_state.md").read_text() + "\nGM live-only correction.\n",
        encoding="utf-8",
    )
    _rc, data = _preview(campaign, capsys)
    changes = _changes(data)
    assert changes["reference/new/eastern-survey.md"]["kind"] == "add"
    assert changes["reference/obsolete/old-watch.md"]["kind"] == "remove"
    assert changes["reference/locations.md"]["kind"] == "replace"
    assert changes["world_state.md"]["kind"] == "replace"
    assert "GM live-only correction" in changes["world_state.md"]["unified_diff"]
    assert data["preview"]["live_digest"]
    assert data["destination"]["edited_since_publication"] is True


def test_binary_difference_is_hashed_and_not_rendered_as_text(
    campaign: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    draft = campaign / "docs/summary_native/ch001-003/state/drafts/reference/nested/payload.bin"
    live = campaign / "docs/grounding/generations/legacy-fixture/live/reference/nested/payload.bin"
    draft.write_bytes(b"candidate\x00\xffbytes")
    live.write_bytes(b"live\x00\xfebytes")
    _rc, data = _preview(campaign, capsys)
    change = _changes(data)["reference/nested/payload.bin"]
    assert change["kind"] == "replace"
    assert change["before_sha256"] != change["after_sha256"]
    assert change["unified_diff"] is None
    assert change.get("binary") is True


@pytest.mark.parametrize("argv", [
    ["promote", "--dry-run", "--json"],
    ["promote", "--since", "1", "--dry-run", "--json"],
])
def test_empty_or_partial_range_selection_refuses_without_guessing(
    campaign: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    before = _tree(campaign)
    with pytest.raises(SystemExit) as exc:
        summary_native_cli.main([*argv, "--config", str(campaign / "config/config.yaml")])
    assert exc.value.code == 2
    assert _tree(campaign) == before
    capsys.readouterr()


def test_mixed_range_draft_refuses_with_available_read_only_diagnostics(
    campaign: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    party = campaign / "docs/summary_native/ch001-003/state/drafts/party.draft.md"
    party.write_text(party.read_text().replace("range: ch001-003", "range: ch004-004", 1))
    before = _tree(campaign)
    rc, data = _preview(campaign, capsys)
    assert rc != 0
    assert "PROMOTION_MIXED_RANGE" in data["preview"]["refusal_codes"]
    assert data["preview"]["eligible"] is False
    assert _tree(campaign) == before


def test_unsupported_source_or_live_layout_refuses_without_writing(
    campaign: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reference = campaign / "docs/summary_native/ch001-003/state/drafts/reference"
    os.symlink("../../../../../../unrelated-gm-notes.md", reference / "unsafe-link.md")
    before = _tree(campaign)
    rc, data = _preview(campaign, capsys)
    assert rc == 2
    assert "PROMOTION_PATH_CONFLICT" in data["preview"]["refusal_codes"]
    assert _tree(campaign) == before


def test_dry_run_is_byte_for_byte_zero_write_and_never_constructs_a_model_client(
    campaign: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("promotion preview must not construct or call a model client")

    import campaignlib
    import campaignlib.api

    for module, name in (
        (campaignlib, "make_client"),
        (campaignlib, "call_api"),
        (campaignlib, "stream_api"),
        (campaignlib.api, "client_from_args"),
    ):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, forbidden)

    before = _tree(campaign)
    _rc, data = _preview(campaign, capsys)
    after = _tree(campaign)
    assert after == before
    assert data["preview"]["preview_sha256"]
    assert any(gate["gate"] == "claims" and gate["state"] == "not_available"
               for gate in data["preview"]["gates"])
    assert not (campaign / "docs/summary_native/ch001-003/state/promotion").exists()


def test_missing_named_check_report_returns_available_structured_preview(
    campaign: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _tree(campaign)
    rc, data = _preview(campaign, capsys, "--check-report", "missing-report.json")
    assert rc == 5
    assert data["preview"]["eligible"] is False
    assert "CLAIMS_INCOMPLETE" in data["preview"]["refusal_codes"]
    assert data["preview"]["changes"]
    assert _tree(campaign) == before


def test_copied_bundle_is_rechecked_in_its_final_layout(
    campaign: Path, tmp_path: Path
) -> None:
    bundle = build_bundle_selection(
        campaign,
        out_root="docs/summary_native",
        since=1,
        until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID),
        review_id="promotion-check",
        rule_versions=("grounding-claims/1", "grounding-bundle-signoff/2"),
    )
    destination = tmp_path / "copied"
    for relative, data in proposed_bytes(campaign, bundle).items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    assert check_copied_bundle(campaign, bundle, destination)[0].state == "passed"
    (destination / "reference/npcs.md").unlink()
    blocked = check_copied_bundle(campaign, bundle, destination)[0]
    assert blocked.code == "PROMOTION_COPIED_BUNDLE_INVALID"
