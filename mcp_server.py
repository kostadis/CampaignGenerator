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

# ── Bootstrap ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from campaignlib import load_config, load_file

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
    """Run a CLI script as a subprocess, return combined stdout+stderr."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(SCRIPT_DIR / script_name),
        *args,
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
    return await _run_script("prep.py", args)


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
    return await _run_script("arc_triggers.py", args)


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
    return await _run_script("npc_table.py", args)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
