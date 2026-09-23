"""A review from the page -> `.authored.yaml` on disk (#455).

The reviewer used to end at the clipboard. That was a ruling taken for a stated
reason — not designing the paste-back format before the page had been used —
and using it discharged the reason: what gets copied is exactly this record,
and copying it by hand through a phone's clipboard corrupted every em dash in
it on the first real run.

**One function does the writing, and both the CLI and the save endpoint call
it.** `sd_review apply` is the engine; the endpoint is a face on it (Principles
VI and XI). A route that wrote YAML itself would be the second implementation
this repo keeps paying for.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import ValidationError

from session_doc.authored import AuthoredError, AuthoredRecord, load_record, record_path


class SaveRefused(Exception):
    """Writing this record would destroy work already on disk."""


def review_to_record(payload: dict) -> AuthoredRecord:
    """Validate what the page produced as an authored record."""
    if not isinstance(payload, dict):
        raise AuthoredError("a review must be a JSON object")
    stamped = dict(payload)
    blocks = []
    for entry in stamped.get("blocks", []) or []:
        if not isinstance(entry, dict):
            raise AuthoredError(f"a review block must be an object, got {entry!r}")
        row = dict(entry)
        # The page does not know today's date and should not be trusted with it.
        row.setdefault("recorded", date.today().isoformat())
        blocks.append(row)
    stamped["blocks"] = blocks
    try:
        return AuthoredRecord.model_validate(stamped)
    except ValidationError as exc:
        raise AuthoredError(f"the review is not a valid record:\n{exc}") from exc


def _lost_work(existing: AuthoredRecord, incoming: AuthoredRecord) -> list[str]:
    """Blocks whose authored prose the incoming record would drop.

    Not "any difference" — a human deliberately shortening a passage is an edit,
    and refusing that would make the tool unusable. This is only about prose
    that exists on disk and is **absent** from what is being saved, which is
    what a stale tab or a second device produces.
    """
    incoming_by_id = incoming.by_id()
    lost = []
    for block in existing.blocks:
        if not block.text:
            continue
        arriving = incoming_by_id.get(block.id)
        if arriving is None or not arriving.text:
            lost.append(block.id)
    return lost


def save_record(narration: Path, record: AuthoredRecord, *,
                force: bool = False) -> tuple[Path, list[str]]:
    """Write `<narration>.authored.yaml`, refusing to drop authored prose.

    Returns the path written and the ids of blocks whose prose would have been
    lost had ``force`` not been given.

    The guard exists because the reviewer autosaves: a tab left open on a phone
    from this morning, saving after an evening at the desk, would otherwise
    quietly replace an hour of writing with a record that never had it. Same
    reasoning as `sd_narrate`'s refusal — prose is the only thing in this
    pipeline a human wrote from scratch.
    """
    path = record_path(narration)
    lost: list[str] = []
    if path.is_file():
        try:
            existing = load_record(path)
        except AuthoredError:
            existing = None          # unreadable: nothing to lose, report nothing
        if existing is not None:
            lost = _lost_work(existing, record)
            if lost and not force:
                raise SaveRefused(
                    f"Refusing to save: this would drop prose already in "
                    f"{path.name}.\n"
                    f"  blocks with writing on disk and none arriving: "
                    f"{', '.join(lost)}\n\n"
                    f"That is what a stale tab looks like — a review opened "
                    f"earlier, saving over work done since. Reload the scene to "
                    f"pick up what is on disk, or pass --force if you mean it."
                )
    payload = record.model_dump(mode="json", exclude_none=True)
    path.write_text(
        "# Generated from a gap review. This file is HAND-AUTHORED state: the\n"
        "# narration and the .composed.md beside it are not, and are rewritten.\n"
        + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path, lost


def summarise(record: AuthoredRecord) -> str:
    """The two figures, for a CLI line and a save response."""
    ruled = sum(1 for b in record.blocks if b.disposition)
    written = sum(1 for b in record.blocks
                  if b.disposition in ("authored", "edited", "cut"))
    return f"{ruled} ruled, {written} written"
