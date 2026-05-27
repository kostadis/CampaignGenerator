"""resolve_refs.py — resolve a campaign's refs.yaml into concrete JSON paths.

A campaign's navigation-index scope lives in two files at the campaign root:

* ``refs.yaml`` — git-tracked, portable across machines. Names content as
  abstract references (canonical source codes, rpg-lib relative paths,
  homebrew-private relative paths).
* ``refs.local.yaml`` — git-ignored, per-machine. Names the *root* directories
  those abstract references resolve against on this machine.

This module reads both, applies the resolution rules, and returns a
deterministic list of absolute JSON paths plus the canonical source-code set.
The launcher (``launch_5etools_mcp.py``) consumes this output to build a
per-campaign symlink farm and start the 5etools MCP server with the right
``DATA_DIRS`` env var.

No HTTP dependencies — purely filesystem. The optional ``query_rpg_lib.py``
authoring helper uses ``rpg_library.db`` directly via ``library_api/db.py``
to find books at refs-authoring time, but the resolver itself never opens
that DB.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


REFS_FILENAME = "refs.yaml"
LOCAL_FILENAME = "refs.local.yaml"

# Default roots used when neither refs.local.yaml nor env vars set the path.
# rpg_library has no default — the PDF corpus location genuinely varies.
_DEFAULT_ROOTS = {
    "fivetools_data": Path("~/src/5etools-kostadis/data").expanduser(),
    "homebrew_private": Path("~/src/homebrew-private").expanduser(),
}
_ROOT_ENV_VARS = {
    "fivetools_data": "FIVETOOLS_DATA_ROOT",
    "rpg_library": "RPG_LIBRARY_ROOT",
    "homebrew_private": "HOMEBREW_PRIVATE_ROOT",
}


# ── Data classes ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedRoot:
    """One root directory + the source that determined its value."""

    name: str
    path: Path
    source: str  # "refs.local.yaml" | "env" | "default"


@dataclass(frozen=True)
class ResolvedRef:
    """One resolved entry from the refs: list."""

    kind: str  # "rpglib" | "homebrew_private" | "path"
    abstract: str  # what was in refs.yaml (relative path or abs path)
    json_path: Path  # absolute path to the resolved JSON file
    note: str | None = None
    book_id: int | None = None  # only for rpglib refs


@dataclass(frozen=True)
class ResolvedScope:
    """The full resolved scope for a campaign's MCP launch."""

    canonical_mode: str  # "all" | "whitelist"
    canonical_sources: list[str]  # source codes IN scope (post-exclude)
    canonical_excluded: list[str]  # source codes dropped (only when mode=all)
    refs: list[ResolvedRef]
    roots: dict[str, ResolvedRoot]
    refs_path: Path
    local_path: Path | None  # None if refs.local.yaml didn't exist


# ── Loading ──────────────────────────────────────────────────────────────


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SystemExit(f"resolve_refs: {path}: {exc}")


def load_refs(campaign_dir: Path) -> tuple[dict, Path]:
    """Load and validate refs.yaml. Returns (raw_dict, resolved_path)."""
    refs_path = (campaign_dir / REFS_FILENAME).resolve()
    if not refs_path.is_file():
        raise SystemExit(f"resolve_refs: {refs_path} not found")
    raw = _load_yaml(refs_path)
    if raw is None:
        raise SystemExit(f"resolve_refs: {refs_path} is empty")
    if not isinstance(raw, dict):
        raise SystemExit(
            f"resolve_refs: {refs_path}: top level must be a mapping"
        )
    return raw, refs_path


def load_local(campaign_dir: Path) -> tuple[dict, Path | None]:
    """Load refs.local.yaml if present. Returns (raw_dict, path_or_None)."""
    local_path = (campaign_dir / LOCAL_FILENAME).resolve()
    if not local_path.is_file():
        return {}, None
    raw = _load_yaml(local_path)
    if raw is None:
        return {}, local_path
    if not isinstance(raw, dict):
        raise SystemExit(
            f"resolve_refs: {local_path}: top level must be a mapping"
        )
    return raw, local_path


# ── Root resolution ──────────────────────────────────────────────────────


