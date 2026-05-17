"""Shared utilities for CampaignGenerator scripts.

All file I/O, API calls, clipboard, and logging live here so individual
scripts only contain their own logic.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
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
    text = strip_base64_images(text).lstrip("﻿")
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
    input_normalizer=None,
    system_suffix: str = "",
) -> list[Path]:
    """Chunk `text`, run `extract_system` against each chunk, cache each result to `extract_dir`.

    Files are named via `filename_template` (default `extract_NNN.md`; `{i}` is
    the 1-indexed chunk number). Existing files are skipped so a partial run
    can be resumed. Returns the ordered list of output paths (including skipped
    ones).

    input_normalizer — optional `Callable[[str], str]` applied to `text`
                       before chunking. Used to rewrite alias variants to
                       canonical names (see `build_alias_normalizer`).
    system_suffix    — optional string appended to `extract_system` with a
                       blank-line separator. Used to seed the prompt with a
                       "Known NPCs" roster (see `format_npc_roster`).
    """
    if input_normalizer:
        text = input_normalizer(text)
    if system_suffix:
        extract_system = extract_system + "\n\n" + system_suffix

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
    input_normalizer=None,
    system_suffix: str = "",
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

    input_normalizer — optional `Callable[[str], str]` applied to each file's
                       contents before it is rendered into the prompt.
    system_suffix    — optional string appended to `synthesize_system` with a
                       blank-line separator.
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
        blocks = []
        for f in files:
            body = f.read_text(encoding="utf-8").strip()
            if input_normalizer:
                body = input_normalizer(body)
            blocks.append(f"<!-- {group_label}: {f.name} -->\n\n{body}")
        body = file_separator.join(blocks)
        parts.append(f"# {heading}\n\n{body}" if heading else body)
        total_files += len(files)

    if not parts:
        print("Error: no source material to synthesize.", file=sys.stderr)
        raise SystemExit(1)

    if system_suffix:
        synthesize_system = synthesize_system + "\n\n" + system_suffix

    user_prompt = group_separator.join(parts)
    print(f"  Synthesizing {total_files} source file(s) ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, synthesize_system, user_prompt, model)
    print("  " + "─" * 56)
    return result


# ── Scene-anchored extraction ─────────────────────────────────────────────────
#
# The gm-assist recap already structures the session into scenes. Feeding that
# verified structure into extraction directly — instead of re-deriving structure
# from blind 50K-char chunks — keeps the LLM in its rendering lane (find verbatim
# moments inside a scene) instead of its architect lane (decide what a scene is).
# See CLAUDE.md "LLMs render, humans decide".

_SCENE_HEADING_RE = re.compile(r"^### +(.+?)\s*$")
_TOP_HEADING_RE = re.compile(r"^## +(.+?)\s*$")


def parse_gmassist_scenes(text: str) -> list[dict]:
    """Parse the `## Scenes` block of a gm-assist recap into ordered scene dicts.

    Returns a list of `{"name": str, "body": str}` — one per `### Scene Name`
    heading found under the first `## Scenes` heading. `body` is the verbatim
    text between this scene's heading and the next `###` (or the end of the
    Scenes section), preserving the optional `#### subtitle` line and bullets.

    Returns `[]` when no `## Scenes` section exists or it has no scene headings.
    Empty list is the signal to callers that no human-verified structure is
    available — they should bail out, not silently fall back to chunk mode.
    """
    lines = text.splitlines()
    in_scenes = False
    scenes: list[dict] = []
    current: dict | None = None
    body: list[str] = []

    def flush():
        if current is not None:
            current["body"] = "\n".join(body).strip()
            scenes.append(current)

    for line in lines:
        stripped = line.strip()
        if not in_scenes:
            if stripped.lower() == "## scenes":
                in_scenes = True
            continue
        # Inside ## Scenes — leaving on next ## heading
        if _TOP_HEADING_RE.match(line):
            flush()
            current = None
            body = []
            in_scenes = False
            continue
        m = _SCENE_HEADING_RE.match(line)
        if m:
            flush()
            current = {"name": m.group(1).strip(), "body": ""}
            body = []
            continue
        if current is not None:
            body.append(line)

    flush()
    return scenes


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def snapshot_scene_for_rerun(out_file: "Path", new_text: str) -> bool:
    """Decide whether a re-extraction's `new_text` should overwrite `out_file`.

    Returns True if the caller should write `new_text` (content differs or no
    file existed), False if the existing file is byte-identical (no write
    needed). When content differs, the existing file is snapshotted to
    `<out_file>.prev` and any `<out_file>.reviewed` marker is removed —
    a re-run that changed content invalidates the GM's prior approval.
    """
    if not out_file.exists():
        return True
    old_text = out_file.read_text(encoding="utf-8")
    if old_text == new_text:
        return False
    prev = out_file.with_name(out_file.name + ".prev")
    prev.write_text(old_text, encoding="utf-8")
    reviewed = out_file.with_name(out_file.name + ".reviewed")
    if reviewed.exists():
        reviewed.unlink()
    return True


def run_scene_extraction(
    client,
    *,
    vtt_text: str,
    scenes: list[dict],
    extract_dir: "Path",
    model: str,
    extraction_instruction: str,
    system_prefix: str = "",
    system_suffix: str = "",
    input_normalizer=None,
    cache_vtt: bool = True,
    filename_template: str = "{i:02d}_{slug}.md",
    max_tokens: int = 8192,
    force: bool = False,
) -> list[Path]:
    """For each scene in `scenes`, run a scene-anchored extraction over `vtt_text`.

    Each call sends the full VTT in the system prompt (cached as a prefix when
    `cache_vtt=True`) and a per-scene user prompt: the scene name + body from
    gm-assist plus `extraction_instruction`. Output is one markdown file per
    scene under `extract_dir`, named `NN_<slug>.md` by default.

    Existing files are skipped so a partial run can be resumed. Pass
    `force=True` to re-extract every scene; in that mode the prior file is
    snapshotted to `<file>.prev` (only if content differs) and any
    `<file>.reviewed` marker is cleared.

    extraction_instruction — the per-call task description. Receives `{name}`
                              and `{body}` substitutions and is rendered as the
                              user message. The caller controls the prompt — the
                              engine just orchestrates the loop and caching.
    system_prefix          — prepended to the system prompt (general-purpose
                              instructions that should be cached alongside the
                              VTT).
    system_suffix          — appended to the system prompt (e.g. NPC roster
                              from `format_npc_roster`).
    input_normalizer       — optional `Callable[[str], str]` applied to
                              `vtt_text` (alias normalization).
    """
    if not scenes:
        print("Error: no scenes provided — cannot run scene-anchored extraction.",
              file=sys.stderr)
        raise SystemExit(1)

    if input_normalizer:
        vtt_text = input_normalizer(vtt_text)

    extract_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    total = len(scenes)

    parts = []
    if system_prefix:
        parts.append(system_prefix.strip())
    parts.append("# TRANSCRIPT (full session VTT)\n\n" + vtt_text.strip())
    if system_suffix:
        parts.append(system_suffix.strip())
    system_prompt = "\n\n".join(parts)

    for i, scene in enumerate(scenes, 1):
        name = scene["name"]
        body = scene.get("body", "").strip()
        slug = _slugify(name) or f"scene_{i}"
        out_file = extract_dir / filename_template.format(i=i, slug=slug)
        if out_file.exists() and not force:
            print(f"  [{i}/{total}] Skipping (already exists): {out_file.name}")
            saved.append(out_file)
            continue

        user_prompt = extraction_instruction.format(name=name, body=body)
        action = "Re-extracting" if force and out_file.exists() else "Scene-extracting"
        print(f"  [{i}/{total}] {action}: {name}")
        print("  " + "─" * 56)
        result = stream_api(client, system_prompt, user_prompt, model,
                            max_tokens=max_tokens, cache_system=cache_vtt)
        print("  " + "─" * 56)

        new_text = format_scene_output(name, body, result)
        if snapshot_scene_for_rerun(out_file, new_text):
            out_file.write_text(new_text, encoding="utf-8")
            print(f"  Saved: {out_file.name}\n")
        else:
            print(f"  Unchanged (no overwrite): {out_file.name}\n")
        saved.append(out_file)

    return saved


def format_scene_output(name: str, body: str, result: str) -> str:
    """Render a scene extraction file body — shared by live and batch paths.

    Layout: front-matter + scene heading + scene summary (verbatim from
    gm-assist) + LLM-extracted verbatim moments. The live and batch paths
    must produce byte-identical files for the same `result` so that a
    user re-running with `--batch` sees no spurious diffs.
    """
    return (
        f"---\n"
        f"scene: {name}\n"
        f"source: gmassist\n"
        f"---\n\n"
        f"# {name}\n\n"
        f"## Scene summary (from gm-assist, verbatim)\n\n"
        f"{body.strip()}\n\n"
        f"## Verbatim moments\n\n"
        f"{result.strip()}\n"
    )


def build_scene_extraction_system_prompt(
    *,
    vtt_text: str,
    system_prefix: str = "",
    system_suffix: str = "",
    input_normalizer=None,
) -> str:
    """Build the system prompt that scene-extraction reuses across all scenes.

    Same shape as the inline assembly in `run_scene_extraction` so live
    and batch callers share one cache breakpoint.
    """
    if input_normalizer:
        vtt_text = input_normalizer(vtt_text)
    parts: list[str] = []
    if system_prefix:
        parts.append(system_prefix.strip())
    parts.append("# TRANSCRIPT (full session VTT)\n\n" + vtt_text.strip())
    if system_suffix:
        parts.append(system_suffix.strip())
    return "\n\n".join(parts)


def plan_scene_extraction(
    *,
    scenes: list[dict],
    extract_dir: "Path",
    filename_template: str = "{i:02d}_{slug}.md",
) -> list[dict]:
    """Map scenes to per-scene custom_ids and on-disk paths.

    Returns one dict per scene: {i, name, body, slug, custom_id, path,
    exists}. Used by both the live loop (for resumability) and the batch
    submitter (to build one Request per non-existent scene).
    """
    plan = []
    for i, scene in enumerate(scenes, 1):
        name = scene["name"]
        body = scene.get("body", "").strip()
        slug = _slugify(name) or f"scene_{i}"
        out_file = extract_dir / filename_template.format(i=i, slug=slug)
        plan.append({
            "i": i,
            "name": name,
            "body": body,
            "slug": slug,
            "custom_id": f"{i:02d}_{slug}",
            "path": out_file,
            "exists": out_file.exists(),
        })
    return plan


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


_PLAYER_PLACEHOLDERS = {
    "", "not specified", "(not specified)", "[not specified]",
    "n/a", "na", "none", "unknown", "tbd",
}


def _is_player_placeholder(name: str) -> bool:
    return name.strip().lower().strip("()[]").strip() in _PLAYER_PLACEHOLDERS


def extract_player_character_map(party_text: str) -> dict[str, str]:
    """Parse party.md and return {player_name: character_name}.

    Supports two heading + info-line shapes:

    Old (single bold span):
        ## Soma
        **Tortle Druid 5, Player: Wade**

    New (party.py output, multiple bold spans separated by ``|``):
        ### Soma — Druid 5
        **Class/Level:** Druid 5 | **Species:** Tortle | **Player:** Wade

    When the Player slot holds multiple names separated by ``/`` or
    ``,``, both names map to the same character. Placeholder values
    like ``(Not specified)`` / ``[not specified]`` / ``N/A`` are
    treated as missing.
    """
    result: dict[str, str] = {}
    current_name: str | None = None

    def _record_players(raw: str) -> None:
        if _is_player_placeholder(raw):
            return
        for p in re.split(r'[/,]', raw):
            p = p.strip().rstrip('*').strip()
            if p and not _is_player_placeholder(p) and current_name:
                result[p] = current_name

    for line in party_text.splitlines():
        stripped = line.strip()
        m = re.match(r'^#{2,3}\s+(.+)$', stripped)
        if m:
            heading = m.group(1).strip()
            current_name = re.split(r'\s+[—–-]\s+', heading, maxsplit=1)[0].strip()
            continue
        if not current_name:
            continue
        new_pm = re.search(r'\*\*Player:\*\*\s*([^|]+?)(?:\s*\||\s*$)', stripped)
        if new_pm:
            _record_players(new_pm.group(1))
            current_name = None
            continue
        cm = re.match(r'^\*\*(.+\d+.+)\*\*$', stripped)
        if cm:
            pm = re.search(r',\s*Player:\s*(.+)', cm.group(1))
            if pm:
                _record_players(pm.group(1))
            current_name = None

    # First-name aliases: if a player's recorded name is "Joe Beda" → also map
    # "Joe" → that character. Skip when the first name is ambiguous (two
    # players share it but map to different characters) so we don't pick one
    # arbitrarily. Existing full-name keys always win.
    first_name_to_chars: dict[str, set[str]] = {}
    for player, char in result.items():
        first = player.split()[0] if player.split() else ""
        if first and first != player:
            first_name_to_chars.setdefault(first, set()).add(char)
    for first, chars in first_name_to_chars.items():
        if len(chars) == 1 and first not in result:
            result[first] = next(iter(chars))

    return result


def normalize_vtt_speakers(
    vtt_text: str,
    player_map: dict[str, str] | None = None,
    gm_player: str | None = None,
) -> str:
    """Rewrite speaker labels at the start of VTT lines.

    Maps each ``Player Name:`` prefix to the corresponding character
    name from ``player_map``. ``gm_player`` (if given) is rewritten to
    ``GM`` regardless of any party.md entry. Longer names match first
    so a player named ``Mike`` and a player named ``Mike Hall`` are
    both handled correctly.

    Body text is untouched — only labels at the start of a dialogue
    line are rewritten. This is a deterministic preprocessing step the
    LLM never sees and never has to derive itself.
    """
    if not player_map and not gm_player:
        return vtt_text
    full_map = dict(player_map or {})
    if gm_player:
        full_map[gm_player] = "GM"
    sorted_keys = sorted(full_map.keys(), key=len, reverse=True)
    out_lines: list[str] = []
    for line in vtt_text.splitlines():
        for key in sorted_keys:
            prefix = f"{key}:"
            if line.startswith(prefix):
                line = f"{full_map[key]}:" + line[len(prefix):]
                break
        out_lines.append(line)
    return "\n".join(out_lines)


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

DGX_DEFAULT_MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"


def _flatten_to_text(value) -> str:
    """Reduce an Anthropic-style content value to plain text for OpenAI-compat servers.

    Accepts: a string, or a list of content blocks (dicts with "type" + "text").
    Drops any non-text blocks (images, tool_use). vLLM/Qwen doesn't see them.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for block in value:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n\n".join(p for p in parts if p)
    return str(value)


