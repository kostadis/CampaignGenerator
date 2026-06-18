"""launch_5etools_mcp.py — per-campaign launcher for the 5etools MCP server.

Reads the campaign's ``refs.yaml`` + ``refs.local.yaml`` via ``resolve_refs``,
builds a per-campaign symlink farm at ``~/.5etools-mcp-runtime/<slug>/``, and
``exec``s the 5etools MCP server with ``DATA_DIRS`` set so it sees exactly the
in-scope content for this campaign.

The runtime tree has two roots:

* ``data/`` — the canonical 5etools tree, either as a single symlink (when no
  ``canonical_exclude`` is in play) or as a filtered mirror that hides
  excluded sources from ``adventures.json`` / ``books.json`` / ``bestiary/index.json``
  / ``spells/index.json`` and only symlinks the in-scope per-source files.
* ``homebrew/`` — generated 5etools-style layout for the campaign's purchased
  and homebrew content. Indices (``adventures.json``, ``books.json``,
  ``bestiary/index.json``, ``spells/index.json``) are synthesised from the
  refs; per-source files are symlinked into the right subdirs.

Idempotence: a sha256 over ``refs.yaml`` + ``refs.local.yaml`` is stored at
``<runtime>/.sources.sha256``. Repeated launches with unchanged refs skip
the rebuild.

Subcommands (flags):

* default — build runtime tree, ``exec`` the MCP server.
* ``--status`` — show the resolved scope. No build, no exec.
* ``--dry-run`` — build the runtime tree but do not exec.
* ``--init-local`` — write a starter ``refs.local.yaml`` with detected
  defaults. Non-destructive (refuses to overwrite an existing file).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import yaml

import resolve_refs as rr


# ── Constants ────────────────────────────────────────────────────────────


RUNTIME_BASE = Path("~/.5etools-mcp-runtime").expanduser()
DEFAULT_MCP_INDEX = Path("~/src/5etools-kostadis/mcp/index.js").expanduser()
SHA_FILENAME = ".sources.sha256"


# ── Runtime tree location ────────────────────────────────────────────────


def _slug(campaign_dir: Path) -> str:
    """Stable slug from a campaign dir name. Strips dots/spaces, lowercases."""
    name = campaign_dir.resolve().name
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "campaign"


def runtime_dir_for(campaign_dir: Path) -> Path:
    return RUNTIME_BASE / _slug(campaign_dir)


# ── Idempotence ──────────────────────────────────────────────────────────


def _sources_hash(refs_path: Path, local_path: Path | None) -> str:
    h = hashlib.sha256()
    h.update(refs_path.read_bytes())
    if local_path and local_path.is_file():
        h.update(b"\x00")
        h.update(local_path.read_bytes())
    return h.hexdigest()


def _is_up_to_date(runtime: Path, scope: rr.ResolvedScope) -> bool:
    sidecar = runtime / SHA_FILENAME
    if not sidecar.is_file():
        return False
    want = _sources_hash(scope.refs_path, scope.local_path)
    try:
        have = sidecar.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return have == want


def _write_sidecar(runtime: Path, scope: rr.ResolvedScope) -> None:
    (runtime / SHA_FILENAME).write_text(
        _sources_hash(scope.refs_path, scope.local_path) + "\n",
        encoding="utf-8",
    )


# ── 5etools shape detection ──────────────────────────────────────────────


def _peek_shape(json_path: Path) -> tuple[str, str | None]:
    """Inspect a 5etools-shaped JSON file's top-level keys and return
    ``(shape, source_id)``.

    ``shape`` is one of:
    * ``adventure_meta`` — ``{adventure: [{id, ...}]}`` (table-of-contents)
    * ``book_meta`` — ``{book: [{id, ...}]}``
    * ``adventure_content`` — ``{data: [...]}`` (per-source content file)
    * ``bestiary`` — ``{monster: [...]}``
    * ``spells`` — ``{spell: [...]}``
    * ``other`` — anything else; symlinked as-is at top level

    ``source_id`` is the source code if we can determine one (from
    ``_meta.title``, filename prefix, or the first entry's ``id``); else ``None``.
    """
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"launch_5etools_mcp: cannot parse {json_path}: {exc}"
        )
    if not isinstance(raw, dict):
        return "other", None

    meta = raw.get("_meta") if isinstance(raw.get("_meta"), dict) else {}
    source_id = meta.get("source") or meta.get("id")

    if "adventure" in raw and isinstance(raw["adventure"], list):
        # Meta TOC. Source from the first entry's id if not in _meta.
        if not source_id and raw["adventure"]:
            source_id = raw["adventure"][0].get("id")
        return "adventure_meta", source_id
    if "book" in raw and isinstance(raw["book"], list):
        if not source_id and raw["book"]:
            source_id = raw["book"][0].get("id")
        return "book_meta", source_id
    if "data" in raw and isinstance(raw["data"], list):
        # Per-source content. Guess source from filename:
        # adventure-<src>.json or book-<src>.json
        stem = json_path.stem
        for prefix in ("adventure-", "book-"):
            if stem.startswith(prefix):
                source_id = source_id or stem[len(prefix):].upper()
        return "adventure_content", source_id
    if "monster" in raw and isinstance(raw["monster"], list):
        stem = json_path.stem
        if stem.startswith("bestiary-"):
            source_id = source_id or stem[len("bestiary-"):].upper()
        return "bestiary", source_id
    if "spell" in raw and isinstance(raw["spell"], list):
        stem = json_path.stem
        if stem.startswith("spells-"):
            source_id = source_id or stem[len("spells-"):].upper()
        return "spells", source_id

    return "other", source_id


# ── Build: canonical data root ───────────────────────────────────────────


def _all_canonical_sources_in_scope(scope: rr.ResolvedScope) -> bool:
    """True when no filtering of the canonical tree is needed."""
    return scope.canonical_mode == "all" and not scope.canonical_excluded


def _build_canonical_data(data_dir: Path, scope: rr.ResolvedScope) -> None:
    canonical_root = scope.roots["fivetools_data"].path

    # Fast path: full canonical view, just symlink.
    if _all_canonical_sources_in_scope(scope):
        data_dir.symlink_to(canonical_root)
        return

    in_scope: set[str] = set(scope.canonical_sources)
    data_dir.mkdir(parents=True)

    # Filter the four source-indexed files.
    _filter_metalist_file(
        canonical_root / "adventures.json",
        data_dir / "adventures.json",
        wrapper_key="adventure",
        in_scope=in_scope,
    )
    _filter_metalist_file(
        canonical_root / "books.json",
        data_dir / "books.json",
        wrapper_key="book",
        in_scope=in_scope,
    )
    (data_dir / "bestiary").mkdir()
    _filter_index_and_symlink(
        canonical_root / "bestiary",
        data_dir / "bestiary",
        in_scope,
    )
    (data_dir / "spells").mkdir()
    _filter_index_and_symlink(
        canonical_root / "spells",
        data_dir / "spells",
        in_scope,
    )

    # adventure/ and book/ subdirs: symlink only in-scope per-source files.
    for subdir, prefix in (("adventure", "adventure-"), ("book", "book-")):
        src_subdir = canonical_root / subdir
        if not src_subdir.is_dir():
            continue
        dst_subdir = data_dir / subdir
        dst_subdir.mkdir(exist_ok=True)
        for f in sorted(src_subdir.iterdir()):
            if not f.name.startswith(prefix) or not f.name.endswith(".json"):
                continue
            src_code = f.stem[len(prefix):].upper()
            # Match canonical-source case-insensitively, since adventures.json
            # uses original-case IDs but filenames are always lowercased.
            in_scope_upper = {s.upper() for s in in_scope}
            if src_code in in_scope_upper:
                (dst_subdir / f.name).symlink_to(f.resolve())

    # Everything else at top level (items.json, races.json, classes/, etc.):
    # symlink as-is. Cross-source files cannot be filtered at this layer.
    skip = {"adventures.json", "books.json", "bestiary", "spells", "adventure", "book"}
    for entry in sorted(canonical_root.iterdir()):
        if entry.name in skip:
            continue
        (data_dir / entry.name).symlink_to(entry.resolve())


def _filter_metalist_file(
    src: Path, dst: Path, *, wrapper_key: str, in_scope: set[str]
) -> None:
    """Filter a 5etools metalist file (adventures.json, books.json).

    Keeps only entries whose ``id`` is in ``in_scope``. Case-sensitive on the
    id field because that matches 5etools' own convention.
    """
    if not src.is_file():
        # Some checkouts may lack one of these; treat as empty.
        dst.write_text(json.dumps({wrapper_key: []}), encoding="utf-8")
        return
    doc = json.loads(src.read_text(encoding="utf-8"))
    entries = doc.get(wrapper_key, []) or []
    doc[wrapper_key] = [e for e in entries if e.get("id") in in_scope]
    dst.write_text(json.dumps(doc, indent="\t"), encoding="utf-8")


def _filter_index_and_symlink(
    src_dir: Path, dst_dir: Path, in_scope: set[str]
) -> None:
    """Filter ``<src_dir>/index.json`` to in-scope sources and symlink the
    corresponding per-source files into ``dst_dir``.
    """
    idx_src = src_dir / "index.json"
    if not idx_src.is_file():
        return
    idx = json.loads(idx_src.read_text(encoding="utf-8"))
    kept: dict[str, str] = {}
    for src_code, filename in idx.items():
        if src_code in in_scope:
            kept[src_code] = filename
            src_file = src_dir / filename
            if src_file.is_file():
                (dst_dir / filename).symlink_to(src_file.resolve())
    (dst_dir / "index.json").write_text(json.dumps(kept, indent="\t"), encoding="utf-8")

    # Also include fluff sidecars when present (fluff-bestiary-<src>.json etc).
    for f in sorted(src_dir.iterdir()):
        if not f.name.startswith("fluff-") or not f.name.endswith(".json"):
            continue
        # fluff-bestiary-mm.json → source code "MM"
        for prefix in ("fluff-bestiary-", "fluff-spells-"):
            if f.name.startswith(prefix):
                code = f.stem[len(prefix):].upper()
                if code in {s.upper() for s in in_scope}:
                    (dst_dir / f.name).symlink_to(f.resolve())
                break


# ── Build: homebrew root ─────────────────────────────────────────────────


def _build_homebrew(
    hb_dir: Path, refs: list[rr.ResolvedRef]
) -> list[dict]:
    """Materialise the campaign's non-canonical refs into a 5etools-style layout.

    Returns a list of ``{note, source_id, kind}`` dicts for every ref that
    resolved to a known source code — used to write ``refs-index.json``.
    """
    hb_dir.mkdir(parents=True)

    # We need to group refs by shape so we can synthesize the right index files.
    adventures_meta: list[dict] = []  # for homebrew/adventures.json
    books_meta: list[dict] = []  # for homebrew/books.json
    bestiary_index: dict[str, str] = {}  # for homebrew/bestiary/index.json
    spells_index: dict[str, str] = {}  # for homebrew/spells/index.json
    refs_index: list[dict] = []

    for ref in refs:
        shape, source_id = _peek_shape(ref.json_path)
        raw = json.loads(ref.json_path.read_text(encoding="utf-8"))
        if shape == "adventure_meta":
            adventures_meta.extend(raw["adventure"])
            # Combined file: adventureData is [{id, source, data: [chapters...]}, ...].
            for ad_entry in raw.get("adventureData") or []:
                src = ad_entry.get("id") or ad_entry.get("source") or source_id
                chapters = ad_entry.get("data") or []
                if src and chapters:
                    adv_dir = hb_dir / "adventure"
                    adv_dir.mkdir(exist_ok=True)
                    (adv_dir / f"adventure-{src.lower()}.json").write_text(
                        json.dumps({"data": chapters}, indent="\t"), encoding="utf-8"
                    )
        elif shape == "book_meta":
            books_meta.extend(raw["book"])
            # Combined file: bookData is [{id, source, data: [chapters...]}, ...].
            # Extract the chapters for each source and write them as separate
            # book/book-<src>.json content files with {data: [chapters...]}.
            for bd_entry in raw.get("bookData") or []:
                src = bd_entry.get("id") or bd_entry.get("source") or source_id
                chapters = bd_entry.get("data") or []
                if src and chapters:
                    book_dir = hb_dir / "book"
                    book_dir.mkdir(exist_ok=True)
                    (book_dir / f"book-{src.lower()}.json").write_text(
                        json.dumps({"data": chapters}, indent="\t"), encoding="utf-8"
                    )
        elif shape == "adventure_content":
            src_code = source_id or ref.json_path.stem
            target = hb_dir / "adventure" / f"adventure-{src_code.lower()}.json"
            target.parent.mkdir(exist_ok=True)
            target.symlink_to(ref.json_path.resolve())
            # If no metadata file existed for this content, synthesize a minimal one.
            if not any(a.get("id") == src_code for a in adventures_meta):
                adventures_meta.append(
                    {"id": src_code, "name": ref.note or src_code, "source": src_code}
                )
        elif shape == "bestiary":
            src_code = source_id or ref.json_path.stem.replace("bestiary-", "").upper()
            filename = f"bestiary-{src_code.lower()}.json"
            (hb_dir / "bestiary").mkdir(exist_ok=True)
            (hb_dir / "bestiary" / filename).symlink_to(ref.json_path.resolve())
            bestiary_index[src_code] = filename
        elif shape == "spells":
            src_code = source_id or ref.json_path.stem.replace("spells-", "").upper()
            filename = f"spells-{src_code.lower()}.json"
            (hb_dir / "spells").mkdir(exist_ok=True)
            (hb_dir / "spells" / filename).symlink_to(ref.json_path.resolve())
            spells_index[src_code] = filename
        else:
            # Unknown shape — drop in a loose/ subdir so the file is at least
            # present, even if no MCP tool surfaces it natively.
            (hb_dir / "loose").mkdir(exist_ok=True)
            (hb_dir / "loose" / ref.json_path.name).symlink_to(ref.json_path.resolve())

        if source_id:
            refs_index.append(
                {"note": ref.note or ref.abstract, "source_id": source_id, "kind": ref.kind}
            )

    # Write the synthesized indices. Always write them — the MCP loader expects
    # adventures.json / books.json at the root.
    (hb_dir / "adventures.json").write_text(
        json.dumps({"adventure": adventures_meta}, indent="\t"), encoding="utf-8"
    )
    (hb_dir / "books.json").write_text(
        json.dumps({"book": books_meta}, indent="\t"), encoding="utf-8"
    )
    if bestiary_index:
        (hb_dir / "bestiary" / "index.json").write_text(
            json.dumps(bestiary_index, indent="\t"), encoding="utf-8"
        )
    if spells_index:
        (hb_dir / "spells" / "index.json").write_text(
            json.dumps(spells_index, indent="\t"), encoding="utf-8"
        )

    return refs_index


# ── Build orchestration ──────────────────────────────────────────────────


REFS_INDEX_FILENAME = "refs-index.json"


def build_runtime_tree(runtime: Path, scope: rr.ResolvedScope) -> None:
    """Build (or rebuild) the per-campaign symlink farm."""
    if _is_up_to_date(runtime, scope):
        return
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    _build_canonical_data(runtime / "data", scope)
    refs_index = _build_homebrew(runtime / "homebrew", scope.refs)
    (runtime / REFS_INDEX_FILENAME).write_text(
        json.dumps(refs_index, indent="\t"), encoding="utf-8"
    )
    _write_sidecar(runtime, scope)


# ── Subcommands ──────────────────────────────────────────────────────────


def cmd_status(scope: rr.ResolvedScope, runtime: Path) -> int:
    print(f"# Refs:    {scope.refs_path}")
    print(f"# Local:   {scope.local_path or '(not present — using defaults)'}")
    print(f"# Runtime: {runtime}")
    print()
    print("# Roots:")
    for name, root in scope.roots.items():
        print(f"  {name:18s} {root.path}  [{root.source}]")
    print()
    print(f"# Canonical: mode={scope.canonical_mode}, {len(scope.canonical_sources)} source(s) in scope")
    if scope.canonical_excluded:
        print(f"# Excluded:  {', '.join(scope.canonical_excluded)}")
    print()
    print(f"# Refs: {len(scope.refs)} entry/entries")
    for i, ref in enumerate(scope.refs, start=1):
        note = f"  ({ref.note})" if ref.note else ""
        print(f"  [{i}] {ref.kind:18s} {ref.json_path}{note}")
    return 0


def cmd_dry_run(scope: rr.ResolvedScope, runtime: Path) -> int:
    cmd_status(scope, runtime)
    print()
    print(f"# Would build runtime tree at: {runtime}")
    print(f"# Would exec MCP with DATA_DIRS={runtime}/data:{runtime}/homebrew")
    return 0


def cmd_init_local(campaign_dir: Path) -> int:
    local_path = campaign_dir / rr.LOCAL_FILENAME
    if local_path.exists():
        raise SystemExit(
            f"launch_5etools_mcp: {local_path} already exists. "
            f"Delete it first if you want to regenerate."
        )
    body = {
        "roots": {
            "fivetools_data": str(rr._DEFAULT_ROOTS["fivetools_data"]),
            "rpg_library": "",  # Intentionally blank — varies per machine.
            "homebrew_private": str(rr._DEFAULT_ROOTS["homebrew_private"]),
        }
    }
    text = (
        "# Per-machine root paths for this campaign. Git-ignored.\n"
        "# Fill in rpg_library with the absolute path to your rpg-lib scan root\n"
        "# (the same path you'd set as RPG_LIBRARY_ROOT for rpg-lib itself).\n\n"
        + yaml.safe_dump(body, sort_keys=False)
    )
    local_path.write_text(text, encoding="utf-8")
    print(f"Wrote starter {local_path}. Edit it to set rpg_library.")
    return 0


def cmd_apply(
    scope: rr.ResolvedScope,
    runtime: Path,
    mcp_index: Path,
    extra_env: dict[str, str],
    *,
    no_exec: bool = False,
) -> int:
    build_runtime_tree(runtime, scope)
    env = os.environ.copy()
    env["DATA_DIRS"] = f"{runtime / 'data'}:{runtime / 'homebrew'}"
    env["CAMPAIGN_DIR"] = str(scope.refs_path.parent)
    env["REFS_INDEX"] = str(runtime / REFS_INDEX_FILENAME)
    env.update(extra_env)
    if no_exec:
        print(f"# Runtime built at {runtime}")
        print(f"# DATA_DIRS={env['DATA_DIRS']}")
        print(f"# CAMPAIGN_DIR={env['CAMPAIGN_DIR']}")
        print(f"# Would exec: node {mcp_index}")
        return 0
    if not mcp_index.is_file():
        raise SystemExit(
            f"launch_5etools_mcp: MCP entry point not found at {mcp_index}. "
            f"Set --mcp-index or check your 5etools-kostadis checkout."
        )
    os.execvpe("node", ["node", str(mcp_index)], env)
    return 0  # unreachable


# ── CLI ──────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None,
    )
    parser.add_argument(
        "--campaign-dir",
        type=Path,
        default=Path.cwd(),
        help="Campaign workspace containing refs.yaml. Default: CWD.",
    )
    parser.add_argument(
        "--mcp-index",
        type=Path,
        default=DEFAULT_MCP_INDEX,
        help=f"Path to the 5etools MCP server's index.js. Default: {DEFAULT_MCP_INDEX}",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the resolved scope and exit. No build, no exec.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved scope + the build plan + the exec env. Do not build or exec.",
    )
    parser.add_argument(
        "--no-exec",
        action="store_true",
        help="Build the runtime tree but do not exec the MCP server. Useful for testing.",
    )
    parser.add_argument(
        "--init-local",
        action="store_true",
        help="Write a starter refs.local.yaml with detected defaults. Refuses to overwrite.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.init_local:
        return cmd_init_local(args.campaign_dir)

    scope = rr.resolve(args.campaign_dir)
    runtime = runtime_dir_for(args.campaign_dir)

    if args.status:
        return cmd_status(scope, runtime)
    if args.dry_run:
        return cmd_dry_run(scope, runtime)

    return cmd_apply(scope, runtime, args.mcp_index, {}, no_exec=args.no_exec)


if __name__ == "__main__":
    sys.exit(main())
