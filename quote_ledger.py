"""Quote Ledger — SQLite-backed tracking of VTT roleplay quotes and their scene assignments.

Parses roleplay extraction files (from vtt_summary.py) and scene extraction files
(from session_doc.py Pass 4), cross-references them via fuzzy matching, and stores
assignments in a local SQLite database.
"""

import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

# ── Parsing ──────────────────────────────────────────────────────────────────

_ROLEPLAY_BLOCK_RE = re.compile(
    r'\*\*([^*]+)\*\*\s*[—–-]\s*\*([^*]+)\*\s*\n((?:>\s*.+\n?)+)',
    re.MULTILINE,
)

_SCENE_DIALOGUE_RE = re.compile(
    r'^([A-Z][^:\n]+):\s*"(.+)"$',
    re.MULTILINE,
)


def parse_roleplay_quotes(text: str, source_file: str) -> list[dict]:
    """Parse a roleplay extraction file into individual quote blocks.

    Returns a list of dicts with keys:
        source_file, block_index, speaker, character, context, quote_text
    """
    quotes: list[dict] = []
    for i, m in enumerate(_ROLEPLAY_BLOCK_RE.finditer(text)):
        speaker = m.group(1).strip()
        context = m.group(2).strip()
        raw_lines = m.group(3).strip().splitlines()
        quote_text = "\n".join(
            line.lstrip(">").strip().strip('"').strip('"').strip('"')
            for line in raw_lines
        )
        # Extract character name from speaker like "GM as Brewbarry" or "kostadis1 as Vukradin"
        char_match = re.search(r'\bas\s+(\w+)', speaker, re.IGNORECASE)
        character = char_match.group(1) if char_match else speaker

        quotes.append({
            "source_file": source_file,
            "block_index": i,
            "speaker": speaker,
            "character": character,
            "context": context,
            "quote_text": quote_text,
        })
    return quotes


def parse_scene_dialogue(text: str) -> list[tuple[str, str]]:
    """Extract (speaker, quote_text) pairs from a scene extraction file."""
    return _SCENE_DIALOGUE_RE.findall(text)


# ── Normalization & Matching ─────────────────────────────────────────────────

