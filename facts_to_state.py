#!/usr/bin/env python3
"""Aggregate exhaustive atomic facts into per-entity current-state dossiers.

The ensemble (`ensemble_extract.py`) produces tens of thousands of atomic
facts — far too many to feed `synthesise_world_state.py` directly. This script
is the missing COMPRESSION layer: it bundles every fact about one entity and
asks a local model to collapse them into a single current-state dossier
(`distill_extractions` density), with an explicit Uncertainty block so a human
can correct scope/ordering/attribution before the dossiers feed synthesis.

Two stages:

  1. BUNDLE (deterministic, no LLM): group facts by (type, canonical subject),
     ordered by CHAPTER index (not in-world date), keeping only "stateful"
     entity types above a fact-count floor. `--list` stops here so you can see
     exactly what will be aggregated — the human checkpoint on scope.

  2. AGGREGATE (local model): per entity, feed its facts in chapter order to the
     `state_aggregate` prompt -> one dossier .md per entity in --out-dir.

Examples:
  # See the bundles (no model call) — sorted by fact count
  python facts_to_state.py --corpus 'scratch_output/full-oota/gen-ch*/merged.json' --list

  # Prototype: aggregate one dense entity on the local Spark
  python facts_to_state.py --corpus 'scratch_output/full-oota/gen-ch*/merged.json' \
      --only Daz --out-dir scratch_output/state-proto \
      --dgx-endpoint http://192.168.1.147:8001/v1 \
      --model Qwen/Qwen3-Next-80B-A3B-Instruct-FP8

  # Top 10 densest entities
  python facts_to_state.py --corpus '...' --top 10 --out-dir scratch_output/state-proto \
      --dgx-endpoint http://192.168.1.147:8001/v1 --model Qwen/...
"""

import argparse
import json
import queue
import re
import sys
import threading
from collections import Counter
from pathlib import Path

from campaignlib import (
    DEFAULT_MODEL,
    load_agent_prompt,
    make_client,
    stream_api,
)
from ensemble_merge import _norm_subject
from synthesise_world_state import (
    expand_globs,
    load_aliases,
    session_index,
    session_label,
)

AGGREGATE_SYSTEM = load_agent_prompt("state_aggregate")

# Entity types worth aggregating into a state model. event/date/thread are
# cross-cutting (history / temporal anchors / mysteries) and handled on a
# separate track, not per-entity.
STATEFUL_TYPES = ["npc", "faction", "location", "object", "monster"]

_INT_RE = re.compile(r"\d+")


def chapter_num(path: Path) -> int:
    """Integer chapter index from a merged.json's label (gen-ch03 -> 3)."""
    nums = _INT_RE.findall(session_label(path))
    return int(nums[0]) if nums else 0


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "entity"


class Bundle:
    """All facts about one (type, canonical-subject), in chapter order."""

    def __init__(self, type_: str, key: str):
        self.type = type_
        self.key = key
        # Internally a 3-tuple: (chapter, fact, location_or_None).
        # The location is the dominant location of the chapter the fact came
        # from — used only by split_bundle_by_location; ignored elsewhere.
        self.facts: list[tuple[int, dict, str | None]] = []
        self._names: Counter = Counter()

    def add(self, chapter: int, fact: dict, display: str,
            location: str | None = None) -> None:
        self.facts.append((chapter, fact, location))
        self._names[display] += 1

    @property
    def display(self) -> str:
        return self._names.most_common(1)[0][0]

    @property
    def chapters(self) -> tuple[int, int]:
        chs = [c for c, _, _l in self.facts]
        return (min(chs), max(chs))

    def ordered(self) -> list[tuple[int, dict]]:
        """Chapter-sorted (chapter, fact) pairs — backward-compatible API."""
        return [(ch, f) for ch, f, _ in sorted(self.facts, key=lambda t: t[0])]

    def ordered_with_location(self) -> list[tuple[int, dict, str | None]]:
        """Chapter-sorted (chapter, fact, location) triples."""
        return sorted(self.facts, key=lambda t: t[0])


