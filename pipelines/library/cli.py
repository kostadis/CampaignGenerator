"""``library`` CLI. No LLM calls; all palace access via mempalace_client.

Subcommands: build, refresh, search, status, verify-citation.
"""

from __future__ import annotations

import argparse
import json
import sys

from pipelines.library import ExitCode, LibraryError
from pipelines.library.config import load_library_config


def _client(config):
    from pipelines.rlm.mempalace_client import LibraryPalaceClient

    return LibraryPalaceClient(config.palace, config.env)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="library")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="full build from the declared selection")
    b.add_argument("--json", action="store_true")
    s = sub.add_parser("search", help="whole-section search")
    s.add_argument("text")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--per-book", type=int, default=2)
    s.add_argument("--json", action="store_true")
    r = sub.add_parser("refresh", help="re-process only changed/added/removed books")
    r.add_argument("--json", action="store_true")
    st = sub.add_parser("status", help="health check")
    st.add_argument("--json", action="store_true")
    v = sub.add_parser("verify-citation", help="check a quote appears verbatim in a passage")
    v.add_argument("file")
    v.add_argument("quote")
    v.add_argument("--json", action="store_true")
    return ap


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0) and ExitCode.USAGE
    try:
        config = load_library_config()
        if args.cmd == "build":
            from pipelines.library.build import build

            rep = build(config, client=_client(config)).to_dict()
            print(json.dumps(rep, indent=2) if args.json else
                  f"built: {rep['indexed']}/{rep['selected']} books, {rep['passages']} passages, "
                  f"{len(rep['skipped'])} skipped, {len(rep['failed'])} failed, {rep['elapsed_s']}s")
            return ExitCode.OK
        if args.cmd == "refresh":
            from pipelines.library.build import refresh

            rep = refresh(config, client=_client(config)).to_dict()
            print(json.dumps(rep, indent=2) if args.json else
                  f"refreshed: changed {rep['changed']}, removed {rep['removed']}, "
                  f"{rep['indexed']} books / {rep['passages']} passages, "
                  f"{len(rep['skipped'])} skipped, {len(rep['failed'])} failed, {rep['elapsed_s']}s")
            return ExitCode.OK
        if args.cmd == "search":
            from pipelines.library.search import format_human, search_library

            out = search_library(
                config, args.text, limit=args.limit, per_book=args.per_book, client=_client(config)
            )
            print(json.dumps(out.to_dict(), indent=2) if args.json else format_human(out))
            return ExitCode.OK
        if args.cmd == "status":
            from pipelines.library.status import status

            s = status(config)
            if args.json:
                print(json.dumps(s, indent=2))
            else:
                print(f"configured: yes, built: {'yes' if s['built'] else 'no'}, books: {s['books']}, "
                      f"stale: {len(s['stale'])}, embedder match: {s['embedder_match']}, "
                      f"palace: {s['palace']}, index bytes: {s['index_bytes']}")
            if not s["built"]:
                print("library: not built; run `library build` (hypostasis setup builds it)", file=sys.stderr)
                return int(ExitCode.NOT_BUILT)
            if s["embedder_match"] is False:
                print("library: embedder mismatch; restore env: in hypostasis.yaml or `library build`",
                      file=sys.stderr)
                return int(ExitCode.EMBEDDER_MISMATCH)
            return int(ExitCode.OK)
        if args.cmd == "verify-citation":
            from pipelines.library.verify import verify_citation

            out = verify_citation(config.work_dir, args.file, args.quote)
            print(json.dumps(out) if args.json else
                  (f"found at offset {out['offset']}" if out["found"] else "NOT FOUND"))
            return int(ExitCode.OK if out["found"] else ExitCode.FAILED)
    except LibraryError as e:
        print(f"library: {e}", file=sys.stderr)
        return int(e.exit_code)
    except Exception as e:
        print(f"library: failed: {e}", file=sys.stderr)
        return int(ExitCode.FAILED)
    return int(ExitCode.USAGE)


if __name__ == "__main__":
    raise SystemExit(main())
