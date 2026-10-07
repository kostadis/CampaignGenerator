"""Compose the GM dossier: the draft dossier plus the authored Secrets (spec 032 T025, FR-018b).

Deterministic, no model. The GM dossier is generated output: the draft and the authored
file are the sources of truth and neither is ever modified here. A hand-edit to a composed
file is detected by comparing its body to the ``composed sha256`` recorded in its own
header, and is reported before the file is overwritten.

Secrets are read only here (``npc_authored.load_secrets``); they are copied byte-for-byte
under ``## Secrets`` and go nowhere else.

No model call (guarded by ``tests/test_summary_native_no_llm.py``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from campaignlib.util import atomic_write_text
from pipelines.summary_native import npc_authored, npc_link, npc_slug, schema

NOT_DRAFTED = "_(not yet drafted)_"
NO_SECRETS = "_(none authored)_"
_GM_HEADER_RE = re.compile(
    r"\A<!-- summary_native npc gm \| npc: (?P<npc>.*?) \| draft sha256: (?P<draft>\S+) "
    r"\| authored sha256: (?P<authored>\S+) \| composed sha256: (?P<composed>\S+) -->\n"
)
_COMMENT_LINE_RE = re.compile(r"\A<!--.*?-->[ \t]*\n", re.DOTALL)


@dataclass(frozen=True)
class ComposeResult:
    stem: str
    subject: str
    out_path: Path
    hand_edited: bool  # an existing composed file did not match its recorded sha (discarded)
    drafted: bool
    has_secrets: bool


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def authored_path_for(root: Path, subject: str) -> Path:
    return Path(root) / schema.AUTHORED_DIR / f"{npc_slug.slug_for(subject)}.authored.yaml"


def draft_body(draft_text: str) -> str:
    """The draft dossier minus its provenance comment line."""
    return _COMMENT_LINE_RE.sub("", draft_text, count=1)


def compose_text(subject: str, draft_text: str | None, secrets: str, authored_bytes: bytes | None) -> str:
    body = draft_body(draft_text).rstrip("\n") if draft_text is not None else NOT_DRAFTED
    tail = secrets if secrets.strip() else NO_SECRETS + "\n"
    rest = f"{body}\n\n## Secrets\n{tail}"
    header = (
        f"<!-- summary_native npc gm | npc: {subject} | draft sha256: "
        f"{_sha(draft_text) if draft_text is not None else 'none'} | authored sha256: "
        f"{_sha(authored_bytes) if authored_bytes is not None else 'none'} | composed sha256: {_sha(rest)} -->\n"
    )
    return header + rest


def is_hand_edited(existing_text: str) -> bool:
    """True when a composed file's body no longer matches the sha its header recorded."""
    m = _GM_HEADER_RE.match(existing_text)
    if m is None:
        return True
    return _sha(existing_text[m.end():]) != m.group("composed")


def _write_composed(out_path: Path, text: str) -> bool:
    """Write the composed file; True when it replaced a hand-edited one. This is the only write here."""
    edited = out_path.is_file() and is_hand_edited(out_path.read_text(encoding="utf-8"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out_path, text)
    return edited


def compose_gm(
    draft_path: Path | None,
    authored_path: Path,
    out_path: Path,
    subject: str,
    stem: str | None = None,
) -> ComposeResult:
    """Write ``out_path`` from the draft (if any) and the authored Secrets (if any).

    Raises ``npc_authored.AuthoredError`` for a malformed or mismatched authored file.
    """
    draft_text = None
    if draft_path is not None and Path(draft_path).is_file():
        draft_text = Path(draft_path).read_text(encoding="utf-8")
    secrets = npc_authored.load_secrets(authored_path, subject)  # validates subject/shape too
    authored_bytes = Path(authored_path).read_bytes() if Path(authored_path).is_file() else None
    text = compose_text(subject, draft_text, secrets, authored_bytes)
    edited = _write_composed(Path(out_path), text)
    return ComposeResult(stem or out_path.stem, subject, out_path, edited, draft_text is not None, bool(secrets.strip()))


def hand_edit_warning(result: ComposeResult, root: Path) -> str:
    return (
        f"warning: {schema.display_path(result.out_path, root)} had an unrecorded hand-edit; discarded "
        f"(put corrections in {schema.AUTHORED_DIR}/{npc_slug.slug_for(result.subject)}.authored.yaml)"
    )


def init(root: Path, subjects: list[str]) -> list[tuple[str, str | None]]:
    """Create an empty authored file for each subject. ``(subject, error)`` per name; an
    existing file is an error for that name only. Composes nothing."""
    out = []
    for subject in subjects:
        try:
            npc_authored.init_authored(authored_path_for(root, subject), subject)
            out.append((subject, None))
        except npc_authored.AuthoredError as e:
            out.append((subject, str(e)))
    return out


# ── Many NPCs ───────────────────────────────────────────────────────────────

DRAFT_DIR = "draft"
GM_DIR = "gm"


def known_npcs(npc_range_dir: Path) -> dict[str, str]:
    """``{stem: subject}`` for every NPC that has evidence or a draft dossier in the range."""
    out = {e.stem: e.subject for e in npc_link.read_evidence_files(npc_range_dir)}
    for p in sorted((Path(npc_range_dir) / DRAFT_DIR).glob("*.md")):
        if p.name.endswith((".incomplete.md", ".verify.md")) or p.stem in out:
            continue
        header, _ = npc_link.split_frontmatter(draft_body(p.read_text(encoding="utf-8")))
        m = re.search(r"^subject: (.+)$", header, re.MULTILINE)
        if m:
            out[p.stem] = m.group(1).strip().strip("'\"")
    return out


class ComposeRefusal(Exception):
    """A request compose cannot honour (CLI exit 2)."""


def compose_many(root: Path, npc_range_dir: Path, names: list[str] | None) -> list[ComposeResult]:
    """Compose GM dossiers for ``names`` (default: every NPC with a draft dossier or an
    authored file). Everything is validated before anything is written."""
    npc_range_dir = Path(npc_range_dir)
    known = known_npcs(npc_range_dir)
    by_name = {subject.casefold(): stem for stem, subject in known.items()}
    has_draft = lambda stem: (npc_range_dir / DRAFT_DIR / f"{stem}.md").is_file()  # noqa: E731
    has_file = lambda subject: authored_path_for(root, subject).is_file()  # noqa: E731
    if names:
        targets = []
        for name in names:
            stem = by_name.get(name.strip().casefold())
            if stem is None:
                raise ComposeRefusal(f"{name}: no NPC with that name has evidence or a draft in this range")
            if not (has_draft(stem) or has_file(known[stem])):
                raise ComposeRefusal(f"{name}: has neither a draft dossier nor an authored file to compose from")
            targets.append(stem)
    else:
        targets = [s for s in sorted(known) if has_draft(s) or has_file(known[s])]
    try:
        for stem in targets:  # validate first: a bad file stops the run before any write
            npc_authored.load_secrets(authored_path_for(root, known[stem]), known[stem])
    except npc_authored.AuthoredError as e:
        raise ComposeRefusal(str(e)) from None
    results = []
    for stem in targets:
        draft = npc_range_dir / DRAFT_DIR / f"{stem}.md"
        results.append(
            compose_gm(
                draft if draft.is_file() else None,
                authored_path_for(root, known[stem]),
                npc_range_dir / GM_DIR / f"{stem}.md",
                known[stem],
                stem,
            )
        )
    return results
