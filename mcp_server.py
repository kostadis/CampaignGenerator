"""MCP server for CampaignGenerator — read campaign data, draft notes, run prep tools.

Usage:
    CAMPAIGN_DIR=/path/to/campaign python mcp_server.py
    python mcp_server.py --campaign-dir /path/to/campaign

Register per-campaign via .mcp.json in the campaign workspace directory.

Read-only on pipeline-generated documents (world_state, campaign_state, etc.).
Write access is restricted to <campaign_dir>/notes/ only.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

try:
    from mempalace.searcher import search_memories
    _HAS_MEMPALACE = True
except ImportError:
    _HAS_MEMPALACE = False

# ── Bootstrap ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from campaignlib import load_config, load_file, wiring_get

# Resolve campaign directory: env var → CLI arg → CWD
_campaign_dir_arg = ""
for i, arg in enumerate(sys.argv):
    if arg == "--campaign-dir" and i + 1 < len(sys.argv):
        _campaign_dir_arg = sys.argv[i + 1]
        break

_campaign_dir_str = (
    os.environ.get("CAMPAIGN_DIR", "")
    or _campaign_dir_arg
    or str(Path.cwd())
)
campaign_dir = Path(_campaign_dir_str).expanduser().resolve()

# Load config
_config_path = campaign_dir / "config.yaml"
if not _config_path.exists():
    _config_path = SCRIPT_DIR / "config" / "config.yaml"

config, base_dir = load_config(str(_config_path))

# Build label → path index from config documents list
_doc_index: dict[str, Path | None] = {}
for _entry in config.get("documents", []):
    _label = _entry.get("label", "")
    _raw_path = _entry.get("path")
    if _label:
        if _raw_path:
            _p = Path(_raw_path)
            _doc_index[_label] = _p if _p.is_absolute() else base_dir / _p
        else:
            _doc_index[_label] = None

# Notes workspace (write-allowed area)
notes_dir = campaign_dir / "notes"

# Mempalace config (wing names are campaign-specific)
_mp_config = config.get("mempalace", {})
_mp_index_wings = _mp_config.get(
    "index_wings", ["chronicle", campaign_dir.name.replace("-", "_")]
)
_mp_canon_wing = _mp_config.get("canon_wing", "narrative")

# ── MCP server ────────────────────────────────────────────────────────────────

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "campaign",
    instructions=(
        f"Campaign data for the D&D campaign at {campaign_dir}. "
        "Read-only access to pipeline-generated documents (world_state, campaign_state, planning, party). "
        f"Write access is restricted to {notes_dir}/ — use write_note/append_note to draft ideas, "
        "NPC refinements, encounter designs, and world additions without touching generated files."
    ),
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_doc(label_or_path: str) -> Path | None:
    """Resolve a label or relative/absolute path to an absolute Path, or None."""
    if label_or_path in _doc_index:
        return _doc_index[label_or_path]
    p = Path(label_or_path).expanduser()
    if p.is_absolute():
        return p
    return campaign_dir / p


def _read_doc(label_or_path: str) -> str:
    p = _resolve_doc(label_or_path)
    if p is None:
        return f"(no path configured for '{label_or_path}')"
    if not p.exists():
        return f"(file not found: {p})"
    return p.read_text(encoding="utf-8")


def _safe_notes_path(filename: str) -> Path:
    """Resolve filename within notes_dir, raising ValueError if it escapes."""
    target = (notes_dir / filename).resolve()
    if not str(target).startswith(str(notes_dir.resolve())):
        raise ValueError(f"Path '{filename}' resolves outside notes directory")
    return target


async def _run_script(script_name: str, args: list[str]) -> str:
    """Run a CLI tool as a subprocess, return combined stdout+stderr.

    `script_name` is either a `<name>.py` filename (resolved against
    SCRIPT_DIR, the repo root) for scripts that still live there, or a bare
    console-script name (no `.py`) for scripts that have migrated into
    `pipelines/` and gained a `[project.scripts]` entry point — resolved
    against the current interpreter's own venv `bin/` directory rather than
    `$PATH`, so it works whether or not the venv is "activated".
    """
    if script_name.endswith(".py"):
        cmd = [sys.executable, str(SCRIPT_DIR / script_name), *args]
    else:
        cmd = [str(Path(sys.executable).parent / script_name), *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(campaign_dir),
    )
    stdout, _ = await proc.communicate()
    return stdout.decode("utf-8", errors="replace")


# ── Resources ─────────────────────────────────────────────────────────────────

@mcp.resource(
    "campaign://docs/campaign_state",
    name="campaign_state",
    description="Completed encounters/quests, resolved plot threads, current NPC states, active quests. Read this first.",
    mime_type="text/markdown",
)
def get_campaign_state() -> str:
    return _read_doc("campaign_state")


@mcp.resource(
    "campaign://docs/world_state",
    name="world_state",
    description="Living canon lore document — locations, factions, history, established facts.",
    mime_type="text/markdown",
)
def get_world_state() -> str:
    return _read_doc("world_state")


@mcp.resource(
    "campaign://docs/planning",
    name="planning",
    description="Enemy dossiers, NPC motivations, forward planning notes.",
    mime_type="text/markdown",
)
def get_planning() -> str:
    return _read_doc("planning")


@mcp.resource(
    "campaign://docs/mechanics",
    name="mechanics",
    description="Arc score systems and campaign-specific mechanics.",
    mime_type="text/markdown",
)
def get_mechanics() -> str:
    return _read_doc("mechanics")


@mcp.resource(
    "campaign://docs/party",
    name="party",
    description="Party roster, character backstories, arc scores, relationships.",
    mime_type="text/markdown",
)
def get_party() -> str:
    # party.md may not be in config — try campaign_dir/docs/party.md as fallback
    content = _read_doc("party")
    if content.startswith("("):
        fallback = campaign_dir / "docs" / "party.md"
        if fallback.exists():
            return fallback.read_text(encoding="utf-8")
    return content


# ── Read / Query tools ────────────────────────────────────────────────────────

@mcp.tool()
def read_document(label_or_path: str) -> str:
    """Read any campaign document by config label (e.g. 'world_state') or path
    relative to the campaign directory. Returns the full text.

    Available labels: campaign_state, world_state, planning, mechanics, party.
    """
    return _read_doc(label_or_path)


@mcp.tool()
def search_document(pattern: str, scope: str = "docs") -> str:
    """Search campaign files for a keyword or regex pattern.

    scope options:
      'docs'      — search docs/ directory (default)
      'summaries' — search summaries/ directory
      'notes'     — search notes/ directory
      'all'       — search entire campaign directory

    Returns matching lines with file path and line number.
    """
    scope_dirs: list[Path] = []
    if scope == "docs":
        scope_dirs = [campaign_dir / "docs"]
    elif scope == "summaries":
        scope_dirs = [campaign_dir / "summaries"]
    elif scope == "notes":
        scope_dirs = [notes_dir]
    elif scope == "all":
        scope_dirs = [campaign_dir]
    else:
        scope_dirs = [campaign_dir / scope]

    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex pattern: {e}"

    results: list[str] = []
    for search_dir in scope_dirs:
        if not search_dir.exists():
            continue
        for md_file in sorted(search_dir.rglob("*.md")):
            try:
                lines = md_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            rel = md_file.relative_to(campaign_dir)
            for i, line in enumerate(lines, 1):
                if rx.search(line):
                    results.append(f"{rel}:{i}: {line.strip()}")

    if not results:
        return f"No matches found for '{pattern}' in scope '{scope}'."
    header = f"Found {len(results)} match(es) for '{pattern}' in '{scope}':\n\n"
    return header + "\n".join(results)


@mcp.tool()
def list_sessions() -> str:
    """List all session directories under summaries/, with available artifacts per session."""
    summaries_dir = campaign_dir / "summaries"
    if not summaries_dir.exists():
        return f"No summaries/ directory found at {campaign_dir}"

    sessions = sorted(
        [d for d in summaries_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )
    if not sessions:
        return "No session directories found in summaries/"

    lines = [f"Sessions in {summaries_dir}:\n"]
    for session in sessions:
        artifacts = []
        checks = {
            "summary": ["session-summary.md", "summary.md"],
            "gm-recap": ["gm-assist.md", "gm_assist.md", "gmassist.md"],
            "plan": ["plan.md", "scene_extractions/plan.md"],
            "extractions": ["scene_extractions/"],
            "roleplay": ["vtt_roleplay_extractions/"],
            "vtt": list(session.glob("*.vtt")),
        }
        for name, candidates in checks.items():
            if isinstance(candidates, list) and candidates and isinstance(candidates[0], Path):
                if candidates:
                    artifacts.append(name)
            else:
                for c in candidates:
                    if (session / c).exists():
                        artifacts.append(name)
                        break

        artifact_str = ", ".join(artifacts) if artifacts else "empty"
        lines.append(f"  {session.name}/  [{artifact_str}]")

    return "\n".join(lines)


@mcp.tool()
def list_files(subdir: str = "docs") -> str:
    """List files in a campaign subdirectory (e.g. 'docs', 'docs/npcs', 'voice', 'notes').
    Returns file paths relative to campaign dir with file sizes.
    """
    target = campaign_dir / subdir
    if not target.exists():
        return f"Directory not found: {target}"
    if not target.is_dir():
        return f"Not a directory: {target}"

    files = sorted(target.rglob("*"))
    file_lines = []
    for f in files:
        if f.is_file():
            size = f.stat().st_size
            rel = f.relative_to(campaign_dir)
            size_str = f"{size:,} bytes" if size < 10_000 else f"{size // 1024} KB"
            file_lines.append(f"  {rel}  ({size_str})")

    if not file_lines:
        return f"No files found in {subdir}/"
    return f"Files in {subdir}/:\n" + "\n".join(file_lines)


# ── Notes workspace tools (write-enabled) ─────────────────────────────────────

@mcp.tool()
def list_notes() -> str:
    """List all files in the notes/ workspace with sizes and modification times."""
    if not notes_dir.exists():
        return f"Notes directory does not exist yet: {notes_dir}\nUse write_note to create the first note."

    import time
    files = sorted(notes_dir.rglob("*"))
    file_lines = []
    for f in files:
        if f.is_file():
            stat = f.stat()
            size = stat.st_size
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
            rel = f.relative_to(notes_dir)
            size_str = f"{size:,} bytes" if size < 10_000 else f"{size // 1024} KB"
            file_lines.append(f"  {rel}  ({size_str}, {mtime})")

    if not file_lines:
        return f"Notes directory is empty: {notes_dir}"
    return f"Notes ({notes_dir}):\n" + "\n".join(file_lines)


@mcp.tool()
def write_note(filename: str, content: str) -> str:
    """Write content to a file in the notes/ workspace.

    filename can include subdirectories (e.g. 'npcs/grundar_refinements.md',
    'session_prep/session_12_ideas.md'). Parent directories are created automatically.

    This is the only write operation allowed — pipeline-generated files
    (world_state, campaign_state, planning, party) are never modified.

    Returns the full path written and byte count.
    """
    try:
        target = _safe_notes_path(filename)
    except ValueError as e:
        return f"Error: {e}"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Written: {target} ({len(content.encode('utf-8')):,} bytes)"


@mcp.tool()
def append_note(filename: str, content: str, separator: str = "\n\n---\n\n") -> str:
    """Append content to a file in the notes/ workspace, creating it if it doesn't exist.

    Useful for accumulating ideas across a session without overwriting existing notes.
    separator — text inserted between existing content and the new content (default: horizontal rule).
    """
    try:
        target = _safe_notes_path(filename)
    except ValueError as e:
        return f"Error: {e}"

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        new_content = existing.rstrip() + separator + content
    else:
        new_content = content

    target.write_text(new_content, encoding="utf-8")
    return f"Appended to: {target} ({len(new_content.encode('utf-8')):,} bytes total)"


# ── Mempalace search tools ───────────────────────────────────────────────────


_MP_PALACE_PATH = str(Path.home() / ".mempalace" / "palace")


def _mempalace_search(
    query: str,
    wings: list[str],
    n_results: int = 5,
    room: str | None = None,
) -> list[dict]:
    """Search one or more mempalace wings, return merged results sorted by similarity."""
    all_results: list[dict] = []
    for wing in wings:
        try:
            resp = search_memories(
                query=query,
                palace_path=_MP_PALACE_PATH,
                wing=wing,
                room=room if room else None,
                n_results=n_results,
            )
        except Exception:
            continue
        for hit in resp.get("results", []):
            all_results.append(hit)
    all_results.sort(key=lambda h: h.get("similarity", 0), reverse=True)
    return all_results[:n_results]


def _format_mp_results(results: list[dict], header: str = "Results") -> str:
    """Format mempalace search results as structured markdown."""
    if not results:
        return ""
    lines = [f"## {header}\n"]
    for i, hit in enumerate(results, 1):
        wing = hit.get("wing", "?")
        room = hit.get("room", "?")
        source = hit.get("source_file", "?")
        sim = hit.get("similarity", 0)
        text = hit.get("text", "").strip()
        lines.append(f"### [{i}] {wing} / {room} — {source} ({sim:.2f})")
        lines.append(f"> {text}\n")
    return "\n".join(lines)


@mcp.tool()
def quick_search(query: str, limit: int = 5, room: str = "") -> str:
    """Search the campaign's mempalace index (chronicle + current-state wings).

    Returns structured results from the maintained index — NPC dossiers,
    world-state snapshots, faction states, threat trackers. This is the fast
    path for most lookups.

    query — what to search for (e.g. "Shal advisor", "Zuggtmoy wedding")
    limit — max results to return (default: 5)
    room  — optional room filter (e.g. "npcs", "world", "arcs")

    Use grounded_search instead when you need to verify a fact against the
    canonical session narrative.
    """
    if not _HAS_MEMPALACE:
        return "Error: mempalace is not installed. Run: pip install mempalace"

    results = _mempalace_search(
        query, _mp_index_wings, n_results=limit, room=room or None
    )
    if not results:
        return f"No results found for '{query}'."
    return _format_mp_results(results, header=f"Index results for: {query}")


@mcp.tool()
def grounded_search(query: str, limit: int = 3) -> str:
    """Search the index then verify against the canonical session narrative.

    Step 1: Searches chronicle + current-state wings (same as quick_search).
    Step 2: Uses the top hit to search the narrative (chapter bible) for the
    verbatim canonical passage.

    Use this when building on a fact, designing a callback, or checking
    something load-bearing. The narrative section is the authoritative record
    of what actually happened at the table.

    query — what to search for
    limit — max index results (default: 3); narrative always returns top 3
    """
    if not _HAS_MEMPALACE:
        return "Error: mempalace is not installed. Run: pip install mempalace"

    # Step 1: index search
    index_results = _mempalace_search(
        query, _mp_index_wings, n_results=limit
    )

    # Step 2: narrative verification using top hit + original query
    narrative_query = query
    if index_results:
        top_text = index_results[0].get("text", "")[:200]
        narrative_query = f"{query} — {top_text}"

    narrative_results = _mempalace_search(
        narrative_query, [_mp_canon_wing], n_results=3
    )

    # Format both sections
    parts: list[str] = []
    if index_results:
        parts.append(_format_mp_results(index_results, header=f"Index results for: {query}"))
    else:
        parts.append(f"No index results found for '{query}'.\n")

    if narrative_results:
        parts.append(_format_mp_results(narrative_results, header="Canon verification (narrative)"))
    else:
        parts.append("No narrative results found for verification.\n")

    return "\n---\n\n".join(parts)


# ── Claude-powered tools (subprocess) ─────────────────────────────────────────

def _find_summaries_file() -> str | None:
    """Try to locate the summaries file in common locations."""
    candidates = [
        campaign_dir / "summaries.md",
        campaign_dir / "summaries" / "summaries.md",
        campaign_dir / "docs" / "summaries.md",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


@mcp.tool()
async def query_lore(query: str, summaries_file: str = "", hits_only: bool = False) -> str:
    """Search session summaries for any event, NPC, location, or topic and return a synthesized answer.

    query        — the question or topic to search for (e.g. "What happened with Grundar at Icespire Hold?")
    summaries_file — path to summaries markdown file; auto-detected if omitted
    hits_only    — if True, return raw matching extracts without synthesis (faster)

    This searches the full session history and synthesizes a direct answer. Use it to look up
    lore, verify what happened, or check the current state of an NPC or plot thread.
    """
    sf = summaries_file or _find_summaries_file() or ""
    if not sf:
        return (
            "Could not locate a summaries file. "
            "Pass summaries_file explicitly, or place summaries.md in the campaign directory."
        )

    args = [sf, query]
    if hits_only:
        args.append("--hits-only")

    return await _run_script("query.py", args)


@mcp.tool()
async def session_prep(beat: str, mode: str = "single", model: str = "") -> str:
    """Generate a session prep encounter document for a given beat.

    beat  — description of the encounter or scene (e.g. "The party confronts Ilvara in the throne room")
    mode  — 'single' (one-pass) or 'pipeline' (Lore Oracle → Encounter Architect → Voice Keeper)
    model — Claude model to use (leave empty for default)

    Returns the full structured encounter design document. Save the result with write_note
    if you want to keep it for later reference.
    """
    args = ["--beat", beat, "--mode", mode, "--no-log"]
    if model:
        args += ["--model", model]
    return await _run_script("prep", args)


@mcp.tool()
async def arc_triggers(character: str, top: int = 3) -> str:
    """Search for arc score trigger candidates using mempalace's chronicle wing.

    Finds the character's score tracking document via mempalace search,
    extracts trigger definitions from it, then searches the chronicle
    (timeline) wing for events matching each trigger. Returns candidates
    organized by trigger with source references.

    character — character name (e.g. 'brewbarry', 'soma', 'valphine').
                Searches mempalace for the matching score doc — doesn't
                need to be exact.
    top       — max chronicle results per trigger (default: 3)

    This is a candidate-finding tool — the DM decides whether a trigger fires.
    """
    args = ["--character", character]
    if top != 3:
        args += ["--top", str(top)]
    return await _run_script("arc_triggers", args)


@mcp.tool()
async def generate_npc_table(docs: list[str] | None = None, model: str = "") -> str:
    """Generate a markdown NPC reference table (Name / Faction / Current State / Motivations).

    docs  — list of document labels to draw from (default: ['world_state', 'planning'])
    model — Claude model to use (leave empty for default)

    Returns a markdown table. Save with write_note to keep a snapshot.
    """
    if docs is None:
        docs = ["world_state", "planning"]

    args = ["--docs"] + docs + ["--no-log"]
    if model:
        args += ["--model", model]
    return await _run_script("npc_table", args)


# ── RLM Phase 3: RPG retrieval tools ──────────────────────────────────────────
#
# These three tools expose the CampaignGenerator → MemPalace / rpglib
# retrieval surface (Phase 2) plus the human-reviewable proposal producer
# (Phase 3). None of them calls Claude; render pipelines deliberately go
# through `docs/dossier_proposal.md` rather than raw retrieval output.


def _resolve_palace_path() -> str | None:
    """Best-effort palace path — env var, per-campaign mempalace config,
    or None (falls through to mempalace-mcp's own resolution chain)."""
    for key in ("MEMPALACE_PALACE_PATH", "MEMPAL_PALACE_PATH"):
        val = os.environ.get(key)
        if val:
            return val
    for key in ("palace", "palace_path"):
        val = _mp_config.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _resolve_rpg_library_url() -> str | None:
    """Resolve the rpg-library HTTP base URL — env var, config, or default.

    Returns None when unwired (no env var, config, or mneme wiring key) —
    callers must not assume a str.
    """
    val = os.environ.get("RPG_LIBRARY_URL")
    if val:
        return val
    val = config.get("rpg_library_url")
    if isinstance(val, str) and val:
        return val
    return wiring_get("rpg_library_url")


def _resolve_fivetools_data_root() -> Path | None:
    """Resolve the 5etools-canonical data root — env var, config, or None."""
    val = os.environ.get("FIVETOOLS_DATA_ROOT")
    if val:
        return Path(val).expanduser()
    val = config.get("fivetools_data_root")
    if isinstance(val, str) and val:
        return Path(val).expanduser()
    return None


@mcp.tool()
def rpg_search(
    query: str = "",
    limit: int = 10,
    k_cheap: int = 10,
    k_expensive: int = 10,
    include_cheap: bool = True,
    include_expensive: bool = True,
    game_system: str = "",
    product_type: str = "",
    source: str = "",
    book_id: int = 0,
    file_path: str = "",
    pin_filter: str = "",
    palace: str = "",
    max_depth: int = 2,
) -> str:
    """Search MemPalace + 5etools-canonical + rpg-library; return tiered hits.

    Tiered retrieval result:
      * drawer / statblock — already-ingested MemPalace content.
      * candidate (cost: cheap)     — 5etools JSON on disk; one-line
        ingest via fivetools_ingest.py.
      * candidate (cost: expensive) — rpg-library PDF needing
        pdf_to_5etools_v2.py conversion + ingest.

    Modes:
      * Mode A — pass `query`. Searches all sources.
      * Mode B — pass `query` plus `source` (5etools source code like
        "MM"/"OotA") to scope the cheap pool, OR `book_id` to scope the
        expensive pool.
      * Mode C — leave `query` empty; pass `file_path` (+ optional
        `pin_filter` like "name=Drow Priestess of Lolth" or "chapter=0")
        for a cheap pin, OR `book_id` for an expensive pin.

    Args:
      query             — free-text query (Mode A / Mode B with scope).
      limit             — max drawer/statblock hits (tier 1).
      k_cheap           — max cheap candidates emitted (tier 2).
      k_expensive       — max expensive candidates emitted (tier 3).
      include_cheap     — set False to suppress tier 2 entirely.
      include_expensive — set False to suppress tier 3 entirely.
      game_system       — optional filter ("D&D 5e", "Pathfinder 2e", …).
      product_type      — optional filter ("adventure", "bestiary", …).
      source            — optional cheap-pool 5etools source scope.
      book_id           — optional expensive-pool scope or pin.
      file_path         — Mode C cheap pin: 5etools JSON to ingest.
      pin_filter        — Mode C cheap pin: filter spec
                          ("name=X[,source=Y]" or "chapter=N").
      palace            — override the active campaign palace name.
      max_depth         — 0 = wings only, 1 = wings+rooms, 2 = full descent.

    This is a *retrieval* tool. Use propose_dossier to capture the result in
    a reviewable file before letting any render pipeline consume it.
    """
    import json

    from rpg_retriever import retrieve

    try:
        result = retrieve(
            query,
            palace=palace or _resolve_palace_path(),
            rpg_library_url=_resolve_rpg_library_url(),
            fivetools_data_root=_resolve_fivetools_data_root(),
            limit=limit,
            k_cheap=k_cheap,
            k_expensive=k_expensive,
            include_cheap=include_cheap,
            include_expensive=include_expensive,
            game_system=game_system or None,
            product_type=product_type or None,
            source=source or None,
            book_id=book_id or None,
            file_path=file_path or None,
            pin_filter=pin_filter or None,
            max_depth=max_depth,
        )
    except Exception as exc:
        return f"Error: rpg_search failed: {exc}"
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def propose_dossier(
    query: str,
    output: str = "",
    limit: int = 20,
    k_cheap: int = 10,
    k_expensive: int = 5,
    include_cheap: bool = True,
    include_expensive: bool = True,
    overwrite: bool = True,
) -> str:
    """Run rpg_search and write the slotted result to docs/dossier_proposal.md.

    query              — free-text query (session beat, faction name, NPC, …)
    output             — optional override path (default <campaign>/docs/dossier_proposal.md)
    limit              — max drawer/statblock candidates
    k_cheap            — max cheap candidates (5etools-canonical hits)
    k_expensive        — max expensive candidates (rpg-library PDFs)
    include_cheap      — set False to suppress cheap candidates
    include_expensive  — set False to suppress expensive candidates
    overwrite          — replace an existing proposal; False refuses if present

    Returns a short status string. The produced file is a CANDIDATES list —
    a human has to review it, edit scope, and change the status banner away
    from `candidates only` before any render pipeline will consume it.
    """
    from dossier_proposer import propose, render, write_proposal

    try:
        proposal = propose(
            query,
            campaign_dir=campaign_dir,
            palace=_resolve_palace_path(),
            rpg_library_url=_resolve_rpg_library_url(),
            fivetools_data_root=_resolve_fivetools_data_root(),
            limit=limit,
            k_cheap=k_cheap,
            k_expensive=k_expensive,
            include_cheap=include_cheap,
            include_expensive=include_expensive,
        )
    except Exception as exc:
        return f"Error: propose_dossier failed: {exc}"

    markdown = render(proposal)
    output_path = Path(output).expanduser() if output else campaign_dir / "docs" / "dossier_proposal.md"
    if output_path.exists() and not overwrite:
        return f"Refused: {output_path} already exists (pass overwrite=true)."
    try:
        write_proposal(markdown, output_path, overwrite=overwrite)
    except Exception as exc:
        return f"Error: write_proposal failed: {exc}"

    slot_summary = ", ".join(
        f"{k}={len(v)}" for k, v in proposal.slots.items() if v
    ) or "(all slots empty)"
    return (
        f"Wrote {output_path} — {proposal.raw_hit_count} hits, slots: {slot_summary}.\n"
        "Review the file, edit scope, and change the `> **Status:**` line "
        "from `candidates only` to e.g. "
        "`approved by <name> on <date>` before rendering."
    )


@mcp.tool()
def suggest_conversion(book_id: int = 0, filepath: str = "") -> str:
    """Build a ConversionSuggestion payload for an unconverted rpglib book.

    Pass either book_id (preferred) or the absolute filepath. Hits the
    rpg-library HTTP API (book lookup → /api/library/book/{id} or
    search by filepath) and returns the JSON convert+ingest command pair
    plus cost estimate.
    """
    import json as _json

    from rpg_retriever import _http_get_json
    from suggest_conversion import build_suggestion

    raw_url = _resolve_rpg_library_url()
    if not raw_url:
        return (
            "Error: rpg-library URL not configured. Set RPG_LIBRARY_URL, "
            "config.yaml's rpg_library_url, or the mneme wiring rpg_library_url."
        )
    base_url = raw_url.rstrip("/")
    palace = _resolve_palace_path()

    book: dict | None = None
    if book_id:
        book = _http_get_json(f"{base_url}/api/library/book/{int(book_id)}")
    if book is None and filepath:
        # rpg-library /search doesn't support exact filepath matching directly;
        # fall back to a substring search by filename and post-filter.
        from urllib.parse import urlencode
        stem = Path(filepath).name
        result = _http_get_json(
            f"{base_url}/api/library/search?{urlencode({'q': stem, 'per_page': '20'})}"
        )
        if isinstance(result, dict):
            for row in result.get("results", []) or []:
                if isinstance(row, dict) and row.get("filepath") == filepath:
                    book = row
                    break

    if not book or not book.get("filepath"):
        return "Error: book not found via rpg-library API (check book_id/filepath, server running at " + base_url + ")."

    suggestion = build_suggestion(book, palace=palace)
    return _json.dumps(suggestion.to_dict(), indent=2, default=str)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