def _anthropic_to_openai_messages(system, messages):
    """Translate (system, [Anthropic messages]) → OpenAI chat.completions messages."""
    out = []
    sys_text = _flatten_to_text(system)
    if sys_text:
        out.append({"role": "system", "content": sys_text})
    for m in messages or []:
        out.append({"role": m["role"], "content": _flatten_to_text(m.get("content"))})
    return out


class _OpenAICompatResponse:
    """Mimics anthropic.types.Message just enough for call_api's `.content[0].text` access."""

    class _Block:
        def __init__(self, text: str):
            self.type = "text"
            self.text = text

    def __init__(self, text: str):
        self.content = [self._Block(text)]
        self.stop_reason = "end_turn"


class _OpenAICompatStream:
    """Mimics the anthropic streaming context manager: `with client.messages.stream(...) as s: s.text_stream`."""

    def __init__(self, oai_client, *, model: str, max_tokens: int, messages: list):
        self._oai = oai_client
        self._model = model
        self._max_tokens = max_tokens
        self._messages = messages
        self._stream = None

    def __enter__(self):
        self._stream = self._oai.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=self._messages,
            stream=True,
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self._stream.close()
        except Exception:
            pass
        return False

    @property
    def text_stream(self):
        def _iter():
            for chunk in self._stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None)
                if piece:
                    yield piece
        return _iter()


