"""Shared utilities for CampaignGenerator scripts.

All file I/O, API calls, clipboard, and logging live here so individual
scripts only contain their own logic.
"""

import re
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_MODEL = "claude-sonnet-4-20250514"


# ── Text cleaning ─────────────────────────────────────────────────────────────

_BASE64_IMAGE_RE = re.compile(
    r'^\[image\d+\]:\s*<data:image/[^>]+>\s*$',
    re.MULTILINE,
)

def strip_base64_images(text: str) -> str:
    """Remove markdown reference-style base64 image definitions (e.g. [image1]: <data:image/png;base64,...>)."""
    return _BASE64_IMAGE_RE.sub('', text)


# ── Text chunking ─────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int) -> list[str]:
    """Split text into chunks at paragraph boundaries near chunk_size chars."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        boundary = text.rfind("\n\n", start, end)
        if boundary == -1 or boundary <= start:
            boundary = text.rfind("\n", start, end)
        if boundary == -1 or boundary <= start:
            boundary = end
        chunks.append(text[start:boundary])
        start = boundary
    return [c.strip() for c in chunks if c.strip()]


def chunk_by_chapters(text: str, chapter_pattern: str) -> list[str]:
    """Split text at headings beginning with chapter_pattern."""
    parts = re.split(rf'(?m)(?=^{re.escape(chapter_pattern)})', text)
    return [p.strip() for p in parts if p.strip()]


def prepare_chunks(
    text: str,
    chunk_size: int,
    split_chapters: str | None = None,
    split_label: str = "section",
) -> tuple[list[str], str]:
    """Chunk text by chapter prefix or character count, print progress, return (chunks, label).

    Strips embedded base64 image data before chunking.

    split_label — word used in the progress line when splitting by prefix
                  (e.g. "session", "chapter"). Defaults to "section".
    """
    text = strip_base64_images(text)
    if split_chapters:
        chunks = chunk_by_chapters(text, split_chapters)
        print(f"  {len(chunks)} {split_label}(s) to process (split on: {split_chapters!r})\n")
        return chunks, split_label
    chunks = chunk_text(text, chunk_size)
    print(f"  {len(chunks)} chunk(s) to process (chunk size: {chunk_size:,} chars)\n")
    return chunks, "chunk"


# ── Extract / synthesize pipeline ─────────────────────────────────────────────

def run_extract_pipeline(
    client,
    text: str,
    *,
    extract_system: str,
    model: str,
    extract_dir: Path,
    chunk_size: int = 60000,
    split_chapters: str | None = None,
    split_label: str = "chunk",
    filename_template: str = "extract_{i:03d}.md",
) -> list[Path]:
    """Chunk `text`, run `extract_system` against each chunk, cache each result to `extract_dir`.

    Files are named via `filename_template` (default `extract_NNN.md`; `{i}` is
    the 1-indexed chunk number). Existing files are skipped so a partial run
    can be resumed. Returns the ordered list of output paths (including skipped
    ones).
    """
    chunks, label = prepare_chunks(text, chunk_size, split_chapters, split_label=split_label)
    total = len(chunks)
    extract_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    for i, chunk in enumerate(chunks, 1):
        out_file = extract_dir / filename_template.format(i=i)
        if out_file.exists():
            print(f"  [{i}/{total}] Skipping (already exists): {out_file.name}")
            saved.append(out_file)
            continue

        print(f"  [{i}/{total}] Extracting {label} ({len(chunk):,} chars)...")
        print("  " + "─" * 56)
        result = stream_api(client, extract_system, chunk, model)
        print("  " + "─" * 56)

        out_file.write_text(result, encoding="utf-8")
        saved.append(out_file)
        print(f"  Saved: {out_file.name}\n")

    return saved


def run_synthesize_pipeline(
    client,
    *,
    source_groups: list[tuple],
    synthesize_system: str,
    model: str,
    source_label: str = "Source",
    group_separator: str = "\n\n===\n\n",
    file_separator: str = "\n\n---\n\n",
) -> str:
    """Concat labeled file groups into a user prompt, call `stream_api`, return the response.

    source_groups — list of tuples in one of two shapes:
                      `(heading, files)` — uses the default `source_label`
                      `(heading, files, group_label)` — override label for this group
                    An empty heading renders the group's files without a
                    `# HEADING` line (used when a single unnamed group is the
                    whole input, e.g. distill.py). Groups with no files are
                    skipped.

    Each file is rendered as:
        <!-- {label}: {filename} -->

        <stripped contents>

    Files within a group are joined by `file_separator`; groups are joined by
    `group_separator`. Exits with SystemExit(1) if all groups are empty.
    """
    parts: list[str] = []
    total_files = 0
    for group in source_groups:
        if len(group) == 3:
            heading, files, group_label = group
        else:
            heading, files = group
            group_label = source_label
        if not files:
            continue
        blocks = [
            f"<!-- {group_label}: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
            for f in files
        ]
        body = file_separator.join(blocks)
        parts.append(f"# {heading}\n\n{body}" if heading else body)
        total_files += len(files)

    if not parts:
        print("Error: no source material to synthesize.", file=sys.stderr)
        raise SystemExit(1)

    user_prompt = group_separator.join(parts)
    print(f"  Synthesizing {total_files} source file(s) ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, synthesize_system, user_prompt, model)
    print("  " + "─" * 56)
    return result


# ── NPC alias machinery ───────────────────────────────────────────────────────
#
# Dossier frontmatter records human-curated canonical ↔ alias mappings
# (see "Dossier merge workflow" in CLAUDE.md). Every extractor can pre-
# normalize its input against this map before the LLM sees it, and seed
# its system prompt with a "Known NPCs" roster. Normalization is a pure
# regex substitution — no LLM scope decision is introduced here.
#
# Empty alias maps collapse cleanly: normalize() becomes identity,
# format_npc_roster() returns "". Safe for campaigns without a planning
# workflow.

_DOSSIER_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n\n?(.*)\Z", re.DOTALL)


def parse_dossier(path: "Path") -> tuple[str, list[str], list[int], str]:
    """Return (canonical_name, aliases, source_extracts, body_without_frontmatter).

    `source_extracts` is the list of dossier_extract_NNN numbers already
    absorbed into this dossier (used by planning.py's sidecar dedup).
    Missing or malformed → empty list.

    Dossiers without frontmatter fall back to (filename_stem, [], [], full_text).
    """
    try:
        import yaml
    except ImportError:
        print("Error: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    text = path.read_text(encoding="utf-8")
    m = _DOSSIER_FRONTMATTER_RE.match(text)
    if not m:
        return (path.stem, [], [], text)
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return (path.stem, [], [], text)
    name = meta.get("name") or path.stem
    aliases = meta.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = []
    source_extracts = meta.get("source_extracts") or []
    if not isinstance(source_extracts, list):
        source_extracts = []
    source_extracts = [
        int(n) for n in source_extracts
        if isinstance(n, int) or (isinstance(n, str) and n.isdigit())
    ]
    return (str(name), [str(a) for a in aliases], source_extracts, m.group(2))


def normalize_npc_key(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for alias-key lookups.

    LLM-emitted variants like "Harbin (Townmaster)" must match flat aliases
    like "Harbin Townmaster". Without normalization the parens block lookup.
    """
    s = re.sub(r"[\(\)\[\]\'\"`\-]", "", name.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_alias_normalizer(
    canonical_to_aliases: dict[str, list[str]],
):
    """Return (normalize(text) -> text, [(canonical, aliases), ...]).

    The returned `normalize` rewrites any alias occurrence in `text` to
    its canonical name. Whole-word, case-insensitive, longest-first
    (so "Captain Tolubb" wins over "Tolubb" when both are aliases).

    An empty map yields an identity function and an empty entries list,
    so every extractor can call this unconditionally.
    """
    alias_to_canonical: dict[str, str] = {}
    for canonical, aliases in canonical_to_aliases.items():
        for alias in aliases:
            alias_to_canonical[alias.lower()] = canonical

    if not alias_to_canonical:
        return (lambda text: text, [])

    sorted_aliases = sorted(alias_to_canonical.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(a) for a in sorted_aliases) + r")\b",
        flags=re.IGNORECASE,
    )

    def normalize(text: str) -> str:
        return pattern.sub(lambda m: alias_to_canonical[m.group(0).lower()], text)

    entries = [(c, a) for c, a in canonical_to_aliases.items() if a]
    return (normalize, entries)


def load_alias_map(dossier_dir) -> dict[str, list[str]]:
    """Scan `dossier_dir` for `*.md` dossiers; return `{canonical: [aliases]}`.

    Returns `{}` when `dossier_dir` is None, missing, or contains no
    dossiers — makes the caller a no-op for campaigns without planning.
    """
    if dossier_dir is None:
        return {}
    d = Path(dossier_dir).expanduser()
    if not d.is_dir():
        return {}
    result: dict[str, list[str]] = {}
    for f in sorted(d.glob("*.md")):
        # Skip sidecar files — they're not canonical dossiers.
        if ".new_notes." in f.name:
            continue
        name, aliases, _, _ = parse_dossier(f)
        result[name] = aliases
    return result


def format_npc_roster(alias_map: dict[str, list[str]]) -> str:
    """Render an alias map as a 'Known NPCs' block to append to an extract prompt.

    Returns '' when the map is empty, so callers can write:
        system = BASE + ("\\n\\n" + roster if roster else "")
    """
    if not alias_map:
        return ""
    lines = [
        "Known NPCs in this campaign — use these exact canonical names when an NPC "
        "appears in the source text, even if the text uses a variant:"
    ]
    for canonical in sorted(alias_map):
        aliases = alias_map[canonical]
        if aliases:
            lines.append(f"- {canonical} (also: {', '.join(aliases)})")
        else:
            lines.append(f"- {canonical}")
    return "\n".join(lines)


# ── Config ────────────────────────────────────────────────────────────────────

def find_default_config(script_file: str) -> str:
    """Return CWD/config.yaml if it exists, else <script_dir>/config/config.yaml."""
    cwd_config = Path.cwd() / "config.yaml"
    if cwd_config.exists():
        return str(cwd_config)
    return str(Path(script_file).resolve().parent / "config" / "config.yaml")


def load_config(config_path: str) -> tuple[dict, Path]:
    """Load a YAML config file. Returns (config_dict, config_directory)."""
    try:
        import yaml
    except ImportError:
        print("Error: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    p = Path(config_path).expanduser().resolve()
    with open(p) as f:
        return yaml.safe_load(f), p.parent


# ── File I/O ──────────────────────────────────────────────────────────────────

def load_file(path: str, base_dir: Path | None = None) -> str:
    """Read a file. Relative paths are resolved against base_dir if given."""
    p = Path(path).expanduser()
    if not p.is_absolute() and base_dir:
        p = base_dir / p
    if not p.exists():
        print(f"Error: file not found: {p}", file=sys.stderr)
        sys.exit(1)
    return p.read_text(encoding="utf-8")


def load_file_optional(path: str | Path, label: str = "file") -> str | None:
    """Read a file, returning None (with a stderr warning) if it does not exist."""
    p = Path(path).expanduser()
    if not p.exists():
        print(f"  Warning: {label} not found: {p}", file=sys.stderr)
        return None
    return p.read_text(encoding="utf-8")


def assemble_docs(config: dict, doc_labels: list[str], base_dir: Path | None = None) -> str:
    """Load the requested document labels from config and join them with separators.

    Documents with no path set are skipped with a warning.
    Raises SystemExit if a requested label is not in the config at all,
    or if no documents with a path could be loaded.
    """
    available = {d["label"]: d.get("path") for d in config.get("documents", [])}
    parts = []
    for label in doc_labels:
        if label not in available:
            print(
                f"Error: document '{label}' not found in config. "
                f"Available: {[k for k, v in available.items() if v]}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not available[label]:
            print(f"Skipping '{label}': no path set in config.", file=sys.stderr)
            continue
        content = load_file(available[label], base_dir)
        parts.append(f"## {label}\n\n{content.strip()}")
    if not parts:
        print("Error: no documents with a path to load.", file=sys.stderr)
        sys.exit(1)
    return "\n\n---\n\n".join(parts)


# ── API ───────────────────────────────────────────────────────────────────────

def make_client():
    """Return an Anthropic client, exiting with a helpful message if not installed."""
    try:
        import anthropic
    except ImportError:
        print("Error: anthropic not installed. Run: pip install anthropic", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic()


def _is_retryable(exc) -> bool:
    """Return True for transient API errors that are worth retrying."""
    try:
        import anthropic
        if isinstance(exc, (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        )):
            return True
        if isinstance(exc, anthropic.APIStatusError) and exc.status_code == 529:
            return True  # overloaded_error
    except ImportError:
        pass
    try:
        import httpx
        if isinstance(exc, (
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.TimeoutException,
        )):
            return True
    except ImportError:
        pass
    return False


def call_api(client, system: str, content, model: str, max_tokens: int = 8096) -> str:
    """Non-streaming API call. Returns full response text.

    content — a string or a list of content blocks (for multimodal/vision calls).
    Retries on transient errors (rate limit, overload, connection) with exponential backoff.
    """
    import time
    messages = [{"role": "user", "content": content}]
    delays = [10, 20, 40]
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [API unavailable — waiting {delay}s before retry {attempt}/{len(delays)}...]",
                  flush=True)
            time.sleep(delay)
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            return response.content[0].text
        except Exception as e:
            if _is_retryable(e) and attempt < len(delays):
                continue
            raise


def stream_api(client, system: str, user: str, model: str, max_tokens: int = 8096,
               silent: bool = False, verbose: bool = False) -> str:
    """Stream a Claude API call, printing each token as it arrives. Returns full response.

    Retries on transient errors (rate limit, overload, connection) with exponential backoff
    (up to 4 attempts). Pass silent=True to suppress all output (useful for
    filter/classification passes). Pass verbose=True to print the system and user prompts
    before calling.
    """
    if verbose:
        print("\n" + "▲" * 60)
        print("SYSTEM PROMPT:")
        print(system)
        print("─" * 60)
        print("USER PROMPT:")
        print(user)
        print("▲" * 60 + "\n")
    import time

    delays = [60, 120, 240]  # seconds to wait before each retry
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [API unavailable — waiting {delay}s before retry {attempt}/{len(delays)}...]",
                  flush=True)
            time.sleep(delay)
        try:
            chunks = []
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                for text in stream.text_stream:
                    if not silent:
                        print(text, end="", flush=True)
                    chunks.append(text)
            if not silent:
                print()
            return "".join(chunks)
        except Exception as e:
            if _is_retryable(e) and attempt < len(delays):
                continue
            raise


# ── Clipboard ─────────────────────────────────────────────────────────────────

def copy_to_clipboard(text: str) -> None:
    try:
        import pyperclip
        pyperclip.copy(text)
        print(f"Copied to clipboard ({len(text):,} chars).")
    except ImportError:
        print("pyperclip not installed. Run: pip install pyperclip", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Clipboard error: {e}", file=sys.stderr)
        print("On WSL you may need: sudo apt install xclip", file=sys.stderr)
        sys.exit(1)


# ── Logging ───────────────────────────────────────────────────────────────────

def save_log(log_dir: str, sections: list[tuple[str, str]], stem: str = "session") -> Path:
    """Save a markdown log file.

    sections — list of (heading, content) tuples
    stem     — filename prefix (timestamp is prepended automatically)
    """
    log_path = Path(log_dir).expanduser()
    log_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = log_path / f"{timestamp}_{stem}.md"
    lines = [f"# Session Log — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    for heading, content in sections:
        lines += ["", "---", "", f"## {heading}", "", content.strip()]
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_file
