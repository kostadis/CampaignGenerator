"""Corpus freshness check shared by every stage that reads a built corpus.

Moved out of ``synth`` so ``npc-link`` and ``npc-draft`` refuse on the same
terms (spec 032 T006). Behaviour is unchanged. No model call.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipelines.summary_native import corpus, npc_forms, npc_link


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
