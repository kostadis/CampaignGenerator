#!/usr/bin/env python3
"""Event spine: a durable per-chapter event store + its renders (#213 Phase 2).

`build_recent_events.py` rendered `recent_events.md` straight from the
per-chapter corpora — a per-run derivation with no durable state. This tool
promotes the events to a **store** (`docs/ensemble/events.jsonl`, one JSON
object per line) and demotes the markdown to a **projection** of it.

Why a store and not a render:

- The corpora under `per_chapter/` are gitignored intermediates; the spine
  survives them. A chapter's rows are replaced only when that chapter's
  `merged.json` is present in an `update` — chapters absent from the input
  keep their rows untouched. Nothing here is ever hand-edited; the store is
  derived-but-durable, and any chapter can be rebuilt from its corpus.
- Rows carry the key the anchor requires — `(chapter, scene, seq)` — plus
  quote provenance and the Phase-1 source lineage, so downstream projections
  (recent_events.md today, campaign_state's recent window next) render from
  verified structure instead of re-deriving order from prose.

Deterministic; zero model calls.

Usage (from inside a campaign dir):

  event_spine.py update --corpus 'docs/ensemble/per_chapter/*/merged.json'
  event_spine.py render --output docs/recent_events.md --window 4
"""
import argparse
import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from campaignlib.constants import config_path
from campaignlib.projection_config import (
    PROJECTION_CONFIG_FILENAME,
    load_projection_config,
)

# table/OOC chatter, not in-world events (VTT/Zoom recaps capture table talk)
OOC = re.compile(
    r"discord|spreadsheet|action economy|rpgbot|reference guide|audio|"
    r"claude-based|name generator|next session|pinned|initiative of|"
    r"rolled (a |an )?\d|roll(ed)? (of |totaled )|disadvantage|advantage on|"
    r"armor class of|saving throw mechanic",
    re.I,
)

# chapter index from the per-chapter dir/file name (chapter_02_*, session_001_*, ch3, gen-ch5, ...)
CHAP = re.compile(r"(?:chapter|session|ch|gen-ch)[_-]?0*(\d+)", re.I)


def chapter_of(path: str) -> int:
    # prefer an explicit chapter/session token; fall back to the last number in the path
    for seg in reversed(Path(path).parts):
        m = CHAP.search(seg)
        if m:
            return int(m.group(1))
    nums = re.findall(r"\d+", path)
    return int(nums[-1]) if nums else 99


def _dedup_key(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower())[:60]


def rows_from_corpus(corpus_file: Path) -> list[dict]:
    """Deterministic event rows for one chapter's merged.json."""
    chapter = chapter_of(str(corpus_file))
    rows, seen = [], set()
    for fa in json.loads(corpus_file.read_text(encoding="utf-8")):
        if fa.get("type") != "event":
            continue
        text = (fa.get("fact") or "").strip()
        if not text or OOC.search(text):
            continue
        key = _dedup_key(text)
        if key in seen:
            continue
        seen.add(key)
        row = {
            "chapter": chapter,
            "scene": fa.get("scene_index"),
            "seq": fa.get("quote_offset"),
            "event": text,
            "quote": (fa.get("source_quote") or "") if fa.get("quote_verified") else "",
        }
        if fa.get("source"):
            row["source"] = fa["source"]
        rows.append(row)
    rows.sort(key=_row_order)
    return rows


def _row_order(r: dict) -> tuple:
    return (
        r.get("chapter", 99),
        r.get("scene") if r.get("scene") is not None else 10**6,
        r.get("seq") if r.get("seq") is not None else 10**12,
        r.get("event", ""),
    )


def load_store(store: Path) -> list[dict]:
    if not store.exists():
        return []
    rows = []
    for line in store.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def save_store(store: Path, rows: list[dict]) -> None:
    rows = sorted(rows, key=_row_order)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8")


def update(corpus_globs: list[str], store: Path) -> tuple[int, list[int]]:
    """Replace rows for every chapter present in the corpus; keep the rest."""
    files = sorted({f for g in corpus_globs for f in glob.glob(g)})
    if not files:
        raise SystemExit(f"no files matched: {corpus_globs}")
    fresh: dict[int, list[dict]] = defaultdict(list)
    for f in files:
        for row in rows_from_corpus(Path(f)):
            fresh[row["chapter"]].append(row)
    kept = [r for r in load_store(store) if r.get("chapter") not in fresh]
    rows = kept + [r for ch in fresh for r in fresh[ch]]
    save_store(store, rows)
    return len(rows), sorted(fresh)


def render(store: Path, output: Path, window: int, campaign: str | None) -> tuple[int, int]:
    rows = load_store(store)
    by_chap: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_chap[r.get("chapter", 99)].append(r)
    chapters = sorted(by_chap)
    if window and len(chapters) > window:
        chapters = chapters[-window:]

    campaign = campaign or Path.cwd().name
    window_line = (
        f"_Window: {'all chapters' if not window else f'last {window} chapters'} "
        f"(chapters {chapters[0]}–{chapters[-1]})._" if chapters else "_No events._"
    )
    lines = [
        f"# Recent Events — {campaign} (short-term world state)",
        "",
        "_Projection of `docs/ensemble/events.jsonl` (the event spine) rendered by",
        "`event_spine.py` — full-fidelity, chapter-ordered, **not** synthesised",
        "(synthesis drops low-persistence facts). The long-term, persistence-filtered",
        "view is `docs/world_state.md`; this is the \"what happened in chapter N\"",
        "companion. Update the store after each extraction; regenerate this render",
        "freely — edit neither by hand._",
        "",
        window_line,
        "",
    ]
    for c in chapters:
        lines.append(f"## Chapter {c}" if c != 99 else "## Unanchored")
        lines.append("")
        lines.extend(f"- {r['event']}" for r in sorted(by_chap[c], key=_row_order))
        lines.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sum(len(by_chap[c]) for c in chapters), len(chapters)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("update", help="Replace store rows for chapters present in the corpus")
    up.add_argument("--corpus", required=True, nargs="+", metavar="GLOB")
    up.add_argument("--store", type=Path, default=None,
                    help="Event spine store (default: config stores.events)")

    rd = sub.add_parser("render", help="Render recent_events.md from the store")
    rd.add_argument("--store", type=Path, default=None,
                    help="Event spine store (default: config stores.events)")
    rd.add_argument("--output", "-o", type=Path, default=None,
                    help="Output markdown (default: config output.recent_events)")
    rd.add_argument("--window", type=int, default=0,
                    help="Keep only the last N chapters (0 = all)")
    rd.add_argument("--campaign", default=None)

    args = ap.parse_args()
    # Loaded once, before any work begins (contracts/cli.md's resolution
    # rule) — an explicit --store/--output always wins; a None sentinel
    # resolves from projections.yaml. `--window` has no config counterpart
    # here (only build_recent_events' persistent window does — research
    # D15), so it keeps its own literal default.
    cfg = load_projection_config(config_path(Path.cwd(), PROJECTION_CONFIG_FILENAME))
    store = args.store if args.store is not None else Path(cfg.stores.events)
    if args.cmd == "update":
        total, replaced = update(args.corpus, store)
        print(f"store {store}: {total} rows; replaced chapter(s): "
              f"{', '.join(map(str, replaced))}")
    else:
        output = args.output if args.output is not None else Path(cfg.output.recent_events)
        kept, nch = render(store, output, args.window, args.campaign)
        print(f"wrote {output}: {kept} events across {nch} chapter(s) "
              f"(window={args.window or 'all'})")


if __name__ == "__main__":
    main()
