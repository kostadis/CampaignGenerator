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
from pathlib import Path

try:  # package import (pytest) vs same-dir script execution
    from pipelines.grounding.event_spine import DEFAULT_STORE, render, update
except ImportError:
    from event_spine import DEFAULT_STORE, render, update


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, nargs="+", metavar="GLOB",
                    help="merged.json glob(s), e.g. 'docs/ensemble/per_chapter/*/merged.json'")
    ap.add_argument("--output", "-o", default="docs/recent_events.md", type=Path,
                    help="Output markdown (default: docs/recent_events.md)")
    ap.add_argument("--window", type=int, default=0,
                    help="Keep only the last N chapters (0 = all)")
    ap.add_argument("--campaign", default=None,
                    help="Campaign label for the header (default: current dir name)")
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE,
                    help=f"Event spine store (default: {DEFAULT_STORE})")
    args = ap.parse_args()

    total, replaced = update(args.corpus, args.store)
    print(f"store {args.store}: {total} rows; replaced chapter(s): "
          f"{', '.join(map(str, replaced))}")
    kept, nch = render(args.store, args.output, args.window, args.campaign)
    print(f"wrote {args.output}: {kept} events across {nch} chapter(s) "
          f"(window={args.window or 'all'})")


if __name__ == "__main__":
    main()
