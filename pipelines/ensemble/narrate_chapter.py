#!/usr/bin/env python3
"""Render a chapter into a plain-prose narrative — a SIBLING artifact to
``merged.json``, not a sixth extraction lens.

The five ``ensemble_extract.py`` passes (``PASSES``) each read a chapter,
chunk it, and emit fact-JSON validated against a fixed ``ALLOWED_TYPES`` —
atomic, decontextualized, and easy to dedupe/count. That atomization is also
the mechanism that loses attribution: "Thorin killed the pit fiend. Tadric
identified the dead fiend as Moziqodo, son of Sylvira Savikas" survives
fragmentation as three fact shards, and nothing downstream can prove they
describe the same corpse (issue #195). This script exists to produce, once
per chapter, the plain statement of events the fragments were extracted
from — so a human reviewing 3-8 short scenes catches what nobody catches by
reading 15,000 facts.

Pipeline shape::

    chapter_NN.md
      -> chunk on the best available structural (scene) boundary, or fall
         back to character-count chunking for chapters with no headings
      -> one stream_api call per scene, rendering plain factual prose
         (config/agents/narrate_scene.md)
      -> concatenate scenes with headers into ONE narrative.md, written
         next to that chapter's merged.json

    narrative.md carries `approved: false` in YAML frontmatter by default.
    It is LLM output and needs a human checkpoint before synthesise_world_state
    (--narratives) will use it as grounding — see that script's docstring for
    the read side of this gate.

No fact-JSON schema, no ALLOWED_TYPES, no merge step: this is prose, and
forcing it into the fact schema (a `scene` type) would re-atomize it and
defeat the point.

Uses the same backend seam ensemble_extract.py / extract_facts.py already
use (--backend/--endpoint/--model via campaignlib.add_backend_args /
client_from_args / stream_api). No retry logic here — stream_api already
retries transient errors. --batch (Anthropic backend only) groups every
cache-miss scene into one Message Batch instead of calling stream_api per
scene, mirroring extract_facts.py's run_batched.

Usage::

    python narrate_chapter.py docs/chapters/chapter_62_the_key_is_secured.md \\
        --output docs/ensemble/per_chapter/chapter_62_the_key_is_secured/narrative.md

    # Preview the scene plan (labels, sizes, chunking convention) with no
    # model calls:
    python narrate_chapter.py chapter.md --output narrative.md --dry-run
"""

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

from campaignlib import (
    add_backend_args,
    build_batch_request,
    client_from_args,
    load_agent_prompt,
    prepare_chunks,
    run_batch,
    split_frontmatter,
    stream_api,
    utc_now_iso,
    wiring_get,
)
from campaignlib.api.client import resolve_cli_model
from campaignlib.util import atomic_write_text as _atomic_write_text

# Same two heading tiers chunk_by_scenes()/annotate_chunks_with_pov() scan
# for (campaignlib/textproc.py) — used here only to pull a human-readable
# label out of a chunk that already opens with its own heading. Matching
# EITHER tier (## or ###) is deliberate: a structural chunk opens with
# whichever tier chunk_by_scenes picked for this document, and we don't
# need to know which to label it.
_HEADING_RE = re.compile(r'^#{2,3}[ \t]+(.+?)[ \t]*$', re.MULTILINE)


def scene_label(chunk: str, index: int) -> str:
    """A human-readable label for one scene chunk.

    Structural chunks (chunk_by_scenes) open with their own heading line —
    use its text verbatim. Character-count fallback chunks (headerless
    chapters, or an oversized scene's tail sub-chunk) usually have none;
    "Scene N" is the honest fallback rather than guessing a title.
    """
    m = _HEADING_RE.search(chunk)
    if m:
        return m.group(1).strip()
    return f"Scene {index}"


def render_narrative_md(
    chapter_label: str,
    source_path: Path,
    scenes: list[tuple[str, str]],
    chunking: str,
) -> str:
    """Assemble the final narrative.md: YAML frontmatter + scene sections.

    `scenes` — [(label, rendered_prose), ...] in document order.
    `approved` is ALWAYS written `false` here — this function has no path
    that produces `true`; only a human editing the file after review does
    that. See `main()`'s approval-gate check for the read side.
    """
    frontmatter = {
        "chapter": chapter_label,
        "source": str(source_path),
        "generated_at": utc_now_iso(),
        "scenes": len(scenes),
        "chunking": chunking,
        "approved": False,
    }
    fm_text = yaml.safe_dump(frontmatter, sort_keys=False).strip()
    lines = [f"---\n{fm_text}\n---", "", f"# Narrative — {chapter_label}"]
    for i, (label, prose) in enumerate(scenes, 1):
        lines.append("")
        lines.append(f"## Scene {i} — {label}")
        lines.append("")
        lines.append(prose.strip())
    return "\n".join(lines).strip() + "\n"


