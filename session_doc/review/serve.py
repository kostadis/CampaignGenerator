"""Serve the gap reviewer and take its saves — issue #455.

Replaces the clipboard. The page is served from the machine that holds the
campaign, and it PUTs each change straight to `<narration>.authored.yaml`, so:

- nothing is copied by hand, and the charset corruption that mangled every em
  dash on the first real review cannot happen (every response here declares
  `charset=utf-8`, which `python -m http.server` does not)
- persistence is a file on disk rather than `localStorage`, whose behaviour
  under `file://` is inconsistent across mobile browsers
- the rulings are readable by everything else immediately

**This is a face, not an engine.** Saving goes through
`session_doc.review.records.save_record`, the same function `sd_review apply`
calls. A route that wrote YAML itself would be the second implementation this
repo keeps paying for (Principle VI).

**No model is reachable from here**, and `tests/test_block_model_no_llm.py`
walks the AST to keep it that way.

Bind address is deliberate: the point is to reach it from a phone, so it
listens on all interfaces. Everything it serves is one campaign's prose, and it
holds no credential — but it is unauthenticated, so it is meant for a tailnet
or a home LAN and it says so when it starts.
"""

from __future__ import annotations

import json
import re
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from session_doc.authored import AuthoredError, load_record_for, record_path
from session_doc.review.export import build_export
from session_doc.review.records import SaveRefused, review_to_record, save_record, summarise

PAGE = Path(__file__).parent / "reviewer.html"

#: Narrations, excluding the two generated variants beside them.
_SCENE_GLOB = "session_doc_scene_*.md"
_GENERATED = (".composed.md", ".scrubbed.md")

#: One path segment, no traversal. Everything served is addressed by a
#: narration stem, and a stem is matched against what is actually on disk
#: rather than joined onto a path.
_STEM = re.compile(r"^[A-Za-z0-9._-]+$")


def narrations(directory: Path) -> list[Path]:
    return [p for p in sorted(directory.glob(_SCENE_GLOB))
            if not p.name.endswith(_GENERATED)]


def _find_extraction(narration: Path) -> Path | None:
    """Matched on scene number, never title — see `sd_review._find_extraction`."""
    number = next((p for p in narration.stem.split("_") if p.isdigit()), None)
    if number is None:
        return None
    for candidate in (narration.parent.parent / "scene_extractions_smoothed",
                      narration.parent.parent / "scene_extractions",
                      narration.parent):
        if candidate.is_dir():
            hits = sorted(candidate.glob(f"{number}_*.md"))
            if len(hits) == 1:
                return hits[0]
    return None


class Handler(BaseHTTPRequestHandler):
    directory: Path

    server_version = "gap-reviewer"

    # ── plumbing ───────────────────────────────────────────────────────────

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        # charset, always. Its absence is what let a phone browser guess
        # Windows-1252 and corrupt every em dash in a scene.
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        # ensure_ascii for the same reason the export uses it: this travels to a
        # phone and the channel has already been shown to mangle multi-byte text.
        self._send(code, (json.dumps(payload, ensure_ascii=True) + "\n").encode(),
                   "application/json")

    def _resolve(self, stem: str) -> Path | None:
        if not _STEM.match(stem):
            return None
        return next((p for p in narrations(self.directory) if p.stem == stem), None)

    def log_message(self, fmt, *args):        # quieter than the default
        if self.command != "GET":
            super().log_message(fmt, *args)

    # ── routes ─────────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._send(200, self._index().encode(), "text/html")
        if path == "/reviewer.html":
            return self._send(200, PAGE.read_bytes(), "text/html")
        if path.startswith("/scene/") and path.endswith(".json"):
            stem = path[len("/scene/"):-len(".json")]
            narration = self._resolve(stem)
            if narration is None:
                return self._json(404, {"error": f"no narration named {stem!r}"})
            export = build_export(
                narration_path=narration,
                narration_text=narration.read_text(encoding="utf-8"),
                extraction_text=(_find_extraction(narration).read_text(encoding="utf-8")
                                 if _find_extraction(narration) else ""))
            return self._json(200, json.loads(export.model_dump_json()))
        if path.startswith("/record/"):
            narration = self._resolve(path[len("/record/"):])
            if narration is None:
                return self._json(404, {"error": "unknown scene"})
            try:
                record = load_record_for(narration)
            except AuthoredError as exc:
                return self._json(409, {"error": str(exc)})
            if record is None:
                return self._json(404, {"error": "no record yet"})
            return self._json(200, json.loads(record.model_dump_json(exclude_none=True)))
        self._json(404, {"error": "not found"})

    def do_PUT(self) -> None:
        path = unquote(urlparse(self.path).path)
        if not path.startswith("/record/"):
            return self._json(404, {"error": "not found"})
        narration = self._resolve(path[len("/record/"):])
        if narration is None:
            return self._json(404, {"error": "unknown scene"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            return self._json(400, {"error": f"unreadable body: {exc}"})

        try:
            record = review_to_record(payload)
        except AuthoredError as exc:
            return self._json(422, {"error": str(exc)})

        current = narration.read_text(encoding="utf-8")
        from session_doc.review.export import digest
        if record.generated_sha256 != digest(current):
            # The narration changed under the review. Saving would produce a
            # record `sd_compose` must refuse anyway; better to say so now,
            # while the GM still has their rulings on screen.
            return self._json(409, {
                "error": "this review was made against a different draft of "
                         f"{narration.name}; reload the scene",
            })
        try:
            written, _lost = save_record(narration, record)
        except SaveRefused as exc:
            return self._json(409, {"error": str(exc)})
        except OSError as exc:
            return self._json(500, {"error": f"cannot write {record_path(narration)}: {exc}"})
        return self._json(200, {"saved": written.name, "summary": summarise(record)})

    # ── the index ──────────────────────────────────────────────────────────

    def _index(self) -> str:
        rows = []
        for narration in narrations(self.directory):
            try:
                record = load_record_for(narration)
            except AuthoredError:
                record = None
            note = summarise(record) if record else "not reviewed"
            rows.append(
                f'<a href="/reviewer.html?scene={narration.stem}">'
                f"{narration.stem}<b>{note}</b></a>")
        listing = "\n".join(rows) or "<p>No narrations in this directory.</p>"
        return f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Gap reviewer</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;margin:0;padding:1.6rem 1.1rem;max-width:34rem}}
a{{display:block;padding:.85rem 1rem;margin:.5rem 0;border:1px solid #ccc;border-radius:4px;
text-decoration:none;color:#111}}b{{display:block;font-size:.8rem;color:#666;font-weight:400}}
h1{{font-size:1.1rem}}p{{color:#666;font-size:.85rem}}</style>
<h1>Scenes to review</h1>
<p>Rulings save to disk as you make them. Nothing to copy.</p>
{listing}"""


def serve(directory: Path, port: int, host: str = "0.0.0.0") -> None:
    handler = partial(Handler)
    Handler.directory = directory
    httpd = ThreadingHTTPServer((host, port), handler)
    count = len(narrations(directory))
    print(f"Serving {count} scene(s) from {directory}")
    print(f"  http://<this machine>:{port}/")
    print("  Rulings save straight to <scene>.authored.yaml — no copy-paste.")
    print("  UNAUTHENTICATED: anyone who can reach this port can read and write "
          "the review. Intended for a tailnet or a home LAN.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
