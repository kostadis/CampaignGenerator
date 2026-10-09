"""Corpus freshness check shared by every stage that reads a built corpus.

Moved out of ``synth`` so ``npc-link`` and ``npc-draft`` refuse on the same
terms (spec 032 T006). Behaviour is unchanged. No model call.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pipelines.summary_native import corpus, npc_forms, npc_link, schema
from pipelines.summary_native.authority import POLICY_VERSION, SCHEMA_VERSION


def check_fresh(report, range_dir: Path, root: Path, manifest: dict, registry_path: Path | None) -> str | None:
    """FR-005b: refuse when any in-range file, or the entity registry, differs from the build.

    The registry is hashed because it decides how headings group into dossiers, so a
    changed registry means the built corpus no longer matches what ``build`` would
    produce now. canon.yaml is deliberately NOT compared: it holds not-a-duplicate
    rulings that affect validation findings only, never the corpus content.
    """
    state = corpus.describe_existing(range_dir, report, root)
    if state is None or state.get("state") != "matches":
        return "summaries changed since build — run `summary_native build --force`"
    built = (manifest.get("canon") or {}).get("registry_sha256")
    now_sha = corpus.sha256_file(registry_path) if registry_path is not None and registry_path.is_file() else None
    if built != now_sha:
        return "entity registry changed since build — run `summary_native build --force`"
    return None


def sha_file(path: Path | None) -> str | None:
    return corpus.sha256_file(path) if path is not None and Path(path).is_file() else None


def authority_manifest_sha256(manifest: dict | None) -> str | None:
    """Stable identity for the exact authority input consumed by a derived run."""
    if manifest is None:
        return None
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _authority_manifest_version_problem(
    recorded: object,
    current: dict | None,
    *,
    artifact: str,
    regenerate_command: str,
) -> str | None:
    """Refuse retired authority-aware artifacts instead of guessing their shape.

    Summary-only artifacts have no authority manifest and remain compatible while
    authority is disabled.  Once a caller supplies a current authority manifest,
    every reused artifact must declare the exact schema and policy versions that
    formed its cache/run identity.  There is deliberately no legacy fallback or
    read-time rewrite: regeneration creates the supported shape.
    """
    if current is None or "authority_schema" not in current or "authority_policy" not in current:
        return None
    if not isinstance(recorded, dict):
        return (
            f"authority inputs changed since this output: {artifact} predates authority inputs; rerun `{regenerate_command} --force` "
            "to regenerate it with the current authority manifest"
        )
    schema_version = recorded.get("authority_schema")
    policy_version = recorded.get("authority_policy")
    if schema_version is None or policy_version is None:
        return (
            f"{artifact} uses a retired authority manifest schema; rerun "
            f"`{regenerate_command} --force` to regenerate it"
        )
    if schema_version != SCHEMA_VERSION or policy_version != POLICY_VERSION:
        return (
            f"{artifact} uses unsupported authority manifest version "
            f"schema={schema_version!r}, policy={policy_version!r}; rerun "
            f"`{regenerate_command} --force` to regenerate it"
        )
    return None


def check_authority_output_fresh(run_record: dict, current_manifest: dict | None) -> str | None:
    """Refuse publishing a derived output whose reviewed authority input moved."""
    recorded = (run_record.get("inputs") or {}).get("authority_manifest")
    version_problem = _authority_manifest_version_problem(
        recorded,
        current_manifest,
        artifact="existing run record",
        regenerate_command="summary_native synth",
    )
    if version_problem:
        return version_problem
    if authority_manifest_sha256(recorded) != authority_manifest_sha256(current_manifest):
        return "authority inputs changed since this output — rerun synthesis with --force"
    return None


def check_authority_cache_fresh(cache_entry: dict, current_manifest: dict | None) -> str | None:
    """Return a regeneration refusal for a retired authority-aware cache entry.

    Cache readers use exact cache keys for normal admission.  This shared guard
    makes the schema boundary explicit for callers that persist an authority
    manifest next to a reusable result, and avoids silently accepting a retired
    authority cache shape during future cache routing changes.
    """
    recorded = cache_entry.get("authority_manifest") if isinstance(cache_entry, dict) else None
    return _authority_manifest_version_problem(
        recorded,
        current_manifest,
        artifact="cached authority output",
        regenerate_command="summary_native extract",
    )


_DRAFT_RECORD_RE = re.compile(r"\brecord:\s+runs/([^/\s]+)/record\.json\b")


def check_authority_draft_fresh(draft_path: Path, current_manifest: dict | None) -> str | None:
    """Return an authority-staleness refusal for an existing generated draft.

    A draft carries the run-record reference in its generated header.  Resolve it
    relative to the range directory, then compare the recorded snapshot with the
    one the caller just built under the authority read lock.  A missing or broken
    reference is deliberately stale: an old draft cannot silently look current.
    """
    try:
        header = Path(draft_path).read_text(encoding="utf-8").split("\n", 1)[0]
        match = _DRAFT_RECORD_RE.search(header)
        if match is None:
            return "existing draft has no authority run record — rerun synthesis with --force"
        record_path = Path(draft_path).parent.parent / "runs" / match.group(1) / "record.json"
        run_record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "existing draft authority run record is unreadable — rerun synthesis with --force"
    return check_authority_output_fresh(run_record, current_manifest)


def manual_sha(manual: list[str]) -> str:
    """The digest of an NPC's manual edits that ``npc-draft`` records and the web page compares."""
    return hashlib.sha256(json.dumps(manual, ensure_ascii=False).encode("utf-8")).hexdigest()


