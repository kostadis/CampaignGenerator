#!/usr/bin/env python3
"""Five-pass ensemble fact extractor.

Runs ``extract_facts.py`` five times against the same input, each with a
different lens, then merges the results deterministically.

Passes:

1. ``small``       — generalist prompt at 6,000-char chunks. Catches action
                     granularity (per-attack, per-spell, per-line-of-dialogue
                     detail) that larger chunks blur.
2. ``large``       — generalist prompt at 15,000-char chunks. Catches scene
                     setup, room descriptions, and cross-paragraph relations
                     that small chunks fragment.
3. ``sweep``       — sweep prompt at 15,000-char chunks. Exhaustive
                     proper-noun, object, and monster enumeration that the
                     generalist deprioritizes (Vof Klownits, Sava game,
                     Tongue of Madness, referenced-but-absent NPCs).
4. ``temporal``    — temporal/numeric anchor prompt at 15,000-char chunks.
                     Catches dates, counts, durations, distances, and
                     values that other passes drop ("5th day of 2nd Tenday
                     of Taraskh 1493", "100 feet above the cavern floor",
                     "eight days away via the Darklake").
5. ``interiority`` — character-interiority prompt at 15,000-char chunks.
                     Catches thoughts, feelings, memories, refusals, and
                     mutterings that action-focused passes skip ("Sarith
                     experiences bouts of madness", "Daz refused to wear
                     armor", "Grygum recalled the Giants").

Each pass writes its own ``facts_NNN.json`` cache under
``<workdir>/cache/<pass_name>/``. Re-runs reuse cached chunks, so iterating
on the merge step (or fixing one bad chunk) is cheap.

Merge is deterministic:

- Group facts by (type, normalized subject). Normalization is lowercase
  alphanumerics only, so "Bupido" and "Buppido" cluster together, as do
  "Ilvara's quarters" and "Ilvara’s quarters".
- Within each group, near-duplicate ``fact`` strings (SequenceMatcher
  ratio ≥ threshold) collapse into one entry; we keep the longest
  ``fact`` and the longest ``source_quote``.
- Each merged entry carries a ``passes`` list naming which input passes
  produced it. Facts present in all three passes are higher-confidence;
  facts unique to one pass are the recall-bonus from that lens.

This does NOT do cross-subject normalization (Velkenyvelve ↔
Velkynvelve, Sloopdopblop ↔ Sloobludop). Those phonetic-drift
clusters need a campaign-level name glossary, which is a deliberately
separate step.

Usage:

    python ensemble_extract.py session.md --workdir runs/session_001/

Re-run safely — caches make it cheap.
"""

import argparse
import json
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

EXTRACT_SCRIPT = Path(__file__).resolve().parent / "extract_facts.py"

PASSES = [
    {"name": "small",       "chunk_size": 6000,  "agent": "extract_facts"},
    {"name": "large",       "chunk_size": 15000, "agent": "extract_facts"},
    {"name": "sweep",       "chunk_size": 15000, "agent": "extract_facts_sweep"},
    {"name": "temporal",    "chunk_size": 15000, "agent": "extract_facts_temporal"},
    {"name": "interiority", "chunk_size": 15000, "agent": "extract_facts_interiority"},
]