class _OpenAICompatMessages:
    def __init__(self, client: "_OpenAICompatClient"):
        self._client = client

    def _resolve_model(self, model: str) -> str:
        if self._client.model_override:
            return self._client.model_override
        # Caller passed an Anthropic model name (e.g. "claude-sonnet-4-6") which the
        # DGX server doesn't know about — substitute the configured default rather
        # than 404.
        if isinstance(model, str) and model.startswith("claude-"):
            return DGX_DEFAULT_MODEL
        return model

    def create(self, *, model, max_tokens, system, messages, tools=None, **_ignored):
        if tools:
            raise NotImplementedError(
                "tool use is not supported on the DGX endpoint — drop --dgx-endpoint "
                "for paths that need tools (e.g. enhance_recap with tools enabled)."
            )
        resp = self._client.oai.chat.completions.create(
            model=self._resolve_model(model),
            max_tokens=max_tokens,
            messages=_anthropic_to_openai_messages(system, messages),
        )
        text = resp.choices[0].message.content or ""
        return _OpenAICompatResponse(text)

    def stream(self, *, model, max_tokens, system, messages, **_ignored):
        return _OpenAICompatStream(
            self._client.oai,
            model=self._resolve_model(model),
            max_tokens=max_tokens,
            messages=_anthropic_to_openai_messages(system, messages),
        )


