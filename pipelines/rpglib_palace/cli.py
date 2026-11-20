"""rpglib_palace {select,fetch,render,mine,query}. No LLM calls."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from pipelines.rpglib_palace.guard import PalaceGuardError, mine_command, require_pilot_palace

DEFAULT_DB = Path("~/src/mytools/rpg-lib/rpg_library.db")
DEFAULT_SOURCE = Path("/mnt/g/My Drive/DriveThru/Dungeon Masters Guild")
DEFAULT_WORKDIR = Path("~/rpglib-palace")
DEFAULT_CACHE = Path("~/rpglib-cache/dmsguild")


def _dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rpglib_palace")
    ap.add_argument("--workdir", default=str(DEFAULT_WORKDIR))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--db", default=str(DEFAULT_DB))
    s.add_argument("--source-root", default=str(DEFAULT_SOURCE))
    s.add_argument("--limit", type=int, default=50)
    f = sub.add_parser("fetch")
    f.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    sub.add_parser("render")
    sub.add_parser("mine")
    q = sub.add_parser("query")
    q.add_argument("text")
    q.add_argument("--per-book", type=int, default=2)
    q.add_argument("--fetch", type=int, default=50)
    q.add_argument("--top", type=int, default=10)
    q.add_argument("--json", action="store_true")
    return ap


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    work = Path(args.workdir).expanduser()
    manifest, fetched, rendered = work / "manifest.json", work / "fetched.json", work / "rendered"

    if args.cmd == "select":
        from pipelines.rpglib_palace.select import select_books, write_manifest

        books = select_books(
            Path(args.db).expanduser(), Path(args.source_root), limit=args.limit
        )
        write_manifest(books, manifest)
        print(f"selected {len(books)} books -> {manifest}")
        return 0

    if args.cmd == "fetch":
        from pipelines.rpglib_palace.fetch import fetch_all
        from pipelines.rpglib_palace.select import read_manifest

        res = fetch_all(read_manifest(manifest)["books"], Path(args.cache_dir).expanduser())
        fetched.parent.mkdir(parents=True, exist_ok=True)
        fetched.write_text(json.dumps({"books": res}, indent=2), encoding="utf-8")
        counts: dict[str, int] = {}
        for r in res:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        print(f"fetched: {counts} -> {fetched}")
        return 0

    if args.cmd == "render":
        from pipelines.rpglib_palace.render import render_book, write_palace_layout
        from pipelines.rpglib_palace.select import read_manifest

        books = [b for b in read_manifest(fetched)["books"] if b["status"] != "missing"]
        records, laid_out = [], []
        for b in books:
            bj = json.loads(Path(b["cache_path"]).read_text(encoding="utf-8"))
            recs = render_book(b, bj, rendered)
            if recs:
                records += recs
                laid_out.append(b)
            else:
                print(f"skipped (no sections): book {b['book_id']} {b['title']}", file=sys.stderr)
        write_palace_layout(rendered, records, laid_out)
        print(f"rendered {len(records)} sections from {len(laid_out)} books -> {rendered}")
        return 0

    if args.cmd == "mine":
        try:
            palace = require_pilot_palace()
        except PalaceGuardError as e:
            print(f"rpglib_palace: {e}", file=sys.stderr)
            raise SystemExit(2)
        t0 = time.time()
        subprocess.run(mine_command(rendered, palace), env=os.environ, check=True)
        print(f"mine elapsed: {time.time() - t0:.1f}s; palace bytes: {_dir_bytes(palace)}")
        return 0

    if args.cmd == "query":
        from pipelines.rpglib_palace.query import format_human, run_query

        try:
            palace = require_pilot_palace()
        except PalaceGuardError as e:
            print(f"rpglib_palace: {e}", file=sys.stderr)
            raise SystemExit(2)
        out = run_query(
            args.text, palace, rendered, fetch=args.fetch, per_book=args.per_book, top=args.top
        )
        print(json.dumps(out, indent=2) if args.json else format_human(out))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