def split_bundle_by_gap(b: Bundle, max_gap: int) -> list["Bundle"]:
    """Split b into sub-bundles wherever consecutive chapter numbers gap > max_gap.

    Named individuals typically appear across chapters with small gaps — the
    split leaves them intact. Generic labels ("orc", "guard") appear in
    encounter clusters separated by large gaps; each cluster becomes its own
    dossier so the LLM isn't asked to synthesize a single "state" for multiple
    unrelated individuals. Sub-bundles get a chapter-start suffix in both their
    key and display name so filenames are unique:
      npc_orc.md  →  npc_orc_ch01.md, npc_orc_ch23.md
    """
    ordered = b.ordered()
    if len(ordered) < 2:
        return [b]

    groups: list[list[tuple[int, dict]]] = []
    current: list[tuple[int, dict]] = [ordered[0]]
    for ch, f in ordered[1:]:
        if ch - current[-1][0] > max_gap:
            groups.append(current)
            current = [(ch, f)]
        else:
            current.append((ch, f))
    groups.append(current)

    if len(groups) == 1:
        return [b]

    result = []
    for group in groups:
        start_ch = group[0][0]
        suffix = f" ch{start_ch:02d}"
        new_b = Bundle(b.type, f"{b.key}ch{start_ch:02d}")
        for ch, f in group:
            new_b.add(ch, f, b.display + suffix)
        result.append(new_b)
    return result


_BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')


def _stem_words(filename_stem: str, min_len: int = 4) -> list[str]:
    """Normalised tokens from a snake_case filename stem, filtered by min length.

    "adabra"              -> ["adabra"]
    "harbin_wester"       -> ["harbin", "wester"]
    "falcon_the_hunter"   -> ["falcon", "hunter"]   ("the" is too short)
    "alphonse_big_al_x"   -> ["alphonse"]            ("big", "al", "x" too short)
    """
    return [_norm_subject(w) for w in filename_stem.split("_") if len(w) >= min_len]