def check_link_fresh(
    npc_range_dir: Path, range_dir: Path, registry_path: Path | None, canon_path: Path | None, evidence_shas: dict,
    players_path: Path | None = None,
) -> str | None:
    """A refusal message when link output is missing or stale against the corpus, else None."""
    mp = npc_range_dir / npc_link.LINK_MANIFEST
    if not mp.is_file():
        return "no link output for this range; run `summary_native npc-link`"
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "link_manifest.json is unreadable; run `summary_native npc-link --force`"
    if m.get("kind") != "npc_link":
        return "link_manifest.json is not an npc_link manifest; run `summary_native npc-link --force`"
    _, wl_sha = npc_forms.load_wordlist()
    now = {
        "corpus_manifest_sha256": corpus.sha256_file(range_dir / "manifest.json"),
        "registry_sha256": sha_file(registry_path),
        "canon_sha256": sha_file(canon_path),
        "wordlist_sha256": wl_sha,
        "players_sha256": sha_file(players_path),
    }
    for k, v in now.items():
        if m.get(k) != v:
            return f"link output is stale ({k.removesuffix('_sha256').replace('_', ' ')} changed); run `summary_native npc-link --force`"
    if m.get("evidence") != evidence_shas:
        return "evidence/ no longer matches link_manifest.json; run `summary_native npc-link --force`"
    return None


# ── Chunked state notes and the audit (spec 033) ────────────────────────────

NOTES_MANIFEST = "manifest.json"
EXTRACT_CMD = "`summary_native extract`"
AUDIT_CMD = "`summary_native audit`"


def audience_slug(audience: str) -> str:
    """Filesystem-safe stable namespace for one audience's derived artifacts."""
    if audience == "gm":
        return "gm"
    if audience in {"players", "characters"}:
        return audience
    readable = re.sub(r"[^a-z0-9]+", "-", audience.lower()).strip("-") or "audience"
    # The readable portion helps operators inspect state, while the exact
    # target digest prevents case/space/punctuation normalization collisions.
    return f"{readable}-{hashlib.sha256(audience.encode('utf-8')).hexdigest()[:12]}"


def audience_state_dir(range_dir: Path, audience: str = "gm") -> Path:
    """GM keeps the historic state location; every other audience is isolated."""
    base = Path(range_dir) / schema.STATE_DIR
    return base if audience == "gm" else base / "audiences" / audience_slug(audience)


def notes_dir(range_dir: Path, audience: str = "gm") -> Path:
    return audience_state_dir(range_dir, audience) / "notes"


def audit_dir(range_dir: Path) -> Path:
    return Path(range_dir) / schema.STATE_DIR / "audit"


