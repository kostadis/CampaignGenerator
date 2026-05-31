#!/usr/bin/env python3
"""Canonicalise proper-noun spellings in a hand-written campaign bible.

A bible written by hand over months drifts: one place ends up spelled six
ways (Whorlstone / Whorlestone / Whirlstone / …), an NPC's name picks up
typos, accents come and go. That drift then propagates into every derived
artifact — `split_chapters.py` → per-chapter files → fact extraction →
synthesis — so the same entity shows up under several spellings downstream.

This tool fixes it at the source, in two steps with a human checkpoint
between them (the LLM-pipeline rule applies to deterministic automation too:
spelling/identity is a precision decision, so a human signs off before the
text is rewritten):

  1. propose — scan the bible, cluster near-duplicate proper nouns, and write
     a reviewable {variant: canonical} map (+ a readable report). Touches
     nothing. Canonical authority: a token close to a name in the module
     inventory canonicalises to the INVENTORY spelling (Phase A); otherwise a
     rare spelling that is clearly a typo of an established, frequent name
     canonicalises to that name (Phase B).

  2. apply — after you edit the map (delete wrong rows, fix canonicals),
     replace each variant deterministically: whole-word, case-preserving,
     possessives kept intact (`Zalthri's` → `Zalthir's`).

Precision is favoured over recall by default: the matcher is tight enough to
exclude near-words (Abyss/Abyssal), plurals (Keeper/Keepers) and common-word
collisions. To sweep the long tail of transpositions (Gyrgum→Grygum), run a
second `propose` pass with a lower `--sim` (e.g. 0.80) and review carefully —
the looser net drags in false positives that only a human can rule on.

Usage:
  python spell_canon.py propose bible.md --inventory inv.md \\
      --out map.json --report report.md
  # ...review/edit map.json...
  python spell_canon.py apply bible.md --map map.json
  python spell_canon.py apply bible.md --map map.json --dry-run

After applying, regenerate derived files (e.g. `split_chapters.py`).
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

DEFAULT_SIM = 0.88        # similarity floor: tight = precision over recall
DEFAULT_MIN_LEN = 5       # shorter names (Nym, Sorn) collide too easily
DEFAULT_MAX_DELTA = 2     # max edit distance / length delta to call it one name
DEFAULT_ANCHOR_MIN = 8    # Phase-B: a name this frequent can anchor typo variants

_INFLECTIONS = ("s", "es", "ing", "ed")

# Capitalised words that are sentence-starts / common English, not proper nouns.
STOP = {
    "The", "This", "That", "These", "Those", "There", "Their", "They", "Then",
    "When", "Where", "While", "With", "Which", "What", "Who", "Whom", "Whose",
    "After", "Before", "Above", "Below", "Because", "Between", "Both", "But",
    "And", "Are", "As", "At", "An", "A", "He", "She", "His", "Her", "Him",
    "It", "Its", "If", "In", "Into", "Is", "Of", "On", "Or", "One", "Once",
    "Only", "Out", "Over", "Some", "Such", "So", "Should", "Still", "Since",
    "Each", "Every", "For", "From", "Finally", "First", "Now", "Not", "No",
    "You", "Your", "We", "Was", "Were", "Will", "Would", "Could", "Can",
    "Do", "Does", "Did", "Done", "Down", "During", "Even", "Here", "How",
    "Inside", "Instead", "Just", "Like", "Maybe", "More", "Most", "Much",
    "Near", "Next", "Other", "Perhaps", "Rather", "Than", "Through", "Too",
    "Under", "Until", "Up", "Upon", "Very", "Within", "Without", "Yet",
}


# ── matching primitives ───────────────────────────────────────────────────

def strip_possessive(tok: str) -> str:
    """Drop a trailing possessive ('s / ’s / ' / ’) to get the base name."""
    return re.sub(r"[’']s$", "", tok).rstrip("’'")


def same_word_family(a_low: str, b_low: str) -> bool:
    """True if the two differ only by an English inflection (plural / verb form
    / re- prefix) — a different grammatical form, NOT a misspelling. Internal
    differences (Bupido↔Buppido, Demogorgon↔Demogorgonn) are NOT a match."""
    s, l = sorted((a_low, b_low), key=len)
    if s == l:
        return False
    if any(l == s + suf for suf in _INFLECTIONS):
        return True
    return l == "re" + s


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def close(a_low: str, b_low: str, sim: float, max_delta: int) -> bool:
    """Same name, different spelling — tight enough to exclude near-words."""
    if abs(len(a_low) - len(b_low)) > max_delta:
        return False
    if edit_distance(a_low, b_low) > max_delta:
        return False
    return SequenceMatcher(None, a_low, b_low).ratio() >= sim


# ── corpus + inventory ────────────────────────────────────────────────────

def inventory_tokens(inventory: Path, min_len: int) -> dict:
    """Lowercased canonical token -> canonical spelling, from **bold** names."""
    canon: dict[str, str] = {}
    for bold in re.findall(r"\*\*(.+?)\*\*", inventory.read_text(encoding="utf-8")):
        for piece in re.split(r"[/,]", bold):       # "Sarith Kzekarit / Sarith"
            for tok in piece.split():
                tok = tok.strip("*_'’.,;:()[]—–-")
                if len(tok) >= min_len and tok[:1].isupper() and tok.isalpha():
                    canon.setdefault(tok.lower(), tok)
    return canon


def proper_nouns(bible: Path, min_len: int) -> tuple[Counter, dict]:
    """Distinct name-like BASE tokens (possessives folded), freq + line samples.
    A token is kept if its capitalised form occurs somewhere; its display case
    is the most common cased form seen."""
    raw: Counter = Counter()
    raw_lines: dict[str, list[int]] = defaultdict(list)
    seen_cap: set[str] = set()
    case_votes: dict[str, Counter] = defaultdict(Counter)
    for i, line in enumerate(bible.read_text(encoding="utf-8").splitlines(), 1):
        for tok in re.findall(r"[A-Za-z][A-Za-z'’]+", line):
            base = strip_possessive(tok)
            core = base.replace("'", "").replace("’", "")
            if len(core) < min_len or not core.isalpha():
                continue
            low = base.lower()
            raw[low] += 1
            case_votes[low][base] += 1
            if len(raw_lines[low]) < 6:
                raw_lines[low].append(i)
            if base[:1].isupper() and base not in STOP:
                seen_cap.add(low)
    freq: Counter = Counter()
    lines_of: dict[str, list[int]] = {}
    for low, n in raw.items():
        if low in seen_cap:
            display = case_votes[low].most_common(1)[0][0]
            freq[display] = n
            lines_of[display] = raw_lines[low]
    return freq, lines_of


def best_canon(tok: str, canon: dict, sim: float, max_delta: int) -> str | None:
    if not tok[:1].isupper():                 # only proper-noun-cased tokens
        return None
    low = tok.lower()
    if low in canon:                          # already a valid name
        return None
    best, best_r = None, 0.0
    for clow, cspell in canon.items():
        if same_word_family(low, clow) or not close(low, clow, sim, max_delta):
            continue
        r = SequenceMatcher(None, low, clow).ratio()
        if r > best_r:
            best, best_r = cspell, r
    return best


# ── propose ───────────────────────────────────────────────────────────────

def build_proposal(bible: Path, inventory: Path, sim: float, min_len: int,
                   max_delta: int, anchor_min: int):
    canon = inventory_tokens(inventory, min_len)
    freq, lines_of = proper_nouns(bible, min_len)

    # Phase A — variants of a canonical inventory name.
    phase_a: dict[str, list[str]] = defaultdict(list)
    matched: set[str] = set()
    for tok in freq:
        c = best_canon(tok, canon, sim, max_delta)
        if c and tok != c:
            phase_a[c].append(tok)
            matched.add(tok)

    # Phase B — rare spellings that are typos of an established (frequent,
    # capitalised) homebrew name with no inventory anchor.
    pool = [t for t in freq if t not in matched and t.lower() not in canon]
    anchors = [t for t in pool if freq[t] >= anchor_min and t[:1].isupper()]
    rare = [t for t in pool if freq[t] < anchor_min and t[:1].isupper()]
    by_anchor: dict[str, list[str]] = defaultdict(list)
    for t in rare:
        near = [a for a in anchors if t.lower() != a.lower()
                and not same_word_family(t.lower(), a.lower())
                and close(t.lower(), a.lower(), sim, max_delta)]
        if len(near) == 1 and freq[t] * 4 <= freq[near[0]]:
            by_anchor[near[0]].append(t)

    mapping: dict[str, str] = {}
    report = [
        "# Proper-noun spelling proposal", "",
        f"Bible: `{bible}`  ({sum(freq.values())} proper-noun tokens, "
        f"{len(freq)} distinct, sim≥{sim})", "",
        "Edit the map (delete wrong rows, fix canonicals), then `apply`.", "",
        "## Phase A — variants of a canonical INVENTORY name (high confidence)", "",
    ]
    for c in sorted(phase_a, key=str.lower):
        report.append(f"### → **{c}**  (inventory)")
        for v in sorted(set(phase_a[c]), key=lambda v: -freq[v]):
            mapping[v] = c
            report.append(f"- `{v}` ×{freq[v]}  (lines {lines_of[v]})")
        report.append("")
    report += ["## Phase B — homebrew typos of an established name (REVIEW)", ""]
    for anchor, vs in sorted(by_anchor.items(), key=lambda kv: -freq[kv[0]]):
        report.append(f"### → **{anchor}** (freq {freq[anchor]})")
        for v in sorted(vs, key=lambda v: -freq[v]):
            mapping[v] = anchor
            report.append(f"- `{v}` ×{freq[v]}  (lines {lines_of[v]})")
        report.append("")
    return mapping, "\n".join(report), len(phase_a), len(by_anchor)


# ── apply ─────────────────────────────────────────────────────────────────

def cased_like(match: str, canon: str) -> str:
    if match.islower():
        return canon.lower()
    if match.isupper():
        return canon.upper()
    return canon                              # Titlecase / mixed → canonical's own


def apply_map(bible: Path, mapping: dict, dry_run: bool) -> dict:
    text = bible.read_text(encoding="utf-8")
    counts: dict[str, int] = {}
    for variant in sorted(mapping, key=len, reverse=True):   # longest first
        canon = mapping[variant]
        n = 0

        def repl(m, _c=canon):
            nonlocal n
            n += 1
            return cased_like(m.group(0), _c)

        text = re.compile(rf"\b{re.escape(variant)}\b", re.IGNORECASE).sub(repl, text)
        counts[variant] = n
    if not dry_run:
        bible.write_text(text, encoding="utf-8")
    return counts


# ── CLI ───────────────────────────────────────────────────────────────────

def cmd_propose(args) -> int:
    bible = Path(args.bible).expanduser().resolve()
    inventory = Path(args.inventory).expanduser().resolve()
    if not bible.exists() or not inventory.exists():
        print("Error: bible or inventory not found", file=sys.stderr)
        return 1
    mapping, report, n_a, n_b = build_proposal(
        bible, inventory, args.sim, args.min_len, args.max_delta, args.anchor_min)
    out = Path(args.out).expanduser().resolve()
    rep = Path(args.report).expanduser().resolve() if args.report else out.with_suffix(".md")
    out.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
    rep.write_text(report, encoding="utf-8")
    print(f"Phase A (inventory): {n_a} canonical names | "
          f"Phase B (homebrew): {n_b} anchors | {len(mapping)} replacements proposed")
    print(f"Map:    {out}\nReport: {rep}")
    print("Review the map, then: spell_canon.py apply "
          f"{args.bible} --map {args.out}")
    return 0


def cmd_apply(args) -> int:
    bible = Path(args.bible).expanduser().resolve()
    mp = Path(args.map).expanduser().resolve()
    if not bible.exists() or not mp.exists():
        print("Error: bible or map not found", file=sys.stderr)
        return 1
    mapping = json.loads(mp.read_text(encoding="utf-8"))
    counts = apply_map(bible, mapping, args.dry_run)
    total = sum(counts.values())
    tag = "[dry-run] would apply" if args.dry_run else "Applied"
    print(f"{tag} {len(mapping)} mappings → {total} replacements in {bible.name}")
    for v in sorted(counts, key=lambda v: -counts[v]):
        print(f"  {counts[v]:>4}  {v} → {mapping[v]}")
    zero = [v for v, n in counts.items() if n == 0]
    if zero:
        print(f"\n⚠ {len(zero)} variant(s) matched nothing (check): {zero}",
              file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("propose", help="scan the bible, write a reviewable map")
    pp.add_argument("bible")
    pp.add_argument("--inventory", required=True, help="module proper-noun inventory (**bold** names)")
    pp.add_argument("--out", default="spell_map.json", help="output map JSON")
    pp.add_argument("--report", default=None, help="output report markdown (default: <out>.md)")
    pp.add_argument("--sim", type=float, default=DEFAULT_SIM,
                    help=f"similarity floor (default {DEFAULT_SIM}; lower e.g. 0.80 "
                         f"sweeps transpositions but needs careful review)")
    pp.add_argument("--min-len", type=int, default=DEFAULT_MIN_LEN)
    pp.add_argument("--max-delta", type=int, default=DEFAULT_MAX_DELTA)
    pp.add_argument("--anchor-min", type=int, default=DEFAULT_ANCHOR_MIN)
    pp.set_defaults(func=cmd_propose)

    pa = sub.add_parser("apply", help="apply a reviewed map to the bible (in place)")
    pa.add_argument("bible")
    pa.add_argument("--map", required=True, help="reviewed {variant: canonical} JSON")
    pa.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    pa.set_defaults(func=cmd_apply)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
