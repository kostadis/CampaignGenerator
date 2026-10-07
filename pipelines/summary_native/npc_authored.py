"""The only module that opens files under ``docs/npcs/authored/`` (spec 032 R7).

Two kinds of file live there, both written by the GM and never by a tool:

* ``<slug>.authored.yaml`` — ``subject``, ``manual`` (numbered edits) and ``secrets``.
* ``<slug>.md`` — a hand-built dossier, read whole for publishing and never parsed.

Secrets are kept out of every prompt STRUCTURALLY: drafting calls ``load_manual``,
which returns the ``manual`` list and has no way to return ``secrets``. Error
messages never quote file content, because a YAML parse error would otherwise
echo a line of the secrets into a log. Only ``init_authored`` writes, and only to
a path that does not exist yet.

No model call (guarded by ``tests/test_summary_native_no_llm.py``).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from campaignlib.util import atomic_write_text

ALLOWED_KEYS = frozenset({"subject", "manual", "secrets"})


class AuthoredError(Exception):
    """An authored file is malformed, mismatched or already exists (CLI exit 2)."""


def _load(path: Path, subject: str) -> dict | None:
    """The validated mapping, or ``None`` when the file does not exist."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise AuthoredError(f"{path}: cannot read ({type(e).__name__})") from e
    except yaml.YAMLError as e:
        # Not str(e): its context snippet quotes the offending line of the file.
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        raise AuthoredError(f"{path}: not valid YAML{where}") from None
    if not isinstance(data, dict):
        raise AuthoredError(f"{path}: must be a mapping with a subject (and optional manual and secrets)")
    extra = sorted(str(k) for k in set(data) - ALLOWED_KEYS)
    if extra:
        raise AuthoredError(f"{path}: unknown key(s) {', '.join(extra)}; allowed: {', '.join(sorted(ALLOWED_KEYS))}")
    if "subject" not in data:
        raise AuthoredError(f"{path}: subject is required")
    if data["subject"] != subject:
        raise AuthoredError(
            f"{path}: subject {data['subject']!r} does not match the NPC {subject!r}; "
            "was the file renamed or copied?"
        )
    manual = data.get("manual")
    if manual is not None:
        if not isinstance(manual, list):
            raise AuthoredError(f"{path}: manual must be a list of non-empty strings")
        for i, item in enumerate(manual, 1):
            if not (isinstance(item, str) and item.strip()):
                raise AuthoredError(f"{path}: manual item {i} must be a non-empty string")
    secrets = data.get("secrets")
    if secrets is not None and not isinstance(secrets, str):
        raise AuthoredError(f"{path}: secrets must be a string")
    return data


def load_manual(path: Path, subject: str) -> list[str]:
    """The numbered Manual edits, in file order (item N is cited ``[manual N]``).

    A missing file means no edits. ``secrets`` is validated but never returned.
    """
    data = _load(path, subject)
    return list(data.get("manual") or []) if data else []


def load_secrets(path: Path, subject: str) -> str:
    """The Secrets text exactly as parsed, or ``""``. For compose only; never for a prompt."""
    data = _load(path, subject)
    return (data.get("secrets") or "") if data else ""


def read_handbuilt(path: Path) -> str:
    """A hand-built dossier, whole and verbatim."""
    path = Path(path)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AuthoredError(f"{path}: no hand-built dossier there") from None
    except (OSError, UnicodeDecodeError) as e:
        raise AuthoredError(f"{path}: cannot read ({type(e).__name__})") from e


def init_authored(path: Path, subject: str) -> None:
    """Create an empty authored file. Refuses if one exists: no tool overwrites the GM's file."""
    path = Path(path)
    if path.exists():
        raise AuthoredError(f"{path} already exists; it is yours and is never overwritten")
    head = yaml.safe_dump({"subject": subject}, allow_unicode=True, default_flow_style=False, width=10**6)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, head + "manual: []\nsecrets: ''\n")
