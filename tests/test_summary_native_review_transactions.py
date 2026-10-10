from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipelines.summary_native.authority import AuthorityError
from pipelines.summary_native.authority_apply import (
    TransactionTarget,
    journal_path,
    prepare_transaction,
    recover_transaction,
)


def test_v2_transaction_recovers_create_replace_and_delete(tmp_path: Path):
    created = tmp_path / "docs" / "created.txt"
    replaced = tmp_path / "docs" / "empty.txt"
    deleted = tmp_path / "docs" / "deleted.txt"
    replaced.parent.mkdir(parents=True)
    replaced.write_bytes(b"")
    deleted.write_bytes(b"remove me")

    journal = prepare_transaction(
        tmp_path,
        proposal_id="review-proposal",
        proposal_sha256="a" * 64,
        targets=[
            TransactionTarget.create(created, b""),
            TransactionTarget.replace(replaced, b"", b"now populated"),
            TransactionTarget.delete(deleted, b"remove me"),
        ],
    )

    assert journal["version"] == 2
    assert [target["operation"] for target in journal["targets"]] == ["create", "replace", "delete"]
    assert [target["before_exists"] for target in journal["targets"]] == [False, True, True]
    assert [target["after_exists"] for target in journal["targets"]] == [True, True, False]

    assert recover_transaction(tmp_path, journal["id"])["state"] == "committed"
    assert created.exists() and created.read_bytes() == b""
    assert replaced.read_bytes() == b"now populated"
    assert not deleted.exists()
    assert recover_transaction(tmp_path, journal["id"])["state"] == "committed"


def test_prepare_preflights_every_target_before_persisting_snapshots(tmp_path: Path):
    first = tmp_path / "docs" / "first.txt"
    stale = tmp_path / "docs" / "stale.txt"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"first")
    stale.write_bytes(b"changed")

    with pytest.raises(AuthorityError, match="target changed"):
        prepare_transaction(
            tmp_path,
            proposal_id="review-proposal",
            proposal_sha256="b" * 64,
            targets=[
                TransactionTarget.replace(first, b"first", b"after"),
                TransactionTarget.replace(stale, b"expected", b"after"),
            ],
        )

    snapshots = tmp_path / "docs" / "authority" / "snapshots"
    assert not snapshots.exists() or not any(snapshots.iterdir())


def test_recovery_preflights_every_target_before_create_or_delete(tmp_path: Path):
    created = tmp_path / "docs" / "created.txt"
    deleted = tmp_path / "docs" / "deleted.txt"
    deleted.parent.mkdir(parents=True)
    deleted.write_bytes(b"delete")
    journal = prepare_transaction(
        tmp_path,
        proposal_id="review-proposal",
        proposal_sha256="c" * 64,
        targets=[
            TransactionTarget.create(created, b"created"),
            TransactionTarget.delete(deleted, b"delete"),
        ],
    )
    deleted.write_bytes(b"operator edit")

    with pytest.raises(AuthorityError, match="AUTH_UNEXPECTED_RECOVERY_BYTES"):
        recover_transaction(tmp_path, journal["id"])

    assert not created.exists()
    assert deleted.read_bytes() == b"operator edit"


def test_versionless_v1_transaction_still_recovers_forward(tmp_path: Path):
    target = tmp_path / "docs" / "legacy.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    journal = prepare_transaction(
        tmp_path,
        proposal_id="legacy-proposal",
        proposal_sha256="d" * 64,
        targets=[(target, b"before", b"after")],
    )
    path = journal_path(tmp_path, journal["id"])
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("version")
    for item in legacy["targets"]:
        item.pop("operation")
    path.write_text(json.dumps(legacy, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    recovered = recover_transaction(tmp_path, journal["id"])
    assert recovered["state"] == "committed"
    assert target.read_bytes() == b"after"


def test_delete_distinguishes_missing_after_state_from_empty_file(tmp_path: Path):
    target = tmp_path / "docs" / "empty.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")
    journal = prepare_transaction(
        tmp_path,
        proposal_id="delete-empty",
        proposal_sha256="e" * 64,
        targets=[TransactionTarget.delete(target, b"")],
    )

    recover_transaction(tmp_path, journal["id"])
    assert not target.exists()


def test_transaction_refuses_symlink_target_before_write_and_during_recovery(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "value.txt").write_bytes(b"outside")
    alias = tmp_path / "docs" / "alias"
    alias.parent.mkdir()
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AuthorityError, match="symlink transaction target"):
        prepare_transaction(
            tmp_path,
            proposal_id="symlink",
            proposal_sha256="f" * 64,
            targets=[TransactionTarget.replace(alias / "value.txt", b"outside", b"changed")],
        )
    assert (outside / "value.txt").read_bytes() == b"outside"

    target = tmp_path / "docs" / "safe" / "value.txt"
    target.parent.mkdir()
    target.write_bytes(b"before")
    journal = prepare_transaction(
        tmp_path, proposal_id="swap", proposal_sha256="a" * 64,
        targets=[TransactionTarget.replace(target, b"before", b"after")],
    )
    target.unlink()
    target.parent.rmdir()
    target.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AuthorityError, match="symlink transaction target"):
        recover_transaction(tmp_path, journal["id"])
    assert (outside / "value.txt").read_bytes() == b"outside"