def resolve_roots(local: dict, required: set[str]) -> dict[str, ResolvedRoot]:
    """Resolve named roots with precedence: refs.local.yaml > env > default.

    ``required`` is the set of root names actually needed by the refs being
    resolved. Roots not in ``required`` are skipped so a campaign that uses
    only canonical content doesn't need ``rpg_library`` set.
    """
    local_roots = local.get("roots") or {}
    if not isinstance(local_roots, dict):
        raise SystemExit("resolve_refs: refs.local.yaml 'roots:' must be a mapping")

    resolved: dict[str, ResolvedRoot] = {}
    missing: list[str] = []

    for name in required:
        # 1. refs.local.yaml
        if name in local_roots and local_roots[name]:
            p = Path(str(local_roots[name])).expanduser().resolve()
            resolved[name] = ResolvedRoot(name, p, "refs.local.yaml")
            continue
        # 2. env var
        env_var = _ROOT_ENV_VARS.get(name)
        if env_var and os.environ.get(env_var):
            p = Path(os.environ[env_var]).expanduser().resolve()
            resolved[name] = ResolvedRoot(name, p, f"env:{env_var}")
            continue
        # 3. default
        if name in _DEFAULT_ROOTS:
            resolved[name] = ResolvedRoot(name, _DEFAULT_ROOTS[name].resolve(), "default")
            continue
        missing.append(name)

    if missing:
        hint = ", ".join(
            f"set 'roots.{n}:' in refs.local.yaml or {_ROOT_ENV_VARS.get(n, '?')}"
            for n in missing
        )
        raise SystemExit(
            f"resolve_refs: required root(s) not configured: {missing}. {hint}"
        )

    return resolved


# ── Canonical resolution ─────────────────────────────────────────────────


def _read_5etools_index(data_root: Path, rel: str) -> dict:
    """Read a 5etools index file (adventures.json, bestiary/index.json, …).

    Raises SystemExit if the file is missing or malformed, with a hint that
    the fivetools_data root may be misconfigured.
    """
    p = data_root / rel
    if not p.is_file():
        raise SystemExit(
            f"resolve_refs: expected 5etools index {p} not found. "
            f"Is roots.fivetools_data ({data_root}) pointing at a valid 5etools data tree?"
        )
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"resolve_refs: malformed JSON in {p}: {exc}")


def list_canonical_sources(data_root: Path) -> list[str]:
    """Enumerate every WotC source code present in the canonical tree.

    Pulls from adventures.json + books.json + bestiary/index.json +
    spells/index.json. Returns a sorted deduplicated list.
    """
    sources: set[str] = set()
    adv = _read_5etools_index(data_root, "adventures.json")
    for entry in adv.get("adventure", []):
        if "id" in entry:
            sources.add(entry["id"])
    bks = _read_5etools_index(data_root, "books.json")
    for entry in bks.get("book", []):
        if "id" in entry:
            sources.add(entry["id"])
    bestiary_index = _read_5etools_index(data_root, "bestiary/index.json")
    sources.update(bestiary_index.keys())
    spells_index = _read_5etools_index(data_root, "spells/index.json")
    sources.update(spells_index.keys())
    return sorted(sources)


