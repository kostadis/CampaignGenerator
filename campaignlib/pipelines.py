"""Chunk-and-extract and load-and-synthesize pipeline orchestrators."""

import sys
from pathlib import Path

from .textproc import prepare_chunks
from .api.client import stream_api

# Default per-chunk extraction output budget — matches stream_api's own
# default. Most extract_system prompts produce compact notes well under this;
# callers whose notes run longer (e.g. distill.py's citation-bearing bullets,
# which roughly double each line's length) pass a larger `max_tokens`.
EXTRACT_MAX_TOKENS = 8096

# Whole-document synthesis needs a far larger output budget than per-chunk
# extraction: a full campaign_state.md / world_state.md legitimately exceeds
# EXTRACT_MAX_TOKENS. 32000 is well under the output ceiling of the synthesis
# models (opus-4-8 / sonnet-4-6) and is accepted by claude -p via
# CLAUDE_CODE_MAX_OUTPUT_TOKENS.
SYNTHESIS_MAX_TOKENS = 32000


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
    max_tokens: int = EXTRACT_MAX_TOKENS,
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
    max_tokens       — output-token ceiling for each extraction call (default
                       `EXTRACT_MAX_TOKENS`). Raise it for extract prompts whose
                       notes run long relative to the source (e.g. per-bullet
                       citations). On the claude-code (subscription) backend,
                       hitting the ceiling is a hard error with no partial
                       text, unlike the Anthropic API's graceful truncation —
                       so a too-low ceiling fails the whole chunk outright.
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
        result = stream_api(client, extract_system, chunk, model, max_tokens=max_tokens)
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
    max_tokens: int = SYNTHESIS_MAX_TOKENS,
    source_label: str = "Source",
    group_separator: str = "\n\n===\n\n",
    file_separator: str = "\n\n---\n\n",
    input_normalizer=None,
    system_suffix: str = "",
    dump_input: str | None = None,
    dump_only: bool = False,
) -> str:
    """Concat labeled file groups into a user prompt, call `stream_api`, return the response.

    max_tokens     — output-token ceiling for the synthesis call (default
                     `SYNTHESIS_MAX_TOKENS`). Whole-document synthesis needs far
                     more headroom than per-chunk extraction; a ceiling, not a
                     target — it permits a longer document, it does not force one.

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
    dump_input       — if set, write the assembled user prompt to this path and
                       the system prompt to <path>.system.md (for `claude -p`).
    dump_only        — with dump_input: skip the API call and return "".
                       Callers should guard: `if dump_only: return` before writing output.
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

    if dump_input:
        dump_path = Path(dump_input).expanduser().resolve()
        dump_path.write_text(user_prompt, encoding="utf-8")
        system_path = dump_path.with_suffix(dump_path.suffix + ".system.md")
        system_path.write_text(synthesize_system, encoding="utf-8")
        print(f"Dumped synthesis input: {dump_path}")
        print(f"Dumped system prompt:   {system_path}")
        if dump_only:
            print("[--dump-only: stopping before the API call]")
            return ""

    print(f"  Synthesizing {total_files} source file(s) ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, synthesize_system, user_prompt, model, max_tokens=max_tokens)
    print("  " + "─" * 56)
    return result