class _OpenAICompatClient:
    """Anthropic-shaped façade over an OpenAI-compatible server (vLLM on the DGX, etc.).

    Supports only the call shapes used by stream_api / call_api: text-in, text-out,
    single-turn user message with an optional system prompt. Batching, tool use,
    and vision content are not implemented — those paths need the real Anthropic API.
    """

    def __init__(self, endpoint: str, model_override: str | None = None,
                 api_key: str = "not-needed"):
        try:
            from openai import OpenAI
        except ImportError:
            print("Error: openai not installed. Run: pip install openai", file=sys.stderr)
            sys.exit(1)
        # vLLM serves under /v1/. Accept both "http://host:port" and "http://host:port/v1".
        base_url = endpoint.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = base_url + "/v1"
        self.oai = OpenAI(base_url=base_url, api_key=api_key)
        self.model_override = model_override or os.environ.get("DGX_MODEL") or DGX_DEFAULT_MODEL
        self.messages = _OpenAICompatMessages(self)


def make_client(endpoint: str | None = None, model_override: str | None = None):
    """Return an LLM client.

    Default: an Anthropic client (existing behaviour).

    When `endpoint` (or the DGX_ENDPOINT env var) is set, returns a thin adapter
    that points at an OpenAI-compatible server — e.g. vLLM serving Qwen on the
    DGX Spark — and presents the small subset of the anthropic SDK surface that
    stream_api / call_api use. `model_override` (or DGX_MODEL env var) controls
    which model name is sent to that server; defaults to Qwen 2.5 14B AWQ.

    No fallback if the local endpoint is unreachable — the choice is explicit,
    and an obscured swap-back to Anthropic would defeat the point of pointing
    at the DGX in the first place.
    """
    endpoint = endpoint or os.environ.get("DGX_ENDPOINT")
    if endpoint:
        return _OpenAICompatClient(endpoint, model_override=model_override)
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


