#!/usr/bin/env python3
"""cognee summarises -> tgrep validates -> report.

cognee: play_record tier + strict prompt (best config found today).
tgrep : two high-precision checks against the same corpus --
        (1) quoted strings must appear verbatim
        (2) proper nouns must appear at all
Checks run against session summaries only: the source of truth.
"""
import asyncio, json, os, re, subprocess, sys
from pathlib import Path
os.chdir("/home/kostadis/cognee-local")
sys.stdout.reconfigure(line_buffering=True)
import cognee  # noqa: E402
from cognee.modules.search.types import SearchType  # noqa: E402

STRICT = Path("strict_prompt.txt").read_text()
ROOT = "/home/kostadis/obelisk"
GLOBS = ["-g", "**/session_summary.md", "-g", "**/session-summary.md"]

QUESTIONS = [
    ("obelisk",  "What is the Obelisk and why does it matter?"),
    ("flayers",  "What is the goal of the mind flayers?"),
    ("gundren",  "What has happened to Gundren Rockseeker and where does his thread stand?"),
    ("glasstaff","Where is Glasstaff now?"),
    ("droop",    "What happened to Droop the goblin?"),
    ("ruxithid", "Who or what is Ruxithid?"),
    ("party",    "What is the party's current situation at the end of the most recent session?"),
]

# words that look like proper nouns but aren't entities
STOP = set("""The This That These Those He She They It Not Session Chapter Party GM DM Record
Status Location What Where Who When Why Note Source Current Based However While During After
Before Both Each Both Their There Here Yes Both Rules Context Question Answer Final Summary
Known Unknown Established Recorded Clean Verified""".split())

def tg(pat, fixed=False):
    cmd = ["tgrep", "-i", "-l", *GLOBS] + (["-F"] if fixed else []) + [pat, ROOT]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return [l for l in r.stdout.splitlines() if l and not l.startswith(("warning", "note"))]
    except Exception:
        return []

def clean(md):
    t = re.sub(r"[*_`#>|]", " ", md)          # strip markdown
    t = re.sub(r"\s*\n\s*", " ", t)           # join wrapped lines
    return re.sub(r"\s{2,}", " ", t)

def verify(md):
    flat = clean(md)
    quotes = [q for q in dict.fromkeys(re.findall(r'[""]([^""\n]{15,140})[""]', md))]
    bad_q = [q for q in quotes if not tg(q, fixed=True)]
    nouns = set()
    for m in re.finditer(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b', flat):
        n = m.group(0)
        if n in STOP or n.split()[0] in STOP: continue
        if flat[:m.start()].rstrip().endswith((".", "!", "?", ":")) and " " not in n: continue
        nouns.add(n)
    bad_n = sorted(n for n in nouns if not tg(re.escape(n)))
    return quotes, bad_q, sorted(nouns), bad_n

async def main():
    out = []
    for qid, q in QUESTIONS:
        r = await cognee.search(query_text=q, query_type=SearchType.HYBRID_COMPLETION,
                                datasets=["obelisk"], node_name=["play_record"],
                                system_prompt=STRICT)
        ans = (getattr(r[0], "text", None) or str(r[0])).strip() if r else "<no results>"
        quotes, bad_q, nouns, bad_n = verify(ans)
        out.append({"id": qid, "q": q, "answer": ans,
                    "quotes": len(quotes), "bad_quotes": bad_q,
                    "nouns": len(nouns), "bad_nouns": bad_n})
        flag = "FLAGS" if (bad_q or bad_n) else "clean"
        print(f"[{flag:5}] {qid:10} quotes {len(quotes)-len(bad_q)}/{len(quotes)} ok, "
              f"nouns {len(nouns)-len(bad_n)}/{len(nouns)} ok")
    Path("pipeline_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print("\nwrote pipeline_results.json")

asyncio.run(main())
