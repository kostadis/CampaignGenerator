"""Publish reviewed NPC dossiers to ``docs/npcs/<slug>.md`` (spec 032 T042, FR-031, R16).

Deterministic, no model. This module is the only writer of ``docs/npcs/<slug>.md`` and of
``<npc root>/publish_log.json`` (default ``docs/npcs/summary_native/``); it never deletes, and it never writes,
renames or deletes anything under ``docs/npcs/authored/`` (hand-built dossiers there are
only read, whole, by ``npc_authored.read_handbuilt``).

Two sources, one gate:

* **summary_native** -- the GM dossier ``<range>/gm/<stem>.md``. Every ``[manual N]`` is
  rewritten to ``[GM]`` (the published file does not carry the numbered list), chapter
  citations are kept, the Secrets section is included.
* **hand-built** -- ``authored/<slug>.md``, copied verbatim.

Both go below a provenance header whose ``published sha256`` is the digest of everything
below the header line. That digest is what a later publish compares against
``publish_log.json`` (or, when the log has no entry, against the header itself) to notice
a hand-edit.

The verification verdict is read from the files the contract defines, not from
``npc_verify``: ``draft/<stem>.verify.md`` first (written by every verification), else
the newest ``runs/*/record.json`` ``npcs[stem].verify.verdict``. Neither present means
"not verified", which refuses like a failure.

Layout note for the AST guard in ``tests/test_no_writes_to_authored.py``: functions that
write contain no mention of the hand-built directory; the reading ones never write.

No model call (guarded by ``tests/test_summary_native_no_llm.py``).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from campaignlib.util import atomic_write_text
from pipelines.summary_native import npc_authored, npc_compose, npc_slug, schema

SOURCE_SN = "summary_native"
SOURCE_HB = "hand-built"
SOURCES = (SOURCE_SN, SOURCE_HB)

VERIFY_PASS = "pass"
VERIFY_NA = "not applicable"

LOG_NAME = "publish_log.json"

_HEADER_FIELD_RE = re.compile(r"published sha256: (\S+) -->\Z")
_GM_HEADER_RE = re.compile(
    r"\A<!-- summary_native npc gm \| npc: (?P<npc>.*?) \| draft sha256: (?P<draft>\S+) "
    r"\| authored sha256: (?P<authored>\S+) \| composed sha256: \S+ -->\n"
)
_DRAFT_HEADER_RE = re.compile(
    r"\A<!-- summary_native npc draft \| npc: .*? \| range: (?P<range>\S+) \| run: (?P<run>\S+?)(?: \||\s*-->)"
)
_VERDICT_RE = re.compile(r"\*\*Verdict: (pass|fail)\*\*")


class PublishRefusal(Exception):
    """The whole request cannot be honoured (no selection, unreadable log). CLI exit 2."""


@dataclass(frozen=True)
class PublishFacts:
    """Everything a provenance header names. Unused fields stay ``None`` for the other source."""

    source: str
    npc: str | None = None
    range: str | None = None
    run: str | None = None
    draft_sha: str | None = None
    authored_sha: str | None = None
    verify: str | None = None
    path: str | None = None  # hand-built: the file it was copied from, relative to the campaign root
    source_sha: str | None = None  # hand-built: sha256 of the copied file


@dataclass
class PublishItem:
    """One NPC's resolved plan: what to write, or why not."""

    name: str
    slug: str
    source: str | None = None
    refusal: str | None = None
    facts: PublishFacts | None = None
    body: str | None = None
    target: Path | None = None
    forced: list[str] = field(default_factory=list)  # which refusals --force overrode


@dataclass(frozen=True)
class PublishResult:
    name: str
    slug: str
    source: str | None
    published: bool
    reason: str | None = None
    forced: tuple[str, ...] = ()

    def line(self) -> str:
        """The contract's stdout line for this NPC."""
        if self.published:
            return f"{self.name}: published ({self.source})" + (
                f" [forced: {'; '.join(self.forced)}]" if self.forced else ""
            )
        return f"{self.name}: refused ({self.reason})"


# ── Pure helpers ────────────────────────────────────────────────────────────


def sha256_text(text: str | bytes) -> str:
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode("utf-8")).hexdigest()


def rewrite_manual_citations(text: str) -> str:
    """Every ``[manual N]`` becomes ``[GM]``; chapter citations are untouched (FR-031b)."""
    return schema.MANUAL_CITATION_RE.sub("[GM]", text)


