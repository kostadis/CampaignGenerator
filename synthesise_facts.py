#!/usr/bin/env python3
"""Deterministic Layer-1 synthesis of merged.json into profile markdown.

Takes the output of ``ensemble_extract.py`` and emits a human-review
document modeled on the shape of distill_extractions: sections per type,
profile per subject, atomic facts as bullets with pass provenance.

This is intentionally **not** an LLM step. No synthesis decisions are made
by code:

- Facts are grouped by exact normalized subject (lowercase alphanumerics).
- An optional ``aliases.json`` lets the human collapse spelling variants
  (Sarith ↔ Sathir ↔ Serith). Without it, variants stay visibly separate.
- A SequenceMatcher-based detector flags **potential** aliases at the end
  of the document. It does not auto-apply them. The human confirms by
  editing aliases.json and re-running.
- Within a subject, facts are kept as separate bullets — no merging of
  phrasings. Multi-pass facts float to the top so the highest-confidence
  observations are scannable first.

aliases.json format::

    {
      "Sarith":         ["Sathir", "Serith"],
      "Zalthir":        ["Zathir"],
      "Buppido":        ["Bupido"],
      "Blingdenstone":  ["Blingdenston"],
      "Tongue of Madness": ["Tongue of Madness mushroom"]
    }

Workflow::

    1. python ensemble_extract.py session.md --workdir runs/session/
    2. python synthesise_facts.py runs/session/merged.json -o runs/session/synthesis.md
    3. Human reviews synthesis.md, copies flagged pairs into aliases.json,
       re-runs step 2 to apply them.
    4. (Optional later) LLM polish on the human-edited synthesis.md.

Usage::

    python synthesise_facts.py runs/session/merged.json -o synth.md
    python synthesise_facts.py merged.json -o synth.md --aliases aliases.json
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

TYPE_ORDER = ["npc", "monster", "faction", "location", "object", "date", "event", "thread"]
TYPE_HEADINGS = {
    "npc": "NPCs",
    "monster": "Monsters",
    "faction": "Factions",
    "location": "Locations",
    "object": "Objects",
    "date": "Dates & Temporal Anchors",
    "event": "Events",
    "thread": "Threads & Mysteries",
}

# SequenceMatcher ratio above which two subject strings are flagged as
# "possibly the same entity." Conservative; the human confirms.
CLUSTER_THRESHOLD = 0.80


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def load_aliases(path: Path | None) -> dict[str, str]:
    """Load aliases.json -> flat {variant: canonical} map.

    Canonical names are also entries that map to themselves, so callers
    can do ``aliases.get(subject, subject)`` uniformly.
    """
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    flat: dict[str, str] = {}
    for canonical, variants in data.items():
        flat[canonical] = canonical
        for v in variants:
            flat[v] = canonical
    return flat


def detect_clusters(
    subjects_by_type: dict[str, list[str]],
    applied_aliases: dict[str, str],
    threshold: float,
) -> dict[str, list[tuple[str, str, float]]]:
    """Find subject pairs above `threshold` not already aliased together."""
    suggestions: dict[str, list[tuple[str, str, float]]] = {}
    for t, subjects in subjects_by_type.items():
        distinct = sorted(set(subjects))
        pairs: list[tuple[str, str, float]] = []
        for i, a in enumerate(distinct):
            for b in distinct[i + 1:]:
                # Already collapsed to the same canonical → skip
                ca, cb = applied_aliases.get(a), applied_aliases.get(b)
                if ca is not None and ca == cb:
                    continue
                if _norm(a) == _norm(b):
                    continue
                ratio = SequenceMatcher(None, _norm(a), _norm(b)).ratio()
                if ratio >= threshold:
                    pairs.append((a, b, ratio))
        if pairs:
            suggestions[t] = sorted(pairs, key=lambda x: -x[2])
    return suggestions


def _fact_sort_key(f: dict) -> tuple:
    """Sort facts within a subject: multi-pass first, then longer fact first."""
    passes = len(f.get("passes", []))
    fact_len = len(f.get("fact", ""))
    return (-passes, -fact_len)


def synthesise(facts: list[dict], aliases: dict[str, str]) -> str:
    """Group facts by (type, canonical_subject) and emit markdown body."""
    by_type_subject: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    variants_by_type: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for f in facts:
        t = f.get("type", "unknown")
        subject = f.get("subject", "")
        canonical = aliases.get(subject, subject)
        by_type_subject[t][canonical].append(f)
        variants_by_type[t][canonical].add(subject)

    lines: list[str] = []
    for t in TYPE_ORDER:
        if t not in by_type_subject:
            continue
        lines.append(f"## {TYPE_HEADINGS.get(t, t.title())}")
        lines.append("")
        for canonical in sorted(by_type_subject[t].keys(), key=lambda s: s.lower()):
            facts_for_subj = sorted(by_type_subject[t][canonical], key=_fact_sort_key)
            variants = variants_by_type[t][canonical] - {canonical}
            header = f"**{canonical}**"
            if variants:
                header += f"  ⚠ also: {', '.join(sorted(variants))}"
            lines.append(header)
            for f in facts_for_subj:
                passes = ", ".join(f.get("passes", []))
                fact_text = f.get("fact", "").rstrip(".")
                provenance = f" *[{passes}]*" if passes else ""
                lines.append(f"- {fact_text}.{provenance}")
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def emit_alias_suggestions(suggestions: dict[str, list[tuple[str, str, float]]]) -> str:
    if not suggestions:
        return ""
    lines = ["## Potential Aliases", ""]
    lines.append(
        "The following subject pairs may refer to the same entity. Confirm by "
        "adding to `aliases.json` (canonical → [variants]) and re-running. "
        "Pairs already covered by aliases.json are suppressed."
    )
    lines.append("")
    for t in TYPE_ORDER:
        if t not in suggestions:
            continue
        lines.append(f"### {TYPE_HEADINGS.get(t, t.title())}")
        lines.append("")
        for a, b, ratio in suggestions[t]:
            lines.append(f"- `{a}` ↔ `{b}`  (similarity {ratio:.2f})")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic Layer-1 synthesis of merged.json into profile "
            "markdown. No LLM. Groups facts by (type, subject), applies any "
            "human-curated aliases, and flags potential aliases for review."
        )
    )
    parser.add_argument("merged", help="Path to merged.json from ensemble_extract.py")
    parser.add_argument("--output", "-o", required=True,
                        help="Where to write the synthesis markdown.")
    parser.add_argument("--aliases", default=None, metavar="FILE",
                        help="Optional aliases.json: {canonical: [variants]}. "
                             "If absent, no spelling-cluster collapsing is applied "
                             "(all variants appear separately).")
    parser.add_argument("--threshold", type=float, default=CLUSTER_THRESHOLD,
                        help=f"Similarity threshold for flagging potential aliases "
                             f"(default: {CLUSTER_THRESHOLD}). Lower = more "
                             f"aggressive flagging.")
    args = parser.parse_args()

    merged_path = Path(args.merged).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    aliases_path = Path(args.aliases).expanduser().resolve() if args.aliases else None

    if not merged_path.exists():
        print(f"Error: merged.json not found: {merged_path}", file=sys.stderr)
        sys.exit(1)

    facts = json.loads(merged_path.read_text(encoding="utf-8"))
    aliases = load_aliases(aliases_path)

    subjects_by_type: dict[str, list[str]] = defaultdict(list)
    for f in facts:
        subjects_by_type[f.get("type", "unknown")].append(f.get("subject", ""))
    suggestions = detect_clusters(subjects_by_type, aliases, args.threshold)

    body = synthesise(facts, aliases)
    tail = emit_alias_suggestions(suggestions)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final = body
    if tail:
        final = final + "\n" + tail + "\n"
    output_path.write_text(final, encoding="utf-8")

    counts = Counter(f.get("type", "?") for f in facts)
    print(f"Wrote synthesis: {output_path}")
    print(f"Source facts: {len(facts)}")
    print(f"By type:      {dict(sorted(counts.items()))}")
    if aliases:
        canonicals = len({v for v in aliases.values()})
        print(f"Aliases:      {canonicals} canonical entities "
              f"({len(aliases)} total mappings)")
    if suggestions:
        total = sum(len(v) for v in suggestions.values())
        print(f"Potential aliases flagged: {total} pair(s) "
              f"— review and add confirmed ones to aliases.json")


if __name__ == "__main__":
    main()