def call_api_with_tools(client, *, system: str, messages: list, tools: list,
                        model: str, max_tokens: int = 8192):
    """Non-streaming tool-use API call. Returns the raw Message response.

    Caller is responsible for the loop, message history, and dispatching
    tool_use blocks. Caller needs response.content (list of blocks),
    response.stop_reason, response.usage.

    Retries on transient errors (rate limit, overload, connection) with
    exponential backoff — same behaviour as call_api / stream_api.
    """
    import time
    delays = [10, 20, 40]
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [API unavailable — waiting {delay}s before retry {attempt}/{len(delays)}...]",
                  flush=True)
            time.sleep(delay)
        try:
            return client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools,
            )
        except Exception as e:
            if _is_retryable(e) and attempt < len(delays):
                continue
            raise


def stream_api(client, system, user: str, model: str, max_tokens: int = 8096,
               silent: bool = False, verbose: bool = False,
               cache_system: bool = False) -> str:
    """Stream a Claude API call, printing each token as it arrives. Returns full response.

    Retries on transient errors (rate limit, overload, connection) with exponential backoff
    (up to 4 attempts). Pass silent=True to suppress all output (useful for
    filter/classification passes). Pass verbose=True to print the system and user prompts
    before calling.

    system — string, or a pre-built list of content blocks (for callers that want to
             control caching breakpoints precisely).
    cache_system — when True and `system` is a string, wrap it in a single
             cache_control: ephemeral block so subsequent calls with the same prefix
             get the prompt-cache discount. Useful when a large fixed context (e.g.
             a full VTT transcript) is reused across many short calls.
    """
    if verbose:
        print("\n" + "▲" * 60)
        print("SYSTEM PROMPT:")
        print(system if isinstance(system, str) else _render_system_blocks_for_log(system))
        print("─" * 60)
        print("USER PROMPT:")
        print(user)
        print("▲" * 60 + "\n")
    import time

    if cache_system and isinstance(system, str):
        system_arg = [{"type": "text", "text": system,
                       "cache_control": {"type": "ephemeral"}}]
    else:
        system_arg = system

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
                system=system_arg,
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


