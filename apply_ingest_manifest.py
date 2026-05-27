"""apply_ingest_manifest.py — replay an ingest_manifest.yaml into a palace.

The MemPalace is a derived store. The *list* of which 5etools / converted-PDF
slices belong in a given campaign palace is the curation work that's
expensive to recreate, so we record it as a YAML manifest checked into the
campaign workspace and replay it with this script.

Manifest shape (lives at ``<campaign-dir>/ingest_manifest.yaml``):

.. code-block:: yaml

    palace: abyss                                 # optional; falls back to
                                                  # config.yaml mempalace.palace
    ingests:
      - source: ~/src/5etools-kostadis/data/adventure/adventure-oota.json
        filter: "chapter=0"
        note: "Velkynvelve opening — session 1 grounding"
      - source: ~/src/5etools-kostadis/data/bestiary/bestiary-oota.json
        filter: "name=Drow Priestess of Lolth"
      - source: ./converted/icespire-homebrew.json
        book_id: 7421
        note: "Homebrew faction, converted 2026-04-20"

Each entry maps 1:1 to a ``fivetools_ingest.py`` invocation. ``source`` is
required; ``filter``, ``book_id``, ``force``, and ``note`` are optional.

Subcommands (flags):

* default — run every entry. Idempotent via the per-(path, palace, filter)
  sidecars that ``fivetools_ingest.py`` writes.
* ``--dry-run`` — print the ``fivetools_ingest.py`` commands without running.
* ``--status`` — report sidecar status per entry (never-run / ingested /
  stale / missing-source). No ingest runs.
* ``--only 1,3,5`` — apply only the listed entries (1-based).
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import yaml

from campaignlib import find_default_config, load_config
from fivetools_ingest import _state_path, file_signature, parse_filter_spec


MANIFEST_FILENAME = "ingest_manifest.yaml"


# ── Loading ──────────────────────────────────────────────────────────────


def load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.is_file():
        raise SystemExit(f"apply_ingest_manifest: {manifest_path} not found")
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SystemExit(f"apply_ingest_manifest: {manifest_path}: {exc}")
    if raw is None:
        raise SystemExit(f"apply_ingest_manifest: {manifest_path} is empty")
    if not isinstance(raw, dict):
        raise SystemExit(
            f"apply_ingest_manifest: {manifest_path}: top level must be a mapping"
        )
    ingests = raw.get("ingests")
    if not isinstance(ingests, list) or not ingests:
        raise SystemExit(
            f"apply_ingest_manifest: {manifest_path}: missing or empty 'ingests:' list"
        )
    for i, entry in enumerate(ingests, start=1):
        if not isinstance(entry, dict):
            raise SystemExit(
                f"apply_ingest_manifest: entry [{i}] must be a mapping, got {type(entry).__name__}"
            )
        if not entry.get("source"):
            raise SystemExit(f"apply_ingest_manifest: entry [{i}] missing 'source'")
    return raw


def resolve_palace(manifest: dict, config: dict | None, cli_palace: str | None) -> str:
    # CLI > manifest > config.yaml. Refuse to guess.
    if cli_palace:
        return cli_palace
    if manifest.get("palace"):
        return str(manifest["palace"])
    if config and isinstance(config.get("mempalace"), dict):
        p = config["mempalace"].get("palace")
        if p:
            return str(p)
    raise SystemExit(
        "apply_ingest_manifest: palace not specified — set 'palace:' in the manifest, "
        "or 'mempalace.palace' in config.yaml, or pass --palace."
    )


def resolve_source(source: str, manifest_dir: Path) -> Path:
    p = Path(source).expanduser()
    if not p.is_absolute():
        p = (manifest_dir / p).resolve()
    return p


# ── Argv construction ────────────────────────────────────────────────────


def build_argv(
    entry: dict,
    palace: str,
    manifest_dir: Path,
    script_dir: Path,
    *,
    dry_run: bool = False,
) -> list[str]:
    source = resolve_source(entry["source"], manifest_dir)
    argv = [
        sys.executable,
        str(script_dir / "fivetools_ingest.py"),
        str(source),
        "--palace",
        palace,
    ]
    if entry.get("filter"):
        argv += ["--filter", str(entry["filter"])]
    if entry.get("book_id") is not None:
        argv += ["--book-id", str(entry["book_id"])]
    if entry.get("force"):
        argv.append("--force")
    if dry_run:
        argv.append("--dry-run")
    return argv


# ── Status ───────────────────────────────────────────────────────────────


def check_status(entry: dict, palace: str, manifest_dir: Path) -> tuple[str, dict | None]:
    """Return (status, prior_state). Status is one of:

    * ``missing-source`` — the JSON named in the manifest doesn't exist.
    * ``never-run`` — no sidecar for this (source, palace, filter) triple.
    * ``ingested`` — sidecar exists and matches current (size, mtime).
    * ``stale`` — sidecar exists but the source has changed since ingest.
    """
    source = resolve_source(entry["source"], manifest_dir)
    if not source.is_file():
        return ("missing-source", None)
    try:
        filters = parse_filter_spec(entry.get("filter"))
    except ValueError as exc:
        raise SystemExit(f"apply_ingest_manifest: {entry['source']}: {exc}")
    filter_key = json.dumps(filters, sort_keys=True)
    sidecar = _state_path(source, palace=palace, filter_key=filter_key)
    if not sidecar.is_file():
        return ("never-run", None)
    try:
        prior = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("never-run", None)
    sig = file_signature(source)
    if (
        prior.get("size") == sig["size"]
        and abs(prior.get("mtime", -1) - sig["mtime"]) < 0.001
    ):
        return ("ingested", prior)
    return ("stale", prior)


# ── Selection ────────────────────────────────────────────────────────────


def parse_only(only_str: str | None, n_entries: int) -> set[int] | None:
    if not only_str:
        return None
    indices: set[int] = set()
    for tok in only_str.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            i = int(tok)
        except ValueError:
            raise SystemExit(
                f"apply_ingest_manifest: --only expects integers, got {tok!r}"
            )
        if i < 1 or i > n_entries:
            raise SystemExit(
                f"apply_ingest_manifest: --only {i} out of range (1..{n_entries})"
            )
        indices.add(i - 1)
    return indices


# ── Run ──────────────────────────────────────────────────────────────────


def _print_header(manifest_path: Path, palace: str, n: int, selected: int) -> None:
    print(f"# Manifest: {manifest_path}")
    print(f"# Palace:   {palace}")
    if selected == n:
        print(f"# Entries:  {n}")
    else:
        print(f"# Entries:  {selected} of {n}")


def _entry_label(entry: dict) -> str:
    note = entry.get("note")
    if note:
        return f"{entry['source']}  ({note})"
    return str(entry["source"])


def cmd_status(manifest: dict, manifest_path: Path, palace: str, only: set[int] | None) -> int:
    entries = manifest["ingests"]
    manifest_dir = manifest_path.parent
    selected = sum(1 for i in range(len(entries)) if only is None or i in only)
    _print_header(manifest_path, palace, len(entries), selected)
    counts: dict[str, int] = {}
    for i, entry in enumerate(entries, start=1):
        if only is not None and (i - 1) not in only:
            continue
        status, prior = check_status(entry, palace, manifest_dir)
        counts[status] = counts.get(status, 0) + 1
        ts = ""
        if prior and prior.get("ingested_at"):
            ts = f"  (last: {prior['ingested_at']})"
        print(f"  [{i}] {status:14s} {_entry_label(entry)}{ts}")
    if counts:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"# Summary:  {summary}")
    return 0 if counts.get("missing-source", 0) == 0 else 2


def cmd_apply(
    manifest: dict,
    manifest_path: Path,
    palace: str,
    only: set[int] | None,
    *,
    dry_run: bool,
) -> int:
    entries = manifest["ingests"]
    manifest_dir = manifest_path.parent
    script_dir = Path(__file__).resolve().parent
    selected = sum(1 for i in range(len(entries)) if only is None or i in only)
    _print_header(manifest_path, palace, len(entries), selected)

    failures = 0
    for i, entry in enumerate(entries, start=1):
        if only is not None and (i - 1) not in only:
            continue
        argv = build_argv(entry, palace, manifest_dir, script_dir, dry_run=dry_run)
        print(f"# [{i}/{len(entries)}] {_entry_label(entry)}")
        print(f"  $ {shlex.join(argv)}")
        if dry_run:
            # We still ask fivetools_ingest to actually do its dry-run work
            # (so the user sees real validation output), but if they only
            # want to see the command, --dry-run-shallow would be a future
            # flag. For now, run the inner --dry-run too.
            pass
        try:
            result = subprocess.run(argv)
        except KeyboardInterrupt:
            print("\napply_ingest_manifest: interrupted", file=sys.stderr)
            return 130
        if result.returncode != 0:
            failures += 1
            print(
                f"  ! entry [{i}] exited with code {result.returncode}",
                file=sys.stderr,
            )
    if failures:
        print(
            f"apply_ingest_manifest: {failures} entry/entries failed",
            file=sys.stderr,
        )
        return 1
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None,
    )
    parser.add_argument(
        "--campaign-dir",
        type=Path,
        default=Path.cwd(),
        help="Workspace containing ingest_manifest.yaml. Default: CWD.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=f"Override path to the manifest. Default: <campaign-dir>/{MANIFEST_FILENAME}.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config.yaml (for fallback palace). Default: campaignlib auto-detection.",
    )
    parser.add_argument(
        "--palace",
        default=None,
        help="Override palace name. Beats both manifest 'palace:' and config.yaml.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print fivetools_ingest.py commands and pass --dry-run to each.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Report sidecar status per entry. No ingest runs.",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated 1-based entry indices (e.g. '1,3,5'). Default: all.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest_path = args.manifest or (args.campaign_dir / MANIFEST_FILENAME)
    manifest = load_manifest(manifest_path)

    config = None
    config_path = args.config or find_default_config(__file__)
    if config_path and Path(config_path).is_file():
        try:
            config, _ = load_config(str(config_path))
        except Exception:
            config = None

    palace = resolve_palace(manifest, config, args.palace)
    only = parse_only(args.only, len(manifest["ingests"]))

    if args.status:
        return cmd_status(manifest, manifest_path, palace, only)
    return cmd_apply(manifest, manifest_path, palace, only, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