def notes_manifest_facts(range_dir: Path, registry_path: Path | None, players_path: Path | None) -> dict:
    """The input digests ``extract`` records in ``state/notes/manifest.json`` and
    ``check_notes_fresh`` compares, declared once so the two sides cannot drift.

    Published dossiers are deliberately not an input: ``synth world_state`` reads them live at
    build time, and the run record keeps their sha256 so two builds can be compared.
    """
    return {
        "corpus_manifest_sha256": sha_file(Path(range_dir) / "manifest.json"),
        "registry_sha256": sha_file(registry_path),
        "players_sha256": sha_file(players_path),
    }


def check_notes_fresh(
    range_dir: Path, registry_path: Path | None, players_path: Path | None, *, extract_cmd: str = "summary_native extract",
    audience: str = "gm",
) -> str | None:
    """A refusal message when the checked notes are missing or stale, else ``None``.

    Stale means the corpus manifest, the entity registry or ``players.yaml`` differs from what
    ``extract`` recorded. The message names the command to re-run; ``extract_cmd`` lets the caller
    spell it with the range (``summary_native extract --since 2 --until 70``).
    """
    mp = notes_dir(range_dir, audience) / NOTES_MANIFEST
    if not mp.is_file():
        return f"no checked notes for this range; run `{extract_cmd}`"
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"state/notes/manifest.json is unreadable; run `{extract_cmd} --force`"
    if not isinstance(m, dict) or m.get("kind") != "state_notes":
        return f"state/notes/manifest.json is not a state-notes manifest; run `{extract_cmd} --force`"
    for k, v in notes_manifest_facts(range_dir, registry_path, players_path).items():
        if m.get(k) != v:
            return f"checked notes are stale ({k.removesuffix('_sha256').replace('_', ' ')} changed); run `{extract_cmd}`"
    if m.get("audience", "gm") != audience:
        return f"checked notes belong to a different audience; run `{extract_cmd}`"
    return None


def check_party_grammar(range_dir: Path) -> str | None:
    """A refusal message when the checked notes were extracted under an older ``## Party`` grammar, else ``None``.

    ``extract`` records the sha256 of its system prompt in the notes manifest. Party notes written
    before the subject grammar (spec 034, research R1) carry no subject, so ``party`` and ``planning``
    cannot attribute them. A missing or unreadable manifest is ``check_notes_fresh``'s report, not this one.
    """
    from pipelines.summary_native import context, extract  # lazy: both import this module

    mp = notes_dir(range_dir) / NOTES_MANIFEST
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict):
        return None
    if m.get("system_sha256") == sha_file(context.PROMPT_DIR / extract.SYSTEM_PROMPT):
        return None
    rng = m.get("range") or {}
    span = f" --since {rng['since']} --until {rng['until']}" if "since" in rng and "until" in rng else ""
    return (
        "the party notes predate the subject grammar; "
        f"run `summary_native extract{span}` (it re-extracts every chunk)"
    )


def track_files_facts(track_files) -> list[list[str]]:
    """``[[file name, sha256], ...]`` sorted, so it is independent of argument order and holds no
    absolute path. A missing file digests as the empty string."""
    return sorted([Path(p).name, sha_file(Path(p)) or ""] for p in track_files)


def audit_exists(range_dir: Path) -> bool:
    return (audit_dir(range_dir) / "items.json").is_file()


def check_audit_fresh(range_dir: Path, track_files) -> str | None:
    """A refusal message when ``state/audit/items.json`` is stale, else ``None``.

    Stale means a track file was added, removed or changed since ``audit`` ran, or the checked
    notes were re-extracted. **No audit at all is not a refusal**: ``synth campaign_state`` says
    "Audit not run for this range" for that (``audit_exists`` tells the two apart).
    """
    ip = audit_dir(range_dir) / "items.json"
    if not ip.is_file():
        return None
    try:
        m = json.loads(ip.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"state/audit/items.json is unreadable; run {AUDIT_CMD} --force"
    now = track_files_facts(track_files)
    was = m.get("track_files_sha256") or []
    if was != now:
        differing = sorted({n for n, _ in now} ^ {n for n, _ in was} | {n for n, s in now if [n, s] not in was})
        return f"the audit is stale (track file(s) changed: {', '.join(differing)}); run {AUDIT_CMD}"
    if m.get("notes_manifest_sha256") != sha_file(notes_dir(range_dir) / NOTES_MANIFEST):
        return f"the audit is stale (the checked notes changed); run {AUDIT_CMD}"
    return None
