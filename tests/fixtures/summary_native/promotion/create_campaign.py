#!/usr/bin/env python3
"""Create the deterministic disposable campaign used by promotion tests.

The default is the pre-migration (``legacy``) shape from the quickstart.  A
``pristine`` fixture has the same reviewed candidate generation and campaign
prerequisites, but no existing managed output.  This script deliberately does
not invoke a pipeline, model client, subprocess, or network service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from pipelines.summary_native import schema, state_sections, synth  # noqa: E402
from pipelines.summary_native.authority import AuthorityLedger, ledger_bytes  # noqa: E402
from pipelines.summary_native.review.models import canonical_bytes  # noqa: E402
from pipelines.summary_native.review.models import canonical_digest  # noqa: E402
from pipelines.summary_native.promotion.models import (  # noqa: E402
    ActivationRecord, BaselineKind, ContentIdentity, GenerationKind, GenerationManifest,
)


CAMPAIGN_ID = UUID("54800000-0000-4000-8000-000000000001")
RANGE_NAME = "ch001-003"
DOCUMENTS = ("world_state", "campaign_state", "party", "planning")
FIXED_TIME = "2026-10-10T00:00:00Z"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _summary(chapter: int) -> str:
    names = {1: "The Sealed Gate", 2: "The Broken Compact", 3: "The Lantern Road"}
    events = {
        1: "Mara accepts the brass key from Warden Hale.",
        2: "The company opens the sealed gate and clears the old watch room.",
        3: "Hale records that the Lantern Road is safe as far as the eastern marker.",
    }
    return (
        f"# Chapter {chapter}: {names[chapter]}\n\n"
        f"## Scenes\n\n### {chapter:03d}.01 {names[chapter]}\n\n{events[chapter]}\n\n"
        f"## NPCs\n\n### Warden Hale\n\nHale keeps the gate ledger.\n\n"
        f"## Locations\n\n### Lantern Road\n\nThe road begins beyond the sealed gate.\n\n"
        f"## Memorable Moments\n\n> \"Write what happened, not what we hoped would happen.\"\n\n"
        f"## Session-End State\n\nThe company rests beside marker {chapter}.\n"
    )


def _reference_members(*, legacy: bool) -> dict[str, str]:
    members = {
        "factions.md": "# Reference: Factions\n\n## Gate Wardens\n\n- The wardens keep the eastern gate. [ch 001 / 001.01]\n",
        "npcs.md": "# Reference: NPCs\n\n## Warden Hale\n\n- Hale records the road as safe. [ch 003 / 003.01]\n",
        "locations.md": "# Reference: Locations\n\n## Lantern Road\n\n- The surveyed road reaches the eastern marker. [ch 003 / locations]\n",
        "items.md": "# Reference: Items\n\n## Brass Key\n\n- Mara carries the key to the sealed gate. [ch 001 / 001.01]\n",
        "threats.md": "# Reference: Threats\n\n_No verified active threat._\n",
        "threads.md": "# Reference: Threads\n\n## Open Gate\n\n- The gate was opened and the watch room cleared. [ch 002 / 002.01]\n",
        "party.md": "# Party Reference\n\nThe company rests on the Lantern Road. [ch 003 / end]\n",
        "threads_unratified.md": "# Unratified Threads\n\n_(none verified)_\n",
        "locations/lantern-road.md": "# Lantern Road\n\nThe surveyed road reaches the eastern marker. [ch 003 / locations]\n",
        "items/keys/brass-key.md": "# Brass Key\n\nMara carries the key to the sealed gate. [ch 001 / 001.01]\n",
        "threads/open-gate.md": "# Open Gate\n\nThe gate was opened and the watch room cleared. [ch 002 / 002.01]\n",
        "nested/deeper/provenance.md": "# Nested Provenance\n\nA deliberately nested generated member.\n",
        "new/eastern-survey.md": "# Eastern Survey\n\nA newly generated member in the candidate bundle.\n",
    }
    if legacy:
        members["locations.md"] = "# Reference: Locations\n\n## Lantern Road\n\n- The road beyond the gate has not been surveyed.\n"
        members["locations/lantern-road.md"] = "# Lantern Road\n\nThe road beyond the gate has not been surveyed.\n"
        members["obsolete/old-watch.md"] = "# Old Watch\n\nObsolete generated member retained only in the prior live bundle.\n"
        members.pop("new/eastern-survey.md")
    return members


def _draft(document: str, record_sha: str, notes_sha: str) -> str:
    contract = state_sections.reading_contract(
        (1, 3),
        {"reference": "reference", "timeline": schema.TIMELINE_FILE, "summaries": "docs/summaries"},
        document,
    )
    sections = []
    for heading in synth.load_outline(document):
        sections.append(f"{heading}\n\nReviewed fixture prose for {document}. [ch 003 / end]")
    body = "\n\n".join(sections)
    if document == "planning":
        # Keep this document slightly above 200 KiB and sectioned so bounded
        # review, diff, and phone rendering paths exercise realistic input.
        paragraph = (
            "Fixture planning detail: verify the eastern marker, preserve the gate ledger, "
            "and ask Warden Hale before changing the watch. [ch 003 / 003.01]\n"
        )
        body += "\n\n" + paragraph * 1450
    return (
        f"<!-- summary_native draft | doc: {document} | range: {RANGE_NAME} | "
        f"record: runs/run-{document}/record.json | record sha256: {record_sha} | "
        f"notes manifest sha256: {notes_sha} -->\n{contract}\n{body}\n"
    )


def _initialize_prerequisites(root: Path) -> None:
    _write(root / "docs/authority/.lock", b"")
    ledger = ledger_bytes(AuthorityLedger(version=2, campaign="promotion-fixture", revision=1))
    _write(root / "docs/authority.yaml", ledger)
    event_id = "event-fixture-init"
    event = {
        "actor": "fixture",
        "after_sha256": _sha(ledger),
        "before_sha256": _sha(b""),
        "id": event_id,
        "reason": "fixture-init",
        "recorded_at": FIXED_TIME,
    }
    _write(root / f"docs/authority/events/{event_id}.json", canonical_bytes(event) + b"\n")
    _write(
        root / "docs/authority/events/tip.json",
        canonical_bytes({"event_id": event_id, "ledger_sha256": _sha(ledger)}) + b"\n",
    )
    _write(
        root / "docs/reviews/campaign.json",
        canonical_bytes({"version": 1, "campaign_id": CAMPAIGN_ID, "canonical_root": str(root.resolve())}),
    )
    _json(
        root / "docs/reviews/promotion-check/fixture-prerequisites.json",
        {
            "version": 1,
            "campaign_id": str(CAMPAIGN_ID),
            "review_id": "promotion-check",
            "rule": "grounding-document-signoff-v2",
            "documents": list(DOCUMENTS),
            "state": "reviewed_fixture_inputs",
            "recorded_at": FIXED_TIME,
        },
    )


def create_campaign(campaign_dir: Path, *, baseline: str = "legacy") -> Path:
    root = Path(campaign_dir).resolve()
    if root.exists():
        if any(root.iterdir()):
            raise ValueError(f"campaign directory is not empty: {root}")
    else:
        root.mkdir(parents=True)

    _write(
        root / "config/config.yaml",
        "campaign: promotion-fixture\nsummary_native:\n  out_root: ../docs/summary_native\n"
        "documents:\n  - label: world_state\n    path: ../docs/world_state.md\n"
        "  - label: campaign_state\n    path: ../docs/campaign_state.md\n"
        "  - label: party\n    path: ../docs/party.md\n"
        "  - label: planning\n    path: ../docs/planning.md\n",
    )
    _write(
        root / "config/grounding.yaml",
        "summary_native:\n  out_root: ../docs/summary_native\n  range_since: 1\n  range_until: 3\n",
    )
    _write(root / "config/players.yaml", "version: 1\nplayers:\n  - name: Fixture Player\n    plays: [Mara Vale]\n")
    _write(root / "docs/entity_registry.yaml", "version: 1\ncampaign: promotion-fixture\nentities: []\n")
    _write(root / "docs/thread_registry.yaml", "version: 1\nthreads: []\n")
    _write(root / "config/party.yaml", "version: 1\ncharacters: []\n")
    _write(root / "config/planning.yaml", "version: 1\ntracked: []\n")
    _write(root / "docs/mechanics/fixture-clock.md", "# Fixture Clock\n\nNo score is asserted.\n")
    _write(root / "docs/tracking/fixture.txt", "Lantern Road survey\n")
    _write(root / "docs/unrelated-gm-notes.md", "# Unrelated GM notes\n\nMigration and promotion must preserve this file.\n")
    for chapter in range(1, 4):
        _write(root / f"docs/summaries/{chapter:03d}-fixture.md", _summary(chapter))
    _initialize_prerequisites(root)

    range_dir = root / "docs/summary_native" / RANGE_NAME
    state = range_dir / "state"
    drafts = state / "drafts"
    summary_files = sorted((root / "docs/summaries").glob("*.md"))
    _json(
        range_dir / "manifest.json",
        {
            "kind": "summary_native",
            "schema": 1,
            "complete": True,
            "range": {"since": 1, "until": 3, "gaps": []},
            "files": [
                {"path": f.relative_to(root).as_posix(), "chapter": i, "sha256": _sha(f.read_bytes())}
                for i, f in enumerate(summary_files, 1)
            ],
        },
    )
    notes_manifest = {
        "kind": "state_notes",
        "audience": "gm",
        "range": {"since": 1, "until": 3},
        "complete": True,
        "source_manifest": "../../manifest.json",
    }
    _json(state / "notes/manifest.json", notes_manifest)
    notes_sha = _sha((state / "notes/manifest.json").read_bytes())
    corpus_sha = _sha((range_dir / "manifest.json").read_bytes())
    registry_sha = _sha((root / "docs/entity_registry.yaml").read_bytes())
    players_sha = _sha((root / "config/players.yaml").read_bytes())
    threads_sha = _sha((root / "docs/thread_registry.yaml").read_bytes())
    party_config_sha = _sha((root / "config/party.yaml").read_bytes())
    planning_config_sha = _sha((root / "config/planning.yaml").read_bytes())
    mechanic_sha = _sha((root / "docs/mechanics/fixture-clock.md").read_bytes())
    track_sha = _sha((root / "docs/tracking/fixture.txt").read_bytes())
    authority_sha = _sha((root / "docs/authority.yaml").read_bytes())
    _write(
        drafts / schema.TIMELINE_FILE,
        "# Canon Events Timeline\n\n- Mara receives the brass key. [ch 001 / 001.01]\n"
        "- The sealed gate is opened. [ch 002 / 002.01]\n"
        "- The Lantern Road is surveyed. [ch 003 / 003.01]\n",
    )
    for relative, text in _reference_members(legacy=False).items():
        _write(drafts / "reference" / relative, text)

    selection = {"version": 1, "review_id": "promotion-check", "documents": []}
    for document in DOCUMENTS:
        record = {
            "version": 1,
            "step": "synth",
            "doc": document,
            "run_id": f"run-{document}",
            "range": {"since": 1, "until": 3},
            "inputs": {
                "corpus_manifest_sha256": corpus_sha,
                "notes_manifest_sha256": notes_sha,
                "registry_sha256": registry_sha,
                "players_sha256": players_sha,
                "track_files": ([{"path": "docs/tracking/fixture.txt", "sha256": track_sha}]
                                if document == "campaign_state" else []),
                **({"party_config": {
                    "path": "config/party.yaml", "sha256": party_config_sha,
                    "files": [{"role": "arc_score:fixture", "path": "docs/mechanics/fixture-clock.md", "sha256": mechanic_sha}],
                }} if document == "party" else {}),
                **({"planning_config": {
                    "path": "config/planning.yaml", "sha256": planning_config_sha,
                    "files": [{"role": "arc_score:fixture", "path": "docs/mechanics/fixture-clock.md", "sha256": mechanic_sha}],
                }, "authority_manifest": {
                    "authority_schema": 2, "authority_policy": 1,
                    "ledger_sha256": authority_sha, "ledger_revision": 1,
                    "records": [], "audience": "gm", "horizon": "planning",
                    "range": {"since": 1, "until": 3}, "selection": None,
                    "pending_transaction": None,
                }} if document == "planning" else {}),
                **({"thread_registry_sha256": threads_sha} if document in {"campaign_state", "planning"} else {}),
            },
            "check": "passed",
            "finished": FIXED_TIME,
        }
        record_path = state / f"runs/run-{document}/record.json"
        _json(record_path, record)
        draft_path = drafts / f"{document}.draft.md"
        _write(draft_path, _draft(document, _sha(record_path.read_bytes()), notes_sha))
        selection["documents"].append(
            {"id": document, "path": draft_path.relative_to(root).as_posix(), "sha256": _sha(draft_path.read_bytes())}
        )
    _json(root / "selections/promotion-documents.json", selection)

    if baseline == "legacy":
        for document in DOCUMENTS:
            candidate = (drafts / f"{document}.draft.md").read_text(encoding="utf-8")
            legacy = candidate.replace(
                f"Reviewed fixture prose for {document}.",
                f"Existing reviewed live edit for {document}.",
                1,
            )
            _write(root / f"docs/{document}.md", legacy)
        _write(root / f"docs/{schema.TIMELINE_FILE}", "# Canon Events Timeline\n\n- Legacy timeline entry.\n")
        for relative, text in _reference_members(legacy=True).items():
            _write(root / "docs/reference" / relative, text)

    _json(
        root / "fixture.json",
        {
            "version": 1,
            "baseline": baseline,
            "campaign_id": str(CAMPAIGN_ID),
            "range": {"since": 1, "until": 3, "name": RANGE_NAME},
            "documents": list(DOCUMENTS),
            "changed_members": ["reference/locations.md", "reference/locations/lantern-road.md"] if baseline == "legacy" else [],
            "removed_members": ["reference/obsolete/old-watch.md"] if baseline == "legacy" else [],
            "added_members": ["reference/new/eastern-survey.md"] if baseline == "legacy" else [],
            "long_document": "planning",
        },
    )
    return root


def initialize_managed(root: Path, generation_id: str = "legacy-fixture") -> Path:
    """Install the fixture's loose baseline as a deterministic managed tree."""
    root = Path(root).resolve()
    authority = root / "docs/authority"
    (authority / ".lock").touch(exist_ok=True)
    grounding = root / "docs/grounding"
    live = grounding / f"generations/{generation_id}/live"
    published = live.parent / "published"
    for destination in (live, published):
        destination.mkdir(parents=True, exist_ok=True)
        for name in (*DOCUMENTS, "canon_events_timeline.md"):
            source = root / "docs" / (f"{name}.md" if name in DOCUMENTS else name)
            shutil.copyfile(source, destination / source.name)
        shutil.copytree(root / "docs/reference", destination / "reference")
    members = []
    for path in sorted(published.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            members.append(ContentIdentity(
                path=path.relative_to(published).as_posix(), sha256=_sha(data), size=len(data)
            ))
    manifest_values = dict(
        generation_id=generation_id, operation_id="fixture-migration",
        campaign_id=str(CAMPAIGN_ID), selected_range=None, kind=GenerationKind.LEGACY_ADOPTION,
        members=tuple(members), retained_records=(), external_dependencies=(),
        published_path=f"docs/grounding/generations/{generation_id}/published",
        live_path=f"docs/grounding/generations/{generation_id}/live",
        bundle_digest=None, analysis_digest=None, parent_activation_id=None,
        created_at=datetime.fromisoformat(FIXED_TIME.replace("Z", "+00:00")), manifest_sha256="0" * 64,
    )
    provisional = GenerationManifest.model_validate(manifest_values)
    manifest_values["manifest_sha256"] = canonical_digest(
        provisional, exclude_fields=frozenset({"manifest_sha256"})
    )
    manifest = GenerationManifest.model_validate(manifest_values)
    manifest_bytes = canonical_bytes(manifest)
    _write(live.parent / "manifest.json", manifest_bytes)
    migration_receipt_base = {
        "version": 1, "state": "committed", "operation_id": "fixture-migration",
        "baseline": "legacy_adoption", "generation_id": generation_id,
        "manifest_path": f"docs/grounding/generations/{generation_id}/manifest.json",
        "activation_path": "docs/grounding/activations/baseline-fixture.json",
    }
    migration_receipt = canonical_digest(migration_receipt_base)
    _json(grounding / "migrations/fixture-migration/receipt.json", {
        **migration_receipt_base, "receipt_sha256": migration_receipt,
    })
    activation = ActivationRecord(
        activation_id="baseline-fixture", operation_id="fixture-migration",
        generation_id=generation_id, manifest_sha256=_sha(manifest_bytes),
        migration_receipt_sha256=migration_receipt, parent_activation_id=None,
        parent_activation_sha256=None, baseline_kind=BaselineKind.LEGACY_BASELINE,
        previous_snapshot_sha256=None, actor="fixture",
        completed_at=datetime.fromisoformat(FIXED_TIME.replace("Z", "+00:00")),
    )
    _write(grounding / "activations/baseline-fixture.json", canonical_bytes(activation))
    _json(grounding / "layout.json", {
        "version": 1, "state": "active", "generation_id": generation_id,
        "migration_operation_id": "fixture-migration",
    })
    os.symlink(f"generations/{generation_id}/live", grounding / "current")
    for name in (*DOCUMENTS, "canon_events_timeline.md"):
        loose = root / "docs" / (f"{name}.md" if name in DOCUMENTS else name)
        loose.unlink()
        os.symlink(f"grounding/current/{loose.name}", loose)
    shutil.rmtree(root / "docs/reference")
    os.symlink("grounding/current/reference", root / "docs/reference")
    return root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--baseline", "--mode", choices=("legacy", "pristine"), default="legacy")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = create_campaign(args.campaign_dir, baseline=args.baseline)
    except (OSError, ValueError) as exc:
        print(f"create_campaign: {exc}", file=sys.stderr)
        return 2
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
