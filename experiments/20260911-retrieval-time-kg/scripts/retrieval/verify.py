#!/usr/bin/env python3
"""Verify a generated document against the corpus using tgrep.

Three checks a trigram index CAN do:
  1. QUOTED STRINGS  -- must appear verbatim somewhere in the corpus
  2. PROPER NOUNS    -- must appear at all
  3. ENTITY PAIRS    -- two proper nouns asserted in one sentence must
                        co-occur in at least one source file

Check 3 is the important one: it catches false RELATIONSHIPS between real
entities, which is most of what an LLM gets wrong.

usage: verify.py <file.md> [corpus_root]
"""
import re, subprocess, sys
from pathlib import Path

DOC = Path(sys.argv[1])
ROOT = sys.argv[2] if len(sys.argv) > 2 else "/home/kostadis/obelisk"
GLOBS = ["-g", "**/session_summary.md", "-g", "**/session-summary.md"]

STOP = {"The","This","That","These","Those","He","She","They","It","Not","Session","Chapter",
        "Party","GM","DM","Record","Status","Location","What","Where","Who","When","Why",
        "Chapters","Chapter 11","Note","Source","Chapter 8","Current","Chapter 7","Position"}

def tg(pattern, fixed=False):
    cmd = ["tgrep", "-i", "-l", *GLOBS] + (["-F"] if fixed else []) + [pattern, ROOT]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return [l for l in r.stdout.splitlines() if l and not l.startswith(("warning","note"))]

text = DOC.read_text(encoding="utf-8")
body = "\n".join(l for l in text.splitlines() if not l.startswith(">"))  # skip our own header

print(f"VERIFYING {DOC.name} against {ROOT}\n")

# 1. quoted strings
quotes = [q for q in re.findall(r'[""«]([^""»\n]{18,120})[""»]', body)]
bad_q = [q for q in dict.fromkeys(quotes) if not tg(q, fixed=True)]
print(f"1. QUOTED STRINGS: {len(set(quotes))} distinct, {len(bad_q)} NOT found verbatim")
for q in bad_q[:6]: print(f"     ✗ \"{q[:90]}\"")

# 2. proper nouns
nouns = {n for n in re.findall(r'\b[A-Z][a-z]{3,}(?:\s+[A-Z][a-z]{2,})?\b', body)} - STOP
missing = [n for n in sorted(nouns) if not tg(re.escape(n))]
print(f"\n2. PROPER NOUNS: {len(nouns)} distinct, {len(missing)} absent from corpus")
for n in missing[:12]: print(f"     ✗ {n}")

# 3. entity pairs asserted in the same sentence
pairs, checked = [], set()
for sent in re.split(r'(?<=[.!?])\s+|\n', body):
    found = [n for n in nouns if n in sent]
    for i in range(len(found)):
        for j in range(i+1, len(found)):
            key = tuple(sorted((found[i], found[j])))
            if key in checked: continue
            checked.add(key)
            pairs.append((key, sent.strip()[:110]))
nocoocc = []
for (a, b), sent in pairs:
    fa, fb = set(tg(re.escape(a))), set(tg(re.escape(b)))
    if fa and fb and not (fa & fb):
        nocoocc.append((a, b, sent))
print(f"\n3. ENTITY PAIRS: {len(pairs)} asserted, {len(nocoocc)} never co-occur in any source file")
for a, b, s in nocoocc[:10]: print(f"     ✗ {a} + {b}\n         \"{s}\"")