# ── Batch API ─────────────────────────────────────────────────────────────────
#
# Anthropic's Message Batches API charges 50% of list price for any request
# that completes within its 24-hour SLA, and honours prompt caching the same
# way live calls do. Our session-prep workflow has a human review step after
# each LLM stage, so giving up live token streaming in exchange for the 50%
# discount is a clean trade — but only when the user explicitly asks (`--batch`).
#
# The helpers below are pure orchestration: they don't know what the prompts
# are, just how to build a Request, submit a batch, poll for completion, and
# stream the results back. Prompt assembly stays in the calling script.


def build_batch_request(
    *,
    custom_id: str,
    system: str,
    user: str,
    model: str,
    max_tokens: int = 8192,
    cache_system: bool = False,
) -> dict:
    """Build one Request entry for `client.messages.batches.create(requests=...)`.

    Mirrors the system/messages shape `stream_api` constructs, including the
    optional `cache_control: ephemeral` block on the system prompt so the
    cache breakpoint is identical between live and batched paths.
    """
    if cache_system:
        system_arg = [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }]
    else:
        system_arg = system

    return {
        "custom_id": custom_id,
        "params": {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_arg,
            "messages": [{"role": "user", "content": user}],
        },
    }


def submit_batch(client, requests: list[dict]) -> str:
    """Submit `requests` as a single Message Batch. Returns the batch ID.

    Retries on transient errors using the same predicate as the streaming path.
    """
    if not requests:
        raise ValueError("submit_batch: requests list is empty")
    delays = [10, 20, 40]
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [Batch submit unavailable — waiting {delay}s before retry "
                  f"{attempt}/{len(delays)}...]", flush=True)
            time.sleep(delay)
        try:
            batch = client.messages.batches.create(requests=requests)
            return batch.id
        except Exception as e:
            if _is_retryable(e) and attempt < len(delays):
                continue
            raise


def poll_batch(client, batch_id: str, *, interval: int = 10, on_tick=None,
               max_wait: int | None = None):
    """Poll until the batch's `processing_status == 'ended'`.

    `on_tick(batch)` is called after each retrieve so the caller can print
    progress (`batch.request_counts.processing/succeeded/errored/...`).
    Returns the final batch object.

    Retries transient retrieve errors. `max_wait` is in seconds; None means
    wait up to the API's 24-hour SLA.
    """
    waited = 0
    delays = [10, 20, 40]
    while True:
        for attempt, delay in enumerate([-1] + delays):
            if delay >= 0:
                print(f"\n  [Batch retrieve unavailable — waiting {delay}s "
                      f"before retry {attempt}/{len(delays)}...]", flush=True)
                time.sleep(delay)
            try:
                batch = client.messages.batches.retrieve(batch_id)
                break
            except Exception as e:
                if _is_retryable(e) and attempt < len(delays):
                    continue
                raise
        if on_tick:
            try:
                on_tick(batch)
            except Exception:
                pass
        if getattr(batch, "processing_status", None) == "ended":
            return batch
        if max_wait is not None and waited >= max_wait:
            raise TimeoutError(
                f"Batch {batch_id} did not finish within {max_wait}s "
                f"(status: {batch.processing_status})"
            )
        time.sleep(interval)
        waited += interval