def normalize_quote(text: str) -> str:
    """Lowercase, strip quotes/punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r'["""\'\'\u2018\u2019\u201c\u201d]', '', text)
    text = re.sub(r'[,;:!?…—–\-\(\)\.]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def match_quote(roleplay_norm: str, scene_norm: str) -> float:
    """Return similarity ratio between a roleplay quote and a scene dialogue line."""
    return SequenceMatcher(None, roleplay_norm, scene_norm).ratio()


def first_n_words(text: str, n: int = 8) -> str:
    """Return the first n words of text, for fallback matching."""
    return " ".join(text.split()[:n])


# ── SQLite Schema ────────────────────────────────────────────────────────────

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS quote (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    speaker     TEXT NOT NULL,
    character   TEXT NOT NULL,
    context     TEXT NOT NULL,
    quote_text  TEXT NOT NULL,
    quote_norm  TEXT NOT NULL,
    scene_index INTEGER,
    pinned      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_file, block_index)
);
CREATE INDEX IF NOT EXISTS idx_quote_scene ON quote(scene_index);
CREATE INDEX IF NOT EXISTS idx_quote_norm  ON quote(quote_norm);
"""


# ── QuoteLedger ──────────────────────────────────────────────────────────────

class QuoteLedger:
    """SQLite-backed quote tracking and scene assignment."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ── Population ───────────────────────────────────────────────────

    def sync(self, roleplay_dir: Path, extract_dir: Path,
             scenes: list[dict]) -> dict:
        """Parse extraction files, populate DB, match quotes to scenes.

        Returns {total, matched, unassigned}.
        """
        # Step 1: Insert/update roleplay quotes
        self._ingest_roleplay(roleplay_dir)

        # Step 2: Match un-pinned quotes to scenes
        self._match_to_scenes(extract_dir, scenes)

        # Step 3: Return summary
        total = self._scalar("SELECT COUNT(*) FROM quote")
        matched = self._scalar("SELECT COUNT(*) FROM quote WHERE scene_index IS NOT NULL")
        return {"total": total, "matched": matched, "unassigned": total - matched}

    def _ingest_roleplay(self, roleplay_dir: Path) -> None:
        """Parse all roleplay extraction files and upsert into DB."""
        for f in sorted(roleplay_dir.glob("extract_*.md")):
            text = f.read_text(encoding="utf-8")
            quotes = parse_roleplay_quotes(text, f.name)
            for q in quotes:
                norm = normalize_quote(q["quote_text"])
                self.conn.execute(
                    """INSERT INTO quote (source_file, block_index, speaker, character,
                                         context, quote_text, quote_norm)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(source_file, block_index) DO UPDATE SET
                           speaker=excluded.speaker, character=excluded.character,
                           context=excluded.context, quote_text=excluded.quote_text,
                           quote_norm=excluded.quote_norm
                    """,
                    (q["source_file"], q["block_index"], q["speaker"],
                     q["character"], q["context"], q["quote_text"], norm),
                )
        self.conn.commit()

    def _match_to_scenes(self, extract_dir: Path, scenes: list[dict]) -> None:
        """Match un-pinned quotes to scenes by fuzzy-matching against scene extractions."""
        from session_doc import extraction_filename

        for scene in scenes:
            idx = scene["index"]
            fname = extraction_filename(idx, scene["narrator"], scene.get("scene", ""))
            fpath = extract_dir / fname
            if not fpath.exists():
                continue

            text = fpath.read_text(encoding="utf-8")
            scene_lines = parse_scene_dialogue(text)
            if not scene_lines:
                continue

            # Normalize all scene dialogue lines
            scene_norms = [normalize_quote(qt) for _, qt in scene_lines]

            # Get all un-pinned, unassigned quotes (or quotes assigned to this scene)
            candidates = self.conn.execute(
                """SELECT id, quote_norm FROM quote
                   WHERE pinned = 0 AND (scene_index IS NULL OR scene_index = ?)""",
                (idx,),
            ).fetchall()

            for row in candidates:
                qid, qnorm = row["id"], row["quote_norm"]
                best_ratio = 0.0
                for snorm in scene_norms:
                    ratio = match_quote(qnorm, snorm)
                    if ratio > best_ratio:
                        best_ratio = ratio

                # Also try first-8-words fallback
                if best_ratio < 0.6:
                    q_prefix = first_n_words(qnorm)
                    for snorm in scene_norms:
                        if q_prefix in snorm:
                            best_ratio = max(best_ratio, 0.65)
                            break

                if best_ratio >= 0.6:
                    self.conn.execute(
                        "UPDATE quote SET scene_index = ? WHERE id = ? AND pinned = 0",
                        (idx, qid),
                    )

        self.conn.commit()

    # ── Query ────────────────────────────────────────────────────────

    def get_quotes_grouped(self, scenes: list[dict]) -> dict:
        """Return all quotes grouped by scene, plus unassigned.

        Returns {scenes: [{index, narrator, scene_name, quotes: [...]}, ...],
                 unassigned: [...]}
        """
        result_scenes = []
        for s in scenes:
            rows = self.conn.execute(
                """SELECT id, speaker, character, context, quote_text, scene_index, pinned
                   FROM quote WHERE scene_index = ? ORDER BY source_file, block_index""",
                (s["index"],),
            ).fetchall()
            result_scenes.append({
                "index": s["index"],
                "narrator": s["narrator"],
                "scene_name": s.get("scene", ""),
                "quotes": [dict(r) for r in rows],
            })

        unassigned = self.conn.execute(
            """SELECT id, speaker, character, context, quote_text, scene_index, pinned
               FROM quote WHERE scene_index IS NULL ORDER BY source_file, block_index"""
        ).fetchall()

        return {
            "scenes": result_scenes,
            "unassigned": [dict(r) for r in unassigned],
        }

    def assign(self, quote_id: int, scene_index: int | None) -> bool:
        """Reassign a quote to a scene (or unassign with None). Sets pinned=1."""
        cur = self.conn.execute(
            "UPDATE quote SET scene_index = ?, pinned = 1 WHERE id = ?",
            (scene_index, quote_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ── Helpers ──────────────────────────────────────────────────────

    def _scalar(self, sql: str) -> int:
        return self.conn.execute(sql).fetchone()[0]