def resolve_canonical(
    refs_doc: dict,
    data_root: Path,
) -> tuple[str, list[str], list[str]]:
    """Return (mode, sources_in_scope, sources_excluded).

    ``mode`` is "all" or "whitelist". ``sources_in_scope`` lists source codes
    that should contribute files to the MCP scope. ``sources_excluded`` is
    populated only in "all" mode and records which sources got dropped.
    """
    canonical = refs_doc.get("canonical", "all")
    excludes_raw = refs_doc.get("canonical_exclude") or []
    if not isinstance(excludes_raw, list):
        raise SystemExit(
            "resolve_refs: 'canonical_exclude:' must be a list of source codes"
        )
    excludes = {str(s) for s in excludes_raw}

    if canonical == "all" or canonical is None:
        all_sources = list_canonical_sources(data_root)
        in_scope = [s for s in all_sources if s not in excludes]
        # Excluded items the user named but that don't exist in canonical — warn,
        # but don't fail. Catches typos like "DOG" when they meant "DoD".
        excluded_present = [s for s in all_sources if s in excludes]
        # The "missing excludes" case is informational only — caller decides
        # whether to surface it; we just return what we computed.
        return "all", in_scope, excluded_present

    if isinstance(canonical, list):
        whitelist = [str(s) for s in canonical]
        all_sources = set(list_canonical_sources(data_root))
        unknown = [s for s in whitelist if s not in all_sources]
        if unknown:
            raise SystemExit(
                f"resolve_refs: canonical whitelist contains unknown source code(s): {unknown}. "
                f"Run with --status to see the canonical source list."
            )
        if excludes:
            raise SystemExit(
                "resolve_refs: 'canonical_exclude:' only applies when 'canonical: all'. "
                "Remove the exclude list or switch canonical back to 'all'."
            )
        return "whitelist", whitelist, []

    raise SystemExit(
        f"resolve_refs: 'canonical:' must be 'all' or a list of source codes, got {canonical!r}"
    )


# ── Ref resolution ───────────────────────────────────────────────────────


def _pdf_to_json_sidecar(pdf_path: Path) -> Path:
    """Mirror rpg-lib's algorithm at ``library_api/sidecar.py:26-40``.

    PDF ``foo.pdf`` → sidecar ``foo.json`` in the same directory.
    """
    return pdf_path.parent / f"{pdf_path.stem}.json"


def _resolve_rpglib_entry(entry: dict, roots: dict[str, ResolvedRoot]) -> ResolvedRef:
    rel = str(entry["rpglib"])
    rpg_root = roots["rpg_library"].path
    pdf_path = (rpg_root / rel).resolve()
    json_path = _pdf_to_json_sidecar(pdf_path)
    if not json_path.is_file():
        raise SystemExit(
            f"resolve_refs: no JSON sidecar for {pdf_path}. "
            f"Expected {json_path}. "
            f"Has this PDF been converted via convert_book.py?"
        )
    return ResolvedRef(
        kind="rpglib",
        abstract=rel,
        json_path=json_path,
        note=entry.get("note"),
        book_id=entry.get("book_id"),
    )


def _resolve_homebrew_entry(
    entry: dict, roots: dict[str, ResolvedRoot]
) -> list[ResolvedRef]:
    rel = str(entry["homebrew_private"])
    root = roots["homebrew_private"].path
    target = (root / rel).resolve()
    if not target.exists():
        raise SystemExit(
            f"resolve_refs: homebrew_private path {target} does not exist "
            f"(from refs.yaml entry: homebrew_private: {rel!r})"
        )
    if target.is_file():
        return [
            ResolvedRef(
                kind="homebrew_private",
                abstract=rel,
                json_path=target,
                note=entry.get("note"),
            )
        ]
    # Directory: recursively include every *.json under it, skipping dotdirs.
    out: list[ResolvedRef] = []
    for jp in sorted(target.rglob("*.json")):
        if any(part.startswith(".") for part in jp.relative_to(target).parts):
            continue
        out.append(
            ResolvedRef(
                kind="homebrew_private",
                abstract=f"{rel}::{jp.relative_to(target)}",
                json_path=jp,
                note=entry.get("note"),
            )
        )
    if not out:
        raise SystemExit(
            f"resolve_refs: homebrew_private dir {target} contains no .json files"
        )
    return out


def _resolve_path_entry(entry: dict, campaign_dir: Path) -> ResolvedRef:
    raw = str(entry["path"])
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (campaign_dir / p).resolve()
    if not p.is_file():
        raise SystemExit(
            f"resolve_refs: path entry {p} is not a file "
            f"(from refs.yaml entry: path: {raw!r})"
        )
    return ResolvedRef(
        kind="path",
        abstract=raw,
        json_path=p,
        note=entry.get("note"),
    )


def _required_roots(refs_list: list[dict], canonical_mode: str) -> set[str]:
    required: set[str] = set()
    if canonical_mode is not None:  # always need fivetools_data for canonical
        required.add("fivetools_data")
    for entry in refs_list:
        if "rpglib" in entry:
            required.add("rpg_library")
        elif "homebrew_private" in entry:
            required.add("homebrew_private")
    return required


