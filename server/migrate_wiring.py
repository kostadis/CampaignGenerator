"""Deliberately move mneme wiring out of an old CampaignGenerator checkout."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import yaml

from campaignlib.wiring import default_wiring_path


KNOWN_KEYS = {
    "dgx_endpoint", "dgx_model", "rpg_library_url", "fivetools_data_root",
    "fivetools_mcp_index", "rpg_library_db", "pdf_translators", "homebrew_private",
}


def migrate_wiring(
    source_checkout: str | Path, target: str | Path | None = None, *, force: bool = False
) -> Path:
    """Validate raw YAML, write the target safely, then remove the source."""
    checkout = Path(source_checkout).expanduser().resolve()
    source = checkout / "config" / "wiring.yaml"
    destination = Path(target).expanduser() if target is not None else default_wiring_path()
    if not source.is_file():
        raise FileNotFoundError(f"retired wiring file not found: {source}")
    if source.resolve() == destination.resolve():
        raise ValueError(f"source and target are the same file: {source}")
    raw = source.read_bytes()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed retired wiring at {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"retired wiring at {source} must be a YAML mapping")
    if destination.exists() and not force:
        raise FileExistsError(
            f"target already exists: {destination}; inspect both files, then use --force to replace"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".wiring-", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    source.unlink()
    unknown = sorted(str(key) for key in data if key not in KNOWN_KEYS)
    print(f"Moved external wiring: {source} -> {destination}")
    if unknown:
        print(f"Preserved unrecognised keys: {', '.join(unknown)}")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-checkout", required=True, metavar="DIR")
    parser.add_argument("--target", metavar="PATH")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        migrate_wiring(args.source_checkout, args.target, force=args.force)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
