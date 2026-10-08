"""Corpus freshness check shared by every stage that reads a built corpus.

Moved out of ``synth`` so ``npc-link`` and ``npc-draft`` refuse on the same
terms (spec 032 T006). Behaviour is unchanged. No model call.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipelines.summary_native import corpus, npc_forms, npc_link, schema


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


def notes_dir(range_dir: Path) -> Path:
    return Path(range_dir) / schema.STATE_DIR / "notes"


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
    range_dir: Path, registry_path: Path | None, players_path: Path | None, *, extract_cmd: str = "summary_native extract"
) -> str | None:
    """A refusal message when the checked notes are missing or stale, else ``None``.

    Stale means the corpus manifest, the entity registry or ``players.yaml`` differs from what
    ``extract`` recorded. The message names the command to re-run; ``extract_cmd`` lets the caller
    spell it with the range (``summary_native extract --since 2 --until 70``).
    """
    mp = notes_dir(range_dir) / NOTES_MANIFEST
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
    return None


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