def _validate_refs_list(refs_list: Any) -> list[dict]:
    if refs_list is None:
        return []
    if not isinstance(refs_list, list):
        raise SystemExit("resolve_refs: 'refs:' must be a list")
    for i, entry in enumerate(refs_list, start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f"resolve_refs: refs[{i}] must be a mapping")
        keys = {"rpglib", "homebrew_private", "path"} & entry.keys()
        if len(keys) != 1:
            raise SystemExit(
                f"resolve_refs: refs[{i}] must have exactly one of "
                f"'rpglib:', 'homebrew_private:', or 'path:' "
                f"(found {sorted(keys) or 'none'})"
            )
    return refs_list


# ── Collision detection ──────────────────────────────────────────────────


def _source_id_from_filename(json_path: Path) -> str | None:
    """Best-effort source-code extraction from a 5etools-style filename.

    ``bestiary-mm.json`` → ``MM`` (uppercased). ``adventure-oota.json`` →
    ``OotA``-ish. Returns None if the filename doesn't follow a known prefix.

    Used only for collision detection; the actual MCP loader reads sources
    from inside each JSON file.
    """
    stem = json_path.stem
    for prefix in ("bestiary-", "spells-", "adventure-", "book-", "fluff-bestiary-", "fluff-"):
        if stem.startswith(prefix):
            return stem[len(prefix):].upper()
    return None


def _detect_collisions(
    canonical_sources: list[str],
    refs: list[ResolvedRef],
) -> None:
    """Raise SystemExit if any ref overlaps a canonical source code or another ref."""
    canonical_set = {s.upper() for s in canonical_sources}
    seen: dict[str, ResolvedRef] = {}
    for r in refs:
        sid = _source_id_from_filename(r.json_path)
        if not sid:
            continue
        if sid in canonical_set:
            raise SystemExit(
                f"resolve_refs: ref {r.abstract!r} resolves to source code {sid!r} "
                f"which is already in the canonical scope. Either rename the homebrew "
                f"or exclude {sid!r} from canonical."
            )
        if sid in seen:
            raise SystemExit(
                f"resolve_refs: two refs both resolve to source code {sid!r}: "
                f"{seen[sid].abstract!r} and {r.abstract!r}. Rename one."
            )
        seen[sid] = r


# ── Top-level entry point ────────────────────────────────────────────────


def resolve(campaign_dir: Path) -> ResolvedScope:
    """Read refs.yaml + refs.local.yaml from ``campaign_dir`` and return a
    fully-resolved scope.

    Errors are raised as ``SystemExit`` with a single-line message naming
    the offending file/ref, so the launcher's surface is uniform.
    """
    campaign_dir = campaign_dir.resolve()
    refs_doc, refs_path = load_refs(campaign_dir)
    local_doc, local_path = load_local(campaign_dir)

    refs_list = _validate_refs_list(refs_doc.get("refs"))

    # Determine which roots we actually need before resolving them.
    required = _required_roots(refs_list, refs_doc.get("canonical", "all"))
    roots = resolve_roots(local_doc, required)

    # Canonical first, then refs.
    canonical_mode, canonical_sources, canonical_excluded = resolve_canonical(
        refs_doc, roots["fivetools_data"].path
    )

    resolved_refs: list[ResolvedRef] = []
    for entry in refs_list:
        if "rpglib" in entry:
            resolved_refs.append(_resolve_rpglib_entry(entry, roots))
        elif "homebrew_private" in entry:
            resolved_refs.extend(_resolve_homebrew_entry(entry, roots))
        elif "path" in entry:
            resolved_refs.append(_resolve_path_entry(entry, campaign_dir))

    _detect_collisions(canonical_sources, resolved_refs)

    return ResolvedScope(
        canonical_mode=canonical_mode,
        canonical_sources=canonical_sources,
        canonical_excluded=canonical_excluded,
        refs=resolved_refs,
        roots=roots,
        refs_path=refs_path,
        local_path=local_path,
    )
