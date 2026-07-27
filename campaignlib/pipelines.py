"""Chunk-and-extract and load-and-synthesize pipeline orchestrators."""

import sys
from pathlib import Path

from .textproc import prepare_chunks
from .api.client import stream_api
from .api.batch import build_batch_request, run_batch, run_single_batch
from .util import atomic_write_text as _atomic_write_text

# Default per-chunk extraction output budget — matches stream_api's own
# default. Most extract_system prompts produce compact notes well under this;
# callers whose notes run longer (e.g. distill.py's citation-bearing bullets,
# which roughly double each line's length) pass a larger `max_tokens`.
EXTRACT_MAX_TOKENS = 8096

# Output budget for extract prompts that embed citation_rules_extract.md —
# per-bullet `[cite: "..."]` tags roughly double a bullet's length over the
# plain-prose EXTRACT_MAX_TOKENS default. Callers pass this explicitly as
# `max_tokens`; it does not change run_extract_pipeline's own default.
CITED_EXTRACT_MAX_TOKENS = 32000

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
    batch: bool = False,
) -> list[Path] | list[str]:
    """Chunk `text`, run `extract_system` against each chunk, cache each result to `extract_dir`.

    Files are named via `filename_template` (default `extract_NNN.md`; `{i}` is
    the 1-indexed chunk number). Existing files are skipped so a partial run
    can be resumed.

    Return value depends on `batch`:
      batch=False (default) — returns the ordered list[Path] of output paths
        (including skipped ones), unchanged from before this parameter existed
        (FR-011: byte-identical behavior when --batch is absent).
      batch=True — returns list[str], the custom_ids of chunks whose batch
        item did NOT succeed (empty list on full success). Callers that need
        the ordered list[Path] of extracted files should re-glob `extract_dir`
        after checking this list is empty (see `resolve_extract_output`).

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
    batch            — when True, submit every not-yet-extracted chunk as one
                       Message Batch (`run_batch`) instead of the serial
                       stream_api loop (FR-006). The missing-chunk set is
                       computed with the identical skip-if-exists check used
                       by the serial path, BEFORE any request is built — a
                       fully-cached re-run submits nothing. Each request's
                       `custom_id` is the chunk's output filename stem, so
                       results map back to paths deterministically. Successful
                       items are written atomically (tmp + os.replace) so a
                       killed process never leaves a torn chunk file; a
                       `FAILED <custom_id>: <status> <error>` line is printed
                       to stderr for every non-succeeded item.
    """
    if input_normalizer:
        text = input_normalizer(text)
    if system_suffix:
        extract_system = extract_system + "\n\n" + system_suffix

    chunks, label = prepare_chunks(text, chunk_size, split_chapters, split_label=split_label)
    total = len(chunks)
    extract_dir.mkdir(parents=True, exist_ok=True)

    if not batch:
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

    # ── batch mode ────────────────────────────────────────────────────────
    # Missing-chunk set computed BEFORE any request is built (Constitution
    # VII) — identical skip-if-exists check as the serial loop above.
    missing: list[tuple[Path, str]] = []
    for i, chunk in enumerate(chunks, 1):
        out_file = extract_dir / filename_template.format(i=i)
        if out_file.exists():
            print(f"  [{i}/{total}] Skipping (already exists): {out_file.name}")
            continue
        missing.append((out_file, chunk))

    if not missing:
        print(f"  All {total} {label}(s) already extracted — nothing to submit.")
        return []

    requests = [
        build_batch_request(
            custom_id=out_file.stem,
            system=extract_system,
            user=chunk,
            model=model,
            max_tokens=max_tokens,
        )
        for out_file, chunk in missing
    ]
    print(f"  Submitting {len(requests)} of {total} {label}(s) as one batch...")
    results = run_batch(client, requests, label=label)

    by_id = {out_file.stem: out_file for out_file, _ in missing}
    failed: list[str] = []
    for custom_id, record in results.items():
        out_file = by_id.get(custom_id)
        if record["status"] != "succeeded":
            failed.append(custom_id)
            print(f"FAILED {custom_id}: {record['status']} {record.get('error')}",
                  file=sys.stderr)
            continue
        if out_file is not None:
            _atomic_write_text(out_file, record["text"])
            print(f"  Saved: {out_file.name}")

    return failed


def resolve_extract_output(result, *, batch: bool, extract_dir: Path,
                           pattern: str = "extract_*.md") -> list[Path]:
    """Normalize `run_extract_pipeline`'s return value across modes for callers.

    batch=False — `result` is already the ordered list[Path]
      `run_extract_pipeline` returns; passed through unchanged.

    batch=True — `result` is the list of failed custom_ids.
      * Non-empty: at least one chunk's batch item did not succeed (its
        `FAILED <custom_id>: ...` line was already printed by
        `run_extract_pipeline`). Prints a summary and exits the process
        (successful chunks are already saved to disk — only the missing ones
        need a re-run).
      * Empty: full success. `run_extract_pipeline`'s batch branch does not
        reconstruct the ordered Path list itself (only the failure set), so
        this re-globs `extract_dir` for it — the same pattern the CLIs
        already use for `--synthesize-only`.
    """
    if not batch:
        return result
    failed = result
    if failed:
        print(f"Error: {len(failed)} extraction chunk(s) failed in the batch "
              f"(see FAILED lines above). Successful chunks are saved in "
              f"{extract_dir} — re-run with --batch to retry only the missing "
              f"one(s).", file=sys.stderr)
        sys.exit(1)
    return sorted(extract_dir.glob(pattern))


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
    batch: bool = False,
) -> str:
    """Concat labeled file groups into a user prompt, call `stream_api`, return the response.

    max_tokens     — output-token ceiling for the synthesis call (default
                     `SYNTHESIS_MAX_TOKENS`). Whole-document synthesis needs far
                     more headroom than per-chunk extraction; a ceiling, not a
                     target — it permits a longer document, it does not force one.

    batch          — when True, route the single synthesis call through
                     `run_single_batch` instead of live `stream_api` (same
                     system/user/model/max_tokens) — the 50% Message Batches
                     discount, one-item batch. Raises `RuntimeError` if that
                     item does not succeed (single-call CLIs have no
                     unit<->file map to report a partial failure against).

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
    if batch:
        result = run_single_batch(client, system=synthesize_system, user=user_prompt,
                                  model=model, max_tokens=max_tokens)
    else:
        result = stream_api(client, synthesize_system, user_prompt, model, max_tokens=max_tokens)
    print("  " + "─" * 56)
    return result
