"""Copy each book's sidecar into a local cache (re-runnable)."""

from __future__ import annotations

import shutil
from pathlib import Path


def fetch_all(books: list[dict], cache_dir: Path) -> list[dict]:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for b in books:
        src = Path(b["sidecar_path"])
        dst = cache_dir / f"{b['book_id']}.json"
        rec = dict(b, cache_path=str(dst), bytes=0, src_mtime=0.0)
        try:
            st = src.stat()
        except OSError:
            rec["status"] = "missing"
            out.append(rec)
            continue
        rec["bytes"], rec["src_mtime"] = st.st_size, st.st_mtime
        if dst.is_file() and dst.stat().st_size == st.st_size and dst.stat().st_mtime == st.st_mtime:
            rec["status"] = "cached"
        else:
            try:
                shutil.copy2(src, dst)
                rec["status"] = "copied"
            except OSError:
                rec["status"] = "missing"
        out.append(rec)
    return out
