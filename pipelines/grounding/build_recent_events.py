#!/usr/bin/env python3
"""Generate recent_events.md — now via the event spine store (#213 Phase 2).

This used to render markdown straight from the per-chapter corpora, a
per-run derivation with no durable state. It is now a compatibility wrapper
over `event_spine.py`: the corpus updates the durable store
(`docs/ensemble/events.jsonl` — chapters present are replaced, chapters
absent keep their rows), and the markdown is rendered as a projection of
the store. Same CLI as before; the store path is the only new knob.

Run from inside a campaign dir:

  build_recent_events \
      --corpus 'docs/ensemble/per_chapter/*/merged.json' \
      --output docs/recent_events.md \
      --window 0            # 0 = all chapters; N = keep only the last N
"""
import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from campaignlib.constants import config_path
from campaignlib.projection_config import (
    PROJECTION_CONFIG_FILENAME,
    load_projection_config,
)

try:  # package import (pytest) vs same-dir script execution
    from pipelines.grounding.event_spine import render, update
except ImportError:
    from event_spine import render, update


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, nargs="+", metavar="GLOB",
                    help="merged.json glob(s), e.g. 'docs/ensemble/per_chapter/*/merged.json'")
    ap.add_argument("--output", "-o", default=None, type=Path,
                    help="Output markdown (default: config output.recent_events)")
    ap.add_argument("--window", type=int, default=None,
                    help="Keep only the last N chapters (default: config "
                         "output.recent_events_window; 0 = all)")
    ap.add_argument("--campaign", default=None,
                    help="Campaign label for the header (default: current dir name)")
    ap.add_argument("--store", type=Path, default=None,
                    help="Event spine store (default: config stores.events)")
    args = ap.parse_args()

    # Loaded once, before any work begins (contracts/cli.md's resolution
    # rule) — an explicit flag always wins. This wrapper moved here from
    # Dossier Synthesis (research D15): its --store now resolves from THIS
    # service's document, so its route/settings had to move with it rather
    # than leave a Dossier Synthesis route reading projections.yaml.
    cfg = load_projection_config(config_path(Path.cwd(), PROJECTION_CONFIG_FILENAME))
    output = args.output if args.output is not None else Path(cfg.output.recent_events)
    window = args.window if args.window is not None else cfg.output.recent_events_window
    store = args.store if args.store is not None else Path(cfg.stores.events)

    total, replaced = update(args.corpus, store)
    print(f"store {store}: {total} rows; replaced chapter(s): "
          f"{', '.join(map(str, replaced))}")
    kept, nch = render(store, output, window, args.campaign)
    print(f"wrote {output}: {kept} events across {nch} chapter(s) "
          f"(window={window or 'all'})")


if __name__ == "__main__":
    main()