def render_header(facts: PublishFacts, published_sha: str) -> str:
    """The one-line provenance comment, including its trailing newline."""
    p = schema.PUBLISH_HEADER_PREFIX
    if facts.source == SOURCE_HB:
        return (
            f"{p} | source: hand-built | path: {facts.path} | sha256: {facts.source_sha} "
            f"| verification: not applicable | published sha256: {published_sha} -->\n"
        )
    return (
        f"{p} | source: summary_native | npc: {facts.npc} | range: {facts.range} "
        f"| draft run: {facts.run} | draft sha256: {facts.draft_sha} "
        f"| authored sha256: {facts.authored_sha} | verify: {facts.verify} "
        f"| published sha256: {published_sha} -->\n"
    )


def render_published(source: str, body: str, facts: PublishFacts) -> str:
    """Header + body. ``body`` is what goes below the header line, byte for byte; the
    ``published sha256`` is its digest. ``source`` must agree with ``facts.source``."""
    if source != facts.source:
        raise ValueError(f"source {source!r} does not match the facts' source {facts.source!r}")
    return render_header(facts, sha256_text(body)) + body


def published_body_sha(text: str) -> tuple[str | None, str | None]:
    """``(digest of everything below the first line, the digest the header recorded)`` for a
    published file; ``(None, None)`` when the first line is not a publish header."""
    first, nl, rest = text.partition("\n")
    if not nl or not first.startswith(schema.PUBLISH_HEADER_PREFIX):
        return None, None
    m = _HEADER_FIELD_RE.search(first)
    return sha256_text(rest), (m.group(1) if m else None)


# ── Publish log ─────────────────────────────────────────────────────────────


def log_path(npc_root: Path) -> Path:
    """``<npc_root>/publish_log.json``, beside the range folders; ``npc_root`` is the range
    folder's parent, so ``--npc-root`` and ``npc_dossiers.yaml npc_root`` are followed."""
    return Path(npc_root) / LOG_NAME


def read_publish_log(root: Path, npc_root: Path) -> dict[str, dict]:
    """``{slug: {source, range, run, published_sha256, published_at}}``; ``{}`` when absent."""
    p = log_path(npc_root)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PublishRefusal(
            f"{schema.display_path(p, root)}: unreadable publish log ({type(e).__name__}); "
            "fix or remove it (it can be rebuilt from the headers in docs/npcs/)"
        ) from None
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise PublishRefusal(f"{schema.display_path(p, root)}: publish log must map each slug to an object")
    return data


