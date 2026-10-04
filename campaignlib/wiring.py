"""Read mneme-rendered host wiring from one selected external location."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def default_wiring_path() -> Path:
    return Path.home() / ".config" / "campaigngenerator" / "wiring.yaml"


def selected_wiring_path(explicit: str | os.PathLike | None = None) -> tuple[Path, bool]:
    """Return (path, selected_by_operator) with no checkout/CWD fallback."""
    if explicit:
        return Path(explicit).expanduser(), True
    env = os.environ.get("MNEME_WIRING")
    if env:
        return Path(env).expanduser(), True
    return default_wiring_path(), False


def load_wiring(path: str | os.PathLike | None = None) -> dict:
    """Read the selected YAML mapping; only a missing default is optional."""
    import yaml

    selected, required = selected_wiring_path(path)
    if not selected.is_file():
        if required:
            raise FileNotFoundError(f"selected external wiring file not found: {selected}")
        return {}
    try:
        data = yaml.safe_load(selected.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed external wiring at {selected}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"external wiring at {selected} must be a YAML mapping")
    return data


def assert_no_retired_wiring(source_checkout: str | os.PathLike) -> None:
    """Refuse a known checkout's retired file before normal startup."""
    checkout = Path(source_checkout).expanduser().resolve()
    retired = checkout / "config" / "wiring.yaml"
    if retired.exists():
        raise RuntimeError(
            f"retired wiring remains at {retired}; run "
            f"migrate_wiring --source-checkout {checkout} and update mneme's "
            "CampaignGenerator config_target before starting"
        )


def wiring_get(key: str, default=None):
    """Return one external wiring value (or ``default`` if absent)."""
    return load_wiring().get(key, default)


def wiring_path(key: str) -> Path | None:
    """Return an external wiring value as an expanded path, or None."""
    val = load_wiring().get(key)
    return Path(val).expanduser() if isinstance(val, str) and val else None


def main() -> int:
    """Internal checkout preflight used by ``startup``."""
    parser = argparse.ArgumentParser(description="Check for retired checkout wiring")
    parser.add_argument("--check-retired", required=True, metavar="CHECKOUT")
    args = parser.parse_args()
    try:
        assert_no_retired_wiring(args.check_retired)
    except RuntimeError as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