def load_known_names(sources: list[Path]) -> set[str]:
    """Build a set of normalised names from inventory .md files and .dedup_state.json.

    Inventory markdown (.md):
      - Every **bold** span (proper names and aliases).
      - First word of each multi-word bold name when it is >= 4 chars, so that
        "Adabra Gwynn" also registers "adabra" (catching short-name fact subjects).

    dedup_state.json (.json):
      - Every string in clusters_confirmed[*].aliases_recorded.
      - Each canonical filename stem, split on _ and filtered to words >= 4 chars
        (e.g. "adabra.md" → "adabra"; "harbin_wester.md" → "harbin", "wester").
      - pc_files_skipped stems by the same rule, so PCs that were filtered from
        the dedup pass are still treated as known named individuals here.
    """
    known: set[str] = set()
    for src in sources:
        path = Path(src).expanduser().resolve()
        if not path.exists():
            print(f"  warn: known-names source not found: {path}", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            data = json.loads(text)
            for cluster in data.get("clusters_confirmed", []):
                for alias in cluster.get("aliases_recorded", []):
                    known.add(_norm_subject(alias))
                canon = cluster.get("canonical", "")
                stem = Path(canon).stem
                known.update(_stem_words(stem))
            for pc_file in data.get("pc_files_skipped", []):
                stem = Path(pc_file).stem
                known.update(_stem_words(stem))
        else:
            for m in _BOLD_RE.finditer(text):
                name = m.group(1).strip()
                if not name:
                    continue
                known.add(_norm_subject(name))
                # First word of multi-word names catches short-name fact subjects
                # (e.g. "Adabra" from "Adabra Gwynn").
                parts = name.split()
                if len(parts) > 1 and len(parts[0]) >= 4:
                    known.add(_norm_subject(parts[0]))
    return known


def load_bundles(corpus_paths: list[Path], aliases: dict[str, str],
                 types: list[str], split_gap: int | None = None,
                 known_names: set[str] | None = None) -> dict[str, Bundle]:
    """Group facts across all corpus files by (type, canonical subject).

    split_gap   — if set, gap-split bundles whose consecutive chapters exceed
                  this value (see split_bundle_by_gap). Still available but
                  superseded by known_names for most use cases.

    known_names — if set (built by load_known_names), entities whose normalised
                  subject is in this set get a global bundle keyed by
                  (type, subject) — normal behaviour. Entities NOT in the set
                  are anonymous/generic and get a location-scoped bundle keyed
                  by (type, subject, chapter_dominant_location). Each bundle
                  carries b.known = True/False so callers can skip synthesis
                  for unknowns with --known-only.
    """
    bundles: dict[str, Bundle] = {}
    type_set = set(types)
    for path in sorted(corpus_paths, key=session_index):
        ch = chapter_num(path)
        try:
            facts = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  warn: skipping {path}: {e}", file=sys.stderr)
            continue

        # Dominant location for this chapter — used to scope anonymous entities.
        if known_names is not None:
            loc_counts: Counter = Counter(
                f["subject"] for f in facts if f.get("type") == "location"
            )
            if loc_counts:
                top_raw, _ = loc_counts.most_common(1)[0]
                chapter_loc_norm = _norm_subject(top_raw)
                chapter_loc_display = top_raw
            else:
                chapter_loc_norm = None
                chapter_loc_display = None
        else:
            chapter_loc_norm = None
            chapter_loc_display = None

        for f in facts:
            t = f.get("type", "")
            if t not in type_set:
                continue
            raw = (f.get("subject") or "").strip()
            if not raw:
                continue
            display = aliases.get(raw, raw)
            norm = _norm_subject(display)
            if not norm:
                continue

            is_known = known_names is None or norm in known_names
            if is_known:
                gkey = f"{t}\x00{norm}"
                display_for_bundle = display
            else:
                # Location-scope anonymous entities so each encounter site gets
                # its own bundle rather than one omnibus dossier for all "orc"s.
                loc_key = chapter_loc_norm or "unknown"
                gkey = f"{t}\x00{norm}\x00{loc_key}"
                loc_label = chapter_loc_display or "unknown location"
                display_for_bundle = f"{display} ({loc_label})"

            b = bundles.get(gkey)
            if b is None:
                b = bundles[gkey] = Bundle(t, norm)
                b.known = is_known  # type: ignore[attr-defined]
            b.add(ch, f, display_for_bundle, location=chapter_loc_norm)

    if split_gap is not None:
        expanded: dict[str, Bundle] = {}
        for b in bundles.values():
            for sub in split_bundle_by_gap(b, split_gap):
                sub.known = getattr(b, "known", True)  # type: ignore[attr-defined]
                expanded[f"{sub.type}\x00{sub.key}"] = sub
        return expanded

    return bundles


def select(bundles: dict[str, Bundle], min_facts: int, only: str | None,
           top: int | None, known_only: bool = False) -> list[Bundle]:
    items = [b for b in bundles.values() if len(b.facts) >= min_facts]
    if known_only:
        items = [b for b in items if getattr(b, "known", True)]
    if only is not None:
        target = _norm_subject(only)
        items = [b for b in items if b.key == target or b.key.startswith(target + "\x00")]
    items.sort(key=lambda b: (-len(b.facts), b.type, b.display.lower()))
    if top is not None:
        items = items[:top]
    return items


def build_user_prompt(b: Bundle, with_quotes: bool) -> str:
    lo, hi = b.chapters
    span = f"chapter {lo}" if lo == hi else f"chapters {lo}-{hi}"
    head = (f"ENTITY: {b.display}   (type: {b.type})\n"
            f"{len(b.facts)} fact(s) across {span}.\n\n"
            "FACTS (chronological — earliest chapter first; later overrides "
            "earlier for current state):\n")
    lines = [head]
    for ch, f in b.ordered():
        lines.append(f"- [ch{ch:02d}] {f.get('fact', '').strip()}")
        if with_quotes:
            q = " ".join((f.get("source_quote") or "").split())
            if q:
                lines.append(f'  > "{q}"')
    return "\n".join(lines)


def dossier_path(out_dir: Path, b: Bundle) -> Path:
    return out_dir / f"{b.type}_{slugify(b.display)}.md"


def render_bundles(bundles: list[Bundle], with_quotes: bool) -> str:
    """Deterministic markdown dump of bundles, grouped by type then subject,
    facts in chapter order. Used for the cross-cutting threads/events track —
    facts that don't aggregate per-entity but feed the synthesis directly."""
    by_type: dict[str, list[Bundle]] = {}
    for b in bundles:
        by_type.setdefault(b.type, []).append(b)
    out: list[str] = []
    for t in sorted(by_type):
        out.append(f"## {t.title()}s\n")
        for b in sorted(by_type[t], key=lambda b: b.display.lower()):
            out.append(f"### {b.display}")
            for ch, f in b.ordered():
                out.append(f"- [ch{ch:02d}] {f.get('fact', '').strip()}")
                if with_quotes:
                    q = " ".join((f.get("source_quote") or "").split())
                    if q:
                        out.append(f'  > "{q}"')
            out.append("")
    return "\n".join(out)


def write_dossier(out_dir: Path, b: Bundle, body: str) -> Path:
    lo, hi = b.chapters
    fm = (f"---\nname: {b.display}\ntype: {b.type}\n"
          f"n_facts: {len(b.facts)}\nchapters: {lo}-{hi}\n---\n\n")
    dest = dossier_path(out_dir, b)
    dest.write_text(fm + body.strip() + "\n", encoding="utf-8")
    return dest


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus", required=True, nargs="+", metavar="GLOB",
                   help="merged.json glob(s) (e.g. 'scratch_output/full-oota/gen-ch*/merged.json')")
    p.add_argument("--out-dir", metavar="DIR",
                   help="Where to write per-entity dossiers (required unless --list)")
    p.add_argument("--aliases", metavar="FILE", default=None,
                   help="aliases.json ({canonical: [variants]}) for subject canonicalisation")
    p.add_argument("--types", nargs="+", default=STATEFUL_TYPES, metavar="TYPE",
                   help=f"Entity types to aggregate (default: {' '.join(STATEFUL_TYPES)})")
    p.add_argument("--min-facts", type=int, default=3, metavar="N",
                   help="Only aggregate entities with at least N facts (default 3); "
                        "below this there's nothing to collapse.")
    p.add_argument("--split-gap", type=int, default=None, metavar="N",
                   help="Split any bundle whose consecutive-chapter gap exceeds N "
                        "into separate sub-bundles. Heuristic fallback; prefer "
                        "--known-names for campaigns with inventory files.")
    p.add_argument("--known-names", nargs="+", default=None, metavar="FILE",
                   help="One or more inventory .md files (bold-marked proper nouns) "
                        "and/or .dedup_state.json files. Entities whose normalised "
                        "name appears in any of these are treated as named "
                        "individuals (global bundle, full dossier). Everything else "
                        "is anonymous and scoped to the chapter's dominant location "
                        "(e.g. 'orc' becomes 'Orc (Phandalin)', 'Orc (Wayside Inn)'). "
                        "Use --known-only to skip synthesis for anonymous bundles.")
    p.add_argument("--known-only", action="store_true",
                   help="With --known-names: synthesize dossiers only for known "
                        "(named) entities; print anonymous bundles in --list but "
                        "skip them for LLM aggregation. They remain available for "
                        "a later dedup pass.")
    p.add_argument("--only", metavar="NAME", default=None,
                   help="Aggregate only the entity whose normalised name matches NAME (prototype).")
    p.add_argument("--top", type=int, default=None, metavar="N",
                   help="Aggregate only the N densest entities (prototype).")
    p.add_argument("--list", action="store_true",
                   help="Stage 1 only: print the selected bundles (no model call). "
                        "The human checkpoint on what will be aggregated.")
    p.add_argument("--render-only", metavar="FILE", default=None,
                   help="Deterministic dump of the selected bundles to FILE as "
                        "grouped markdown (no model call). Used to build the "
                        "cross-cutting threads/events track for synthesis "
                        "(e.g. --types thread --min-facts 2 --render-only threads.md).")
    p.add_argument("--quotes", action=argparse.BooleanOptionalAction, default=True,
                   help="Include source_quote lines in the model input (default on).")
    p.add_argument("--dgx-endpoint", default=None, metavar="URL",
                   help="Single OpenAI-compatible local endpoint (else Anthropic API).")
    p.add_argument("--endpoints", nargs="+", default=None, metavar="URL",
                   help="Multiple endpoints to fan out across concurrently (one worker per "
                        "endpoint, work-stealing). Overrides --dgx-endpoint. All must serve --model.")
    p.add_argument("--model", default=None, metavar="ID",
                   help=f"Model id (default: $DGX_MODEL on a DGX endpoint, else {DEFAULT_MODEL}).")
    p.add_argument("--max-tokens", type=int, default=8000, metavar="N",
                   help="max_tokens per aggregation call (default 8000).")
    args = p.parse_args()

    if not args.list and not args.render_only and not args.out_dir:
        p.error("--out-dir is required unless --list / --render-only")

    corpus = expand_globs(args.corpus)
    if not corpus:
        print("Error: no corpus files matched.", file=sys.stderr)
        sys.exit(1)
    aliases = load_aliases(Path(args.aliases).expanduser()) if args.aliases else {}

    known_names: set[str] | None = None
    if args.known_names:
        known_names = load_known_names([Path(p) for p in args.known_names])
        print(f"Known names: {len(known_names)} normalised entries from "
              f"{len(args.known_names)} source(s)")

    bundles = load_bundles(corpus, aliases, args.types, split_gap=args.split_gap,
                           known_names=known_names)
    selected = select(bundles, args.min_facts, args.only, args.top,
                      known_only=args.known_only)

    total_entities = len(bundles)
    n_known   = sum(1 for b in bundles.values() if getattr(b, "known", True))
    n_unknown = total_entities - n_known
    scope_note = (f"  ({n_known} known / {n_unknown} location-scoped)"
                  if known_names is not None else "")
    split_note = f", gap-split >{args.split_gap}" if args.split_gap else ""
    print(f"Corpus:   {len(corpus)} file(s)")
    print(f"Entities: {total_entities} of types {args.types}{split_note}{scope_note} "
          f"(>= {args.min_facts} facts: {sum(1 for b in bundles.values() if len(b.facts) >= args.min_facts)})")
    print(f"Selected: {len(selected)} for aggregation"
          + (" (known-only)" if args.known_only else ""))
    print("=" * 60)

    if args.render_only:
        md = render_bundles(selected, args.quotes)
        dest = Path(args.render_only).expanduser().resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(md, encoding="utf-8")
        print(f"Rendered {len(selected)} bundle(s) -> {dest} "
              f"(~{len(md)//4:,} tokens)")
        return

    if args.list or not selected:
        show_all = args.list and not args.known_only and known_names is not None
        # When --known-names is active, show unknown entities too so the human
        # can see what got location-scoped (even if they won't be synthesized).
        list_items = selected
        if show_all:
            unseen_keys = {id(b) for b in selected}
            extras = [b for b in bundles.values()
                      if not getattr(b, "known", True)
                      and len(b.facts) >= args.min_facts
                      and id(b) not in unseen_keys]
            extras.sort(key=lambda b: (-len(b.facts), b.type, b.display.lower()))
            list_items = selected + extras
        for b in list_items:
            lo, hi = b.chapters
            tag = "" if known_names is None else ("[known]   " if getattr(b, "known", True) else "[location]")
            print(f"  {tag}{len(b.facts):>5}  {b.type:9s}  {b.display}  (ch {lo}-{hi})")
        if not selected:
            print("(nothing selected)")
        return

    model = args.model
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resumable: skip entities whose dossier already exists (survives sleeps /
    # interrupts; re-run to fill in the rest).
    todo = [b for b in selected if not dossier_path(out_dir, b).exists()]
    already = len(selected) - len(todo)

    endpoints = args.endpoints or [args.dgx_endpoint]
    where = ", ".join(e or "Anthropic API" for e in endpoints)
    print(f"Aggregating {len(todo)} entitie(s) on {where} (model: {model or 'default'})"
          f"{f'; {already} already done (skipped)' if already else ''}\n")

    work: queue.Queue = queue.Queue()
    for item in enumerate(todo, 1):
        work.put(item)
    lock = threading.Lock()
    done = 0
    errors: list[str] = []

    def worker(endpoint: str | None) -> None:
        nonlocal done
        client = make_client(endpoint=endpoint, model_override=model)
        while True:
            try:
                i, b = work.get_nowait()
            except queue.Empty:
                return
            try:
                user = build_user_prompt(b, args.quotes)
                body = stream_api(client, AGGREGATE_SYSTEM, user, model,
                                  max_tokens=args.max_tokens, silent=True)
                write_dossier(out_dir, b, body)
                with lock:
                    done += 1
                    print(f"[{done}/{len(todo)}] {b.type}: {b.display} "
                          f"({len(b.facts)} facts) -> {dossier_path(out_dir, b).name}")
            except Exception as e:  # one bad entity must not kill the batch
                with lock:
                    errors.append(f"{b.type}:{b.display}: {e!r}")
                    print(f"  ERROR {b.type}: {b.display}: {e!r}", file=sys.stderr)

    threads = [threading.Thread(target=worker, args=(ep,), daemon=True) for ep in endpoints]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"\nWrote {done} dossier(s) to {out_dir} ({already} pre-existing)")
    if errors:
        print(f"{len(errors)} entitie(s) failed (re-run to retry):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
    print("REVIEW these (esp. the ## Uncertainty blocks) before synthesis.")


if __name__ == "__main__":
    main()