def collect_batch(client, batch_id: str) -> dict[str, dict]:
    """Stream the batch's results back into a dict keyed by `custom_id`.

    Each value: `{"status": "succeeded" | "errored" | "canceled" | "expired",
                  "text": str | None, "error": str | None,
                  "usage": dict | None}`.

    `text` is populated only for succeeded results. The caller is responsible
    for deciding what to do with non-succeeded entries (typically: print the
    error message and let the user re-run; sidecar files stay on disk so a
    subsequent `--collect` can retry).
    """
    delays = [10, 20, 40]
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [Batch results unavailable — waiting {delay}s before retry "
                  f"{attempt}/{len(delays)}...]", flush=True)
            time.sleep(delay)
        try:
            stream = client.messages.batches.results(batch_id)
            break
        except Exception as e:
            if _is_retryable(e) and attempt < len(delays):
                continue
            raise

    out: dict[str, dict] = {}
    for entry in stream:
        custom_id = getattr(entry, "custom_id", None)
        result = getattr(entry, "result", None)
        if custom_id is None or result is None:
            continue
        result_type = getattr(result, "type", None)
        record: dict = {"status": result_type, "text": None,
                        "error": None, "usage": None}
        if result_type == "succeeded":
            message = getattr(result, "message", None)
            if message is not None:
                blocks = getattr(message, "content", []) or []
                text_parts = [getattr(b, "text", "") for b in blocks
                              if getattr(b, "type", None) == "text"]
                record["text"] = "".join(text_parts)
                usage = getattr(message, "usage", None)
                if usage is not None:
                    record["usage"] = {
                        "input_tokens": getattr(usage, "input_tokens", None),
                        "output_tokens": getattr(usage, "output_tokens", None),
                        "cache_creation_input_tokens":
                            getattr(usage, "cache_creation_input_tokens", None),
                        "cache_read_input_tokens":
                            getattr(usage, "cache_read_input_tokens", None),
                    }
        elif result_type == "errored":
            err = getattr(result, "error", None)
            record["error"] = (
                getattr(getattr(err, "error", None), "message", None)
                or str(err)
            )
        else:
            record["error"] = f"result type: {result_type}"
        out[custom_id] = record
    return out


def write_batch_sidecar(path: Path, payload: dict) -> None:
    """Persist batch metadata (id, model, custom_ids, etc.) for later --collect."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def read_batch_sidecar(path: Path) -> dict:
    """Read a sidecar previously written by `write_batch_sidecar`."""
    if not path.exists():
        print(f"Error: batch sidecar not found: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_batch_progress(batch) -> str:
    """One-line summary like '[batch ... | 4/8 succeeded | 1 processing]'."""
    counts = getattr(batch, "request_counts", None)
    if counts is None:
        return f"[batch {batch.id} | status: {batch.processing_status}]"
    succeeded = getattr(counts, "succeeded", 0) or 0
    errored = getattr(counts, "errored", 0) or 0
    canceled = getattr(counts, "canceled", 0) or 0
    expired = getattr(counts, "expired", 0) or 0
    processing = getattr(counts, "processing", 0) or 0
    total = succeeded + errored + canceled + expired + processing
    parts = [f"[batch {batch.id}", f"{succeeded}/{total} succeeded"]
    if processing:
        parts.append(f"{processing} processing")
    if errored:
        parts.append(f"{errored} errored")
    if canceled:
        parts.append(f"{canceled} canceled")
    if expired:
        parts.append(f"{expired} expired")
    return " | ".join(parts) + "]"


def _render_system_blocks_for_log(blocks) -> str:
    if not isinstance(blocks, list):
        return str(blocks)
    parts = []
    for b in blocks:
        if isinstance(b, dict) and "text" in b:
            cache = " [cached]" if b.get("cache_control") else ""
            parts.append(f"<block{cache}>\n{b['text']}\n</block>")
        else:
            parts.append(str(b))
    return "\n".join(parts)


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