def check_approval_gate(output_path: Path, force: bool) -> None:
    """Refuse to overwrite an approved narrative.md without --force.

    Regeneration produces genuinely different LLM output (the model call is
    nondeterministic) — silently PRESERVING a stale `approved: true` marker
    on new, unreviewed prose would misrepresent it as reviewed, which is
    worse than refusing. So: refuse by default, matching the repo's existing
    "refuse to clobber without --force" idiom (server/migrate_*.py). Checked
    BEFORE any model call, so a doomed run fails without spending tokens.
    """
    if not output_path.exists():
        return
    try:
        text = output_path.read_text(encoding="utf-8")
    except OSError:
        return
    frontmatter, _ = split_frontmatter(text)
    if frontmatter.get("approved") is True and not force:
        print(
            f"Error: {output_path} is marked 'approved: true' — refusing to "
            f"regenerate without --force (this would silently discard a "
            f"human review, and the new prose would NOT be re-reviewed). "
            f"Re-run with --force to overwrite it (the new file resets to "
            f"'approved: false'), or move the approved file aside first.",
            file=sys.stderr,
        )
        sys.exit(1)


def run_batched_scenes(
    chunks: list[str], cache_dir: Path, client, system_prompt: str,
    model: str, max_tokens: int,
) -> dict[int, str]:
    """Render cache-miss scenes through ONE grouped Message Batch (--batch).

    Mirrors extract_facts.py's run_batched contract (1-based {index: text}
    results against the same scene_NNN.txt cache names, so main()'s
    post-processing is identical regardless of which path filled the cache)
    but simpler: no JSON parsing, no per-item retry bookkeeping — the raw
    response text IS the rendered scene (this is prose, not fact-JSON; see
    the module docstring). Exits nonzero on the first failed item, same as
    extract_facts.py's batch path, since a partial narrative.md would be
    silently missing a scene.
    """
    results: dict[int, str] = {}
    missing: list[tuple[int, str, Path]] = []
    for i, chunk in enumerate(chunks, 1):
        cache_file = cache_dir / f"scene_{i:03d}.txt"
        if cache_file.exists():
            print(f"  [{i}/{len(chunks)}] Reusing cached: {cache_file.name}")
            results[i] = cache_file.read_text(encoding="utf-8")
        else:
            missing.append((i, chunk, cache_file))

    if not missing:
        print(f"  All {len(chunks)} scene(s) already rendered — nothing to submit.")
        return results

    requests = [
        build_batch_request(
            custom_id=cache_file.stem, system=system_prompt, user=chunk,
            model=model, max_tokens=max_tokens,
        )
        for _, chunk, cache_file in missing
    ]
    print(f"  Submitting {len(requests)} of {len(chunks)} scene(s) as one batch...")
    batch_results = run_batch(client, requests, label="narrate_chapter")

    by_id = {cache_file.stem: (i, cache_file) for i, _chunk, cache_file in missing}
    for custom_id, record in batch_results.items():
        entry = by_id.get(custom_id)
        if entry is None:
            continue
        i, cache_file = entry
        if record["status"] != "succeeded":
            print(f"Error: scene {i} ({cache_file.stem}) failed in the batch: "
                  f"{record['status']} {record.get('error')}", file=sys.stderr)
            sys.exit(1)
        prose = record["text"]
        _atomic_write_text(cache_file, prose)
        results[i] = prose
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render a chapter into a plain-prose narrative.md — a sibling "
            "artifact to merged.json, not a sixth extraction lens. Chunks on "
            "the best available scene/heading boundary (falling back to "
            "character-count chunking for headerless chapters), renders each "
            "scene as plain factual prose stating who did what and who died, "
            "and concatenates the result with an 'approved: false' YAML "
            "frontmatter gate. synthesise_world_state.py --narratives only "
            "consumes files flipped to 'approved: true' after human review."
        )
    )
    parser.add_argument("input", help="Chapter markdown file.")
    parser.add_argument(
        "--output", "-o", required=True, metavar="FILE",
        help="Where to write narrative.md. Required and never defaulted — "
             "conventionally next to that chapter's merged.json, e.g. "
             "docs/ensemble/per_chapter/<chapter>/narrative.md.")
    parser.add_argument(
        "--chunk-size", type=int, default=15000, metavar="CHARS",
        help="Max characters per scene (default: 15000, matching the "
             "ensemble's 'large' pass). Only bites when a structural scene "
             "exceeds it, or on the character-count fallback for headerless "
             "chapters — chunk_by_scenes sub-splits an oversized scene at "
             "this size rather than sending it to the model whole.")
    parser.add_argument(
        "--agent", default="narrate_scene", metavar="NAME",
        help="Agent prompt name to load from config/agents/ (default: "
             "narrate_scene).")
    parser.add_argument(
        "--model", default=None, metavar="ID",
        help="Model id to send to the endpoint (default: $DGX_MODEL or mneme "
             "wiring dgx_model, resolved by the dgx backend adapter, same as "
             "extract_facts.py).")
    parser.add_argument(
        "--max-tokens", type=int, default=4096, metavar="N",
        help="max_tokens per scene call (default: 4096). Scenes are prose, "
             "not JSON, so this is intentionally smaller than "
             "extract_facts.py's default.")
    parser.add_argument(
        "--cache-dir", default=None, metavar="DIR",
        help="Where to cache each rendered scene "
             "(default: <output_dir>/<output_stem>.scenes/). Re-running "
             "reuses a scene's cached prose instead of re-calling the model, "
             "mirroring extract_facts.py's per-chunk cache.")
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing narrative.md even if its frontmatter "
             "says 'approved: true'. Without this, an approved file refuses "
             "to regenerate (see check_approval_gate).")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the resolved scene plan (count, labels, sizes, chunking "
             "convention) and exit — no model calls, no output written.")
    add_backend_args(parser, default_backend="dgx")
    args = parser.parse_args()
    args.model = resolve_cli_model(
        args, legacy_default=None
    ).effective_model

    # Same fallback extract_facts.py uses: an explicit --endpoint always
    # wins; otherwise, only when the resolved backend really is "dgx" do we
    # fall through to DGX_ENDPOINT / mneme wiring (gating on that avoids
    # silently routing e.g. --backend anthropic at a stale DGX default).
    if args.backend == "dgx" and args.endpoint is None:
        args.endpoint = os.environ.get("DGX_ENDPOINT") or wiring_get("dgx_endpoint")

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not input_path.exists():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    text = input_path.read_text(encoding="utf-8")
    # Chapter identity frontmatter (issue #213) is metadata, not prose to
    # narrate.
    _, text = split_frontmatter(text)
    if not text.strip():
        print(f"Error: input file is empty: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Approval gate — checked before any chunking/model work.
    check_approval_gate(output_path, args.force)

    chunks, label = prepare_chunks(
        text, args.chunk_size, annotate_pov=True, structural=True)
    if not chunks:
        print(f"Error: no content to narrate in {input_path} "
              f"(chunking produced 0 chunks).", file=sys.stderr)
        sys.exit(1)

    chapter_label = input_path.stem
    print(f"[Narrate chapter | {input_path.name} | {len(chunks)} {label}(s) | "
          f"endpoint: {args.endpoint} | model: {args.model or 'default'}]")
    print("=" * 60)

    if args.dry_run:
        for i, chunk in enumerate(chunks, 1):
            print(f"  scene {i}: {scene_label(chunk, i)!r}  ({len(chunk):,} chars)")
        print(f"\n[dry-run] scene plan resolved ({label} chunking); "
              f"no model calls made, nothing written.")
        return

    system_prompt = load_agent_prompt(args.agent)
    client = client_from_args(args)

    cache_dir = (
        Path(args.cache_dir).expanduser().resolve() if args.cache_dir
        else output_path.parent / f"{output_path.stem}.scenes"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)

    if args.batch:
        scene_prose = run_batched_scenes(
            chunks, cache_dir, client, system_prompt, args.model, args.max_tokens)
        rendered = [(scene_label(chunk, i), scene_prose[i])
                   for i, chunk in enumerate(chunks, 1)]
    else:
        rendered = []
        for i, chunk in enumerate(chunks, 1):
            lbl = scene_label(chunk, i)
            cache_file = cache_dir / f"scene_{i:03d}.txt"
            if cache_file.exists():
                prose = cache_file.read_text(encoding="utf-8")
                print(f"  [{i}/{len(chunks)}] Reusing cached: {cache_file.name}")
            else:
                print(f"  [{i}/{len(chunks)}] Rendering scene {i} — {lbl!r} "
                      f"({len(chunk):,} chars)...")
                prose = stream_api(
                    client, system_prompt, chunk, args.model,
                    max_tokens=args.max_tokens, silent=True,
                )
                _atomic_write_text(cache_file, prose)
            rendered.append((lbl, prose))

    doc = render_narrative_md(chapter_label, input_path, rendered, label)
    _atomic_write_text(output_path, doc)

    print("\n" + "=" * 60)
    print(f"Wrote narrative: {output_path}")
    print(f"Scenes: {len(rendered)} ({label} chunking)")
    print(f"Scene cache: {cache_dir}")
    print("Approved: false — review the narrative, then flip 'approved: "
          "true' in its frontmatter before synthesise_world_state.py "
          "--narratives will use it.")


if __name__ == "__main__":
    main()
