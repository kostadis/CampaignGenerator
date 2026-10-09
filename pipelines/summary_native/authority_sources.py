"""The narrow V1 authority source adapter: exact maintained-summary replacement."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pipelines.summary_native.authority import AuthorityError, SourceRef


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def allowed_summary_path(campaign_dir: Path, summaries_dir: Path, source: SourceRef) -> Path:
    root = Path(campaign_dir).resolve()
    summaries = Path(summaries_dir).resolve()
    path = (root / source.path).resolve() if not Path(source.path).is_absolute() else Path(source.path).resolve()
    if path.suffix.lower() != ".md":
        raise AuthorityError("AUTH_TARGET_NOT_ALLOWED: target must be a maintained summary Markdown file", "AUTH_TARGET_NOT_ALLOWED")
    try:
        relative = path.relative_to(summaries)
    except ValueError as exc:
        raise AuthorityError("AUTH_TARGET_NOT_ALLOWED: source target is outside configured summaries root", "AUTH_TARGET_NOT_ALLOWED") from exc
    # A generated range state lives at `<range>/state/...`; do not mistake an
    # unrelated source directory named `state` for it.
    for previous, component in zip(relative.parts, relative.parts[1:]):
        if component == "state" and re.fullmatch(r"(?:ch\d{3}-\d{3}|chapter-\d+)", previous):
            raise AuthorityError("AUTH_TARGET_NOT_ALLOWED: generated state artifact cannot be rewritten", "AUTH_TARGET_NOT_ALLOWED")
    if not path.is_file():
        raise AuthorityError(f"AUTH_TARGET_NOT_ALLOWED: source target does not exist: {path}", "AUTH_TARGET_NOT_ALLOWED")
    if path.read_bytes().lstrip().lower().startswith(b"<!-- generated: summary-native"):
        raise AuthorityError("AUTH_TARGET_NOT_ALLOWED: generated summary-native artifact cannot be rewritten", "AUTH_TARGET_NOT_ALLOWED")
    return path


def exact_replace(path: Path, before: bytes, after: bytes, *, expected_file_sha256: str | None = None) -> bytes:
    data = Path(path).read_bytes()
    if expected_file_sha256 and sha256(data) != expected_file_sha256:
        raise AuthorityError("AUTH_STALE_PROPOSAL: source digest changed; create a new proposal", "AUTH_STALE_PROPOSAL")
    matches = data.count(before)
    if matches != 1:
        raise AuthorityError(f"AUTH_SPAN_NOT_UNIQUE: reviewed span occurs {matches} times", "AUTH_SPAN_NOT_UNIQUE")
    offset = data.index(before)
    if _overlaps_verbatim_moments(data, offset, offset + len(before)):
        raise AuthorityError("AUTH_VERBATIM_TARGET: declared verbatim source cannot be rewritten", "AUTH_VERBATIM_TARGET")
    return data.replace(before, after, 1)


_VERBATIM_HEADING = re.compile(br"^##[ \t]+Verbatim moments[ \t]*\r?$", re.IGNORECASE | re.MULTILINE)
_SECTION_HEADING = re.compile(br"^##[ \t]+", re.MULTILINE)


def _overlaps_verbatim_moments(data: bytes, start: int, end: int) -> bool:
    """Use the session-doc declaration (`## Verbatim moments`) and its h2 span."""
    for heading in _VERBATIM_HEADING.finditer(data):
        next_heading = _SECTION_HEADING.search(data, heading.end())
        section_end = next_heading.start() if next_heading else len(data)
        if start < section_end and end > heading.start():
            return True
    return False