def _norm_subject(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _fact_key(fact: dict) -> tuple[str, str]:
    return (fact.get("type", ""), _norm_subject(fact.get("subject", "")))


def _facts_similar(a: str, b: str, threshold: float) -> bool:
    if a == b:
        return True
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold


def merge_facts(
    pass_outputs: dict[str, list[dict]], similarity: float
) -> list[dict]:
    """Union facts across passes, group by (type, normalized subject), dedup."""
    groups: dict[tuple[str, str], list[tuple[dict, str]]] = {}
    for pass_name, facts in pass_outputs.items():
        for f in facts:
            groups.setdefault(_fact_key(f), []).append((f, pass_name))

    merged: list[dict] = []
    for items in groups.values():
        kept: list[dict] = []
        for fact, pass_name in items:
            text = fact.get("fact", "")
            quote = fact.get("source_quote", "")
            matched: dict | None = None
            for existing in kept:
                if _facts_similar(existing["fact"], text, similarity):
                    matched = existing
                    break
            if matched is not None:
                if len(text) > len(matched["fact"]):
                    matched["fact"] = text
                if len(quote) > len(matched.get("source_quote", "")):
                    matched["source_quote"] = quote
                if pass_name not in matched["passes"]:
                    matched["passes"].append(pass_name)
            else:
                kept.append(
                    {
                        "type": fact.get("type", ""),
                        "subject": fact.get("subject", ""),
                        "fact": text,
                        "source_quote": quote,
                        "passes": [pass_name],
                    }
                )
        merged.extend(kept)

    # Stable sort for diffability across runs.
    merged.sort(key=lambda f: (f["type"], _norm_subject(f["subject"]), f["fact"]))
    return merged


def run_pass(input_path: Path, pass_spec: dict, workdir: Path) -> list[dict]:
    output_path = workdir / f"{pass_spec['name']}.json"
    extract_dir = workdir / "cache" / pass_spec["name"]
    extract_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(EXTRACT_SCRIPT),
        str(input_path),
        "--output", str(output_path),
        "--extract-dir", str(extract_dir),
        "--chunk-size", str(pass_spec["chunk_size"]),
        "--agent", pass_spec["agent"],
    ]
    print(f"\n[Pass: {pass_spec['name']}] chunk={pass_spec['chunk_size']} "
          f"agent={pass_spec['agent']}")
    print("=" * 70)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(
            f"\nERROR: pass {pass_spec['name']!r} failed with exit code "
            f"{result.returncode}. Fix the failing chunk in "
            f"{extract_dir} and re-run.",
            file=sys.stderr,
        )
        sys.exit(result.returncode)
    return json.loads(output_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the three-pass ensemble extraction plan "
            "(generalist@small + generalist@large + sweep@large), then "
            "deterministically merge with subject clustering and "
            "near-duplicate fact dedup."
        )
    )
    parser.add_argument("input",
                        help="Input text file (session summary, chapter, ...)")
    parser.add_argument("--workdir", "-w", required=True, metavar="DIR",
                        help="Working directory for per-pass outputs and caches.")
    parser.add_argument("--similarity", type=float, default=0.85, metavar="RATIO",
                        help="Fact-text similarity threshold for within-group "
                             "dedup (0..1, default 0.85). Higher = stricter, "
                             "more duplicates retained; lower = looser, more "
                             "collapsed.")
    parser.add_argument("--skip", action="append", default=[], metavar="NAME",
                        choices=[p["name"] for p in PASSES],
                        help="Skip a named pass (can repeat). Useful when "
                             "iterating on prompt fixes for one lens.")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    workdir = Path(args.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    active_passes = [p for p in PASSES if p["name"] not in args.skip]
    if not active_passes:
        print("Error: no passes selected (all skipped).", file=sys.stderr)
        sys.exit(1)

    print(f"Input:    {input_path}")
    print(f"Workdir:  {workdir}")
    print(f"Passes:   {', '.join(p['name'] for p in active_passes)}")
    if args.skip:
        print(f"Skipped:  {', '.join(args.skip)}")

    pass_outputs: dict[str, list[dict]] = {}
    for pass_spec in active_passes:
        pass_outputs[pass_spec["name"]] = run_pass(input_path, pass_spec, workdir)

    print("\n" + "=" * 70)
    print("Merging...")
    merged = merge_facts(pass_outputs, args.similarity)
    merged_path = workdir / "merged.json"
    merged_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

    counts_by_pass = {name: len(facts) for name, facts in pass_outputs.items()}
    counts_by_type: dict[str, int] = {}
    pass_combo_counts: dict[str, int] = {}
    for f in merged:
        counts_by_type[f["type"]] = counts_by_type.get(f["type"], 0) + 1
        combo = "+".join(sorted(f["passes"]))
        pass_combo_counts[combo] = pass_combo_counts.get(combo, 0) + 1

    print(f"\nPer-pass facts (raw):  {counts_by_pass}")
    print(f"Total merged (unique): {len(merged)}")
    print(f"By type:               {dict(sorted(counts_by_type.items()))}")
    print(f"Pass coverage:")
    for combo, n in sorted(pass_combo_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {combo:30s} {n}")
    print(f"\nWritten: {merged_path}")


if __name__ == "__main__":
    main()