def write_publish_log(npc_root: Path, log: dict[str, dict]) -> None:
    """Sorted keys, atomic write. The only write of the log."""
    _put(log_path(npc_root), json.dumps(log, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _put(path: Path, text: str) -> None:
    """Create parents and write atomically. Every write in this module goes through here."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)


# ── Reading the GM dossier and its verdict ──────────────────────────────────


def read_verdict(npc_range_dir: Path, stem: str) -> str | None:
    """``"pass"``, ``"fail"``, or ``None`` when the NPC has never been verified."""
    vmd = Path(npc_range_dir) / npc_compose.DRAFT_DIR / f"{stem}.verify.md"
    if vmd.is_file():
        m = _VERDICT_RE.search(vmd.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    for rec in sorted((Path(npc_range_dir) / "runs").glob("*/record.json"), reverse=True):
        try:
            data = json.loads(rec.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        verdict = ((data.get("npcs") or {}).get(stem) or {}).get("verify", {})
        verdict = verdict.get("verdict") if isinstance(verdict, dict) else None
        if verdict in ("pass", "fail"):
            return verdict
    return None


def _current_draft_signoff(root: Path, draft_path: Path, draft_sha256: str) -> bool:
    """Whether authority contains a current signoff for these exact draft bytes.

    The review item carries the verifier outcome as well as the digest.  A human
    approval of a mechanically failing item therefore cannot become publication
    authority, and a custody refresh that marks the item stale reopens the gate.
    """

    from pipelines.summary_native.authority import ReviewDecisionRecord, load_ledger
    from pipelines.summary_native.review.store import _reject_symlinks, read_review_state, read_snapshot

    root = Path(root).resolve()
    try:
        relative = Path(draft_path).resolve().relative_to(root).as_posix()
        ledger = load_ledger(root)
    except (OSError, ValueError):
        return False
    states: dict[str, tuple[tuple, list[dict], set[str], bool]] = {}
    for record in ledger.records:
        if (
            not isinstance(record, ReviewDecisionRecord)
            or record.status != "accepted"
            or record.domain != "npc_finding"
            or record.disposition != "document_signoff"
        ):
            continue
        try:
            if record.review_id not in states:
                _manifest, items, events, stale = read_review_state(root, record.review_id)
                _manifest, custody, _items = read_snapshot(root, record.review_id)
                custody_current = all(
                    (path := _reject_symlinks(root, root / source.path)).is_file()
                    and sha256_text(path.read_bytes()) == source.sha256
                    for source in custody.sources
                )
                states[record.review_id] = (items, events, stale, custody_current)
            items, events, stale, custody_current = states[record.review_id]
        except (OSError, ValueError):
            continue
        if record.item_id in stale or not custody_current:
            continue
        item = next(
            (
                candidate
                for candidate in items
                if candidate.item_id == record.item_id
                and candidate.revision == record.item_revision
                and candidate.review_digest == record.review_digest
            ),
            None,
        )
        if item is None:
            continue
        current = next(
            (
                event
                for event in reversed(events)
                if event.get("item_id") == item.item_id
                and event.get("kind") != "rebind"
            ),
            None,
        )
        details = item.proposed_action.details
        binding = next((value for value in item.input_bindings if value.path == relative), None)
        if (
            current is not None
            and current.get("event_id") == record.event_id
            and current.get("verdict") == "approve"
            and current.get("disposition") == "document_signoff"
            and item.proposed_action.action == "signoff_npc_draft"
            and details.get("draft_path") == relative
            and details.get("draft_sha256") == draft_sha256
            and details.get("verification_complete") is True
            and details.get("mechanical_verdict") == "pass"
            and binding is not None
            and binding.custody_sha256 == draft_sha256
        ):
            return True
    return False


def _range_name(npc_range_dir: Path) -> str:
    return Path(npc_range_dir).name


def _plan_summary_native(root: Path, npc_range_dir: Path, stem: str, subject: str, item: PublishItem,
                         signoff_checker: Callable[[Path, str], bool]) -> None:
    gm_path = Path(npc_range_dir) / npc_compose.GM_DIR / f"{stem}.md"
    text = gm_path.read_text(encoding="utf-8")
    m = _GM_HEADER_RE.match(text)
    if m is None:
        item.refusal = (
            f"{schema.display_path(gm_path, root)} has no GM-dossier header; run `summary_native npc-compose`"
        )
        return
    if m.group("draft") == "none":
        item.refusal = f"{schema.display_path(gm_path, root)} has no draft dossier behind it (not yet drafted)"
        return
    draft_path = Path(npc_range_dir) / npc_compose.DRAFT_DIR / f"{stem}.md"
    draft_bytes = draft_path.read_bytes() if draft_path.is_file() else None
    dm = _DRAFT_HEADER_RE.match(draft_bytes.decode("utf-8")) if draft_bytes is not None else None
    if dm is None:
        item.refusal = f"{schema.display_path(draft_path, root)}: draft header missing or unreadable; re-run npc-draft"
        return
    draft_sha256 = sha256_text(draft_bytes)
    if m.group("draft") != draft_sha256:
        item.refusal = "draft changed after composition; run `summary_native npc-compose` and recheck it"
        return
    verdict = read_verdict(npc_range_dir, stem)
    if verdict != "pass":
        why = "verification failed" if verdict == "fail" else "not verified"
        report = schema.display_path(Path(npc_range_dir) / npc_compose.DRAFT_DIR / f"{stem}.verify.md", root)
        item.refusal = (
            f"{why}; see {report}" if verdict == "fail" else f"{why}; run `summary_native npc-verify`"
        )
        return
    if not signoff_checker(draft_path, draft_sha256):
        item.refusal = (
            "NPC_DRAFT_SIGNOFF_REQUIRED: exact draft approval is missing or stale; "
            "create a real NPC verification review and run `summary_native review npc sign`"
        )
        return
    verify = VERIFY_PASS
    item.source = SOURCE_SN
    item.body = rewrite_manual_citations(text[m.end():])
    item.facts = PublishFacts(
        source=SOURCE_SN, npc=subject, range=dm.group("range"), run=dm.group("run"),
        draft_sha=m.group("draft"), authored_sha=m.group("authored"), verify=verify,
    )


def _plan_hand_built(root: Path, path: Path, item: PublishItem) -> None:
    try:
        text = npc_authored.read_handbuilt(path)
    except npc_authored.AuthoredError as e:
        item.refusal = str(e)
        return
    item.source = SOURCE_HB
    item.body = text
    item.facts = PublishFacts(
        source=SOURCE_HB, path=schema.display_path(path, root), source_sha=sha256_text(text.encode("utf-8")),
        verify=VERIFY_NA,
    )


# ── Planning ────────────────────────────────────────────────────────────────


def _handbuilt_files(root: Path) -> dict[str, Path]:
    """``{slug: path}`` for each hand-built ``<slug>.md`` (the ``.authored.yaml`` files are not dossiers)."""
    d = Path(root) / schema.AUTHORED_DIR
    return {p.stem: p for p in sorted(d.glob("*.md"))} if d.is_dir() else {}


def _target_check(root: Path, target: Path, slug: str, log: dict[str, dict], item: PublishItem,
                  force: bool) -> None:
    """Refuse (or note a forced override of) a foreign or hand-edited target."""
    if not target.is_file():
        return
    shown = schema.display_path(target, root)
    try:
        existing = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        existing = ""
    actual, in_header = published_body_sha(existing)
    if actual is None:
        reason, tag = (
            f"{shown} exists and was not published by summary_native (no provenance header)",
            "foreign target",
        )
    else:
        recorded = (log.get(slug) or {}).get("published_sha256") or in_header
        if actual == recorded:
            return
        reason, tag = (
            f"{shown} was edited by hand since it was published; move the correction into "
            f"{schema.AUTHORED_DIR}/{slug}.authored.yaml",
            "hand-edited target",
        )
    if force:
        item.forced.append(tag)
    else:
        item.refusal = reason


def plan_publish(
    root: Path,
    npc_range_dir: Path,
    *,
    names: Iterable[str] = (),
    all_: bool = False,
    authored_all: bool = False,
    source: str | None = None,
    force: bool = False,
    aliases: dict[str, str] | None = None,
    registry_npcs: Iterable[str] = (),
    _signoff_checker: Callable[[Path, str], bool] | None = None,
) -> list[PublishItem]:
    """Resolve the selection into one ``PublishItem`` per NPC (refusal or ready to write).

    Raises ``PublishRefusal`` for no selection, a bad ``source`` or an unreadable log.
    Writes nothing.
    """
    root, npc_range_dir = Path(root), Path(npc_range_dir)
    signoff_checker = _signoff_checker or (
        lambda path, digest: _current_draft_signoff(root, path, digest)
    )
    names = [n for n in names if n and n.strip()]
    if not (names or all_ or authored_all):
        raise PublishRefusal("no selection: give --name NAME, --all or --authored-all (publishing is always explicit)")
    if source is not None and source not in SOURCES:
        raise PublishRefusal(f"--source must be one of {', '.join(SOURCES)}")
    log = read_publish_log(root, npc_range_dir.parent)
    known = npc_compose.known_npcs(npc_range_dir)  # {stem: subject}
    by_name = {subject.casefold(): stem for stem, subject in known.items()}
    gm_exists = lambda stem: (npc_range_dir / npc_compose.GM_DIR / f"{stem}.md").is_file()  # noqa: E731
    handbuilt = _handbuilt_files(root)
    collisions = npc_slug.slug_collisions([*known.values(), *registry_npcs])

    # Selection -> ordered, de-duplicated (slug, display name, stem-or-None)
    chosen: dict[str, tuple[str, str | None]] = {}

    def add(slug: str, display: str, stem: str | None) -> None:
        if slug not in chosen:
            chosen[slug] = (display, stem)

    items: list[PublishItem] = []
    for name in names:
        key = name.strip().casefold()
        stem = by_name.get(key) or by_name.get((aliases or {}).get(key, "").casefold())
        if stem is not None:
            add(npc_slug.slug_for(known[stem]), known[stem], stem)
        elif npc_slug.slug_for(name) in handbuilt:
            add(npc_slug.slug_for(name), name.strip(), None)
        else:
            items.append(PublishItem(
                name=name.strip(), slug=npc_slug.slug_for(name),
                refusal=f"no GM dossier in {_range_name(npc_range_dir)} and no hand-built dossier for this name",
            ))
    if all_:
        for stem in sorted(known, key=lambda s: (known[s].casefold(), s)):
            if gm_exists(stem):
                add(npc_slug.slug_for(known[stem]), known[stem], stem)
    if authored_all:
        stem_by_slug = {npc_slug.slug_for(subject): stem for stem, subject in known.items()}
        for slug in handbuilt:
            stem = stem_by_slug.get(slug)
            add(slug, known[stem] if stem else slug, stem)

    for slug, (display, stem) in chosen.items():
        item = PublishItem(name=display, slug=slug, target=root / schema.NPCS_DIR / f"{slug}.md")
        items.append(item)
        if slug in collisions:
            item.refusal = f"slug collision: {', '.join(collisions[slug])} all map to '{slug}'"
            continue
        gm_path = npc_range_dir / npc_compose.GM_DIR / f"{stem}.md" if stem else None
        sn_real = bool(stem and gm_exists(stem) and "draft sha256: none" not in
                       gm_path.read_text(encoding="utf-8").split("\n", 1)[0])
        hb_path = handbuilt.get(slug)
        if sn_real and hb_path is not None and source is None:
            item.refusal = (
                f"both sources exist: {schema.display_path(gm_path, root)} and "
                f"{schema.display_path(hb_path, root)}; choose with --source summary_native|hand-built"
            )
            continue
        pick = source or (SOURCE_SN if sn_real else SOURCE_HB if hb_path is not None else SOURCE_SN)
        if pick == SOURCE_HB:
            if hb_path is None:
                item.refusal = f"no hand-built dossier {schema.AUTHORED_DIR}/{slug}.md"
                continue
            _plan_hand_built(root, hb_path, item)
        else:
            if stem is None or not gm_exists(stem):
                item.refusal = f"no GM dossier in {_range_name(npc_range_dir)}; run `summary_native npc-draft`"
                continue
            _plan_summary_native(root, npc_range_dir, stem, display, item, signoff_checker)
        if item.refusal is None:
            _target_check(root, item.target, slug, log, item, force)
    return items


# ── Publishing ──────────────────────────────────────────────────────────────


def publish(
    root: Path,
    npc_range_dir: Path,
    *,
    names: Iterable[str] = (),
    all_: bool = False,
    authored_all: bool = False,
    source: str | None = None,
    force: bool = False,
    aliases: dict[str, str] | None = None,
    registry_npcs: Iterable[str] = (),
    now: Callable[[], datetime] | None = None,
    _signoff_checker: Callable[[Path, str], bool] | None = None,
) -> list[PublishResult]:
    """Publish every selected NPC that passes its checks; return one result per NPC.

    A refusal for one NPC never stops the others. The caller exits 2 when any result is
    not ``published``. Raises ``PublishRefusal`` (nothing written) when the request as a
    whole is refused. Nothing is ever deleted.
    """
    root, npc_range_dir = Path(root), Path(npc_range_dir)

    def write() -> list[PublishResult]:
        items = plan_publish(
            root, npc_range_dir, names=names, all_=all_, authored_all=authored_all, source=source,
            force=force, aliases=aliases, registry_npcs=registry_npcs,
            _signoff_checker=_signoff_checker,
        )
        log = read_publish_log(root, npc_range_dir.parent)
        results = []
        for it in items:
            if it.refusal is not None:
                results.append(PublishResult(it.name, it.slug, it.source, False, it.refusal))
                continue
            text = render_published(it.source, it.body, it.facts)
            _put(it.target, text)
            stamp = (now or (lambda: datetime.now(timezone.utc)))().isoformat(timespec="seconds")
            log[it.slug] = {
                "source": it.source,
                "range": it.facts.range,
                "run": it.facts.run,
                "published_sha256": sha256_text(it.body),
                "published_at": stamp,
            }
            write_publish_log(npc_range_dir.parent, log)
            results.append(PublishResult(it.name, it.slug, it.source, True, None, tuple(it.forced)))
        return results

    if _signoff_checker is not None:
        return write()
    from pipelines.summary_native.authority_apply import authority_lock, require_no_pending_transaction

    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        return write()
