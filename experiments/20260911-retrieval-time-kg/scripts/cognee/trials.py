#!/usr/bin/env python3
"""Repeat trials: strict vs baseline system prompt, on OPEN threads.

Every question below is one the play record leaves unresolved. A correct answer
reports the gap. A wrong answer closes it -- usually with published-module canon.
3 repetitions per arm to measure run-to-run variance.
"""
import asyncio, json, os, re, sys, time
from pathlib import Path
os.chdir("/home/kostadis/cognee-local")
sys.stdout.reconfigure(line_buffering=True)
import cognee  # noqa: E402
from cognee.modules.search.types import SearchType  # noqa: E402

STRICT = """You are answering questions about an in-progress tabletop campaign from its play record.

RULES, in priority order:
1. Use ONLY the provided context. You may have prior knowledge of published
   adventures; that knowledge is NOT evidence about this campaign and must never
   appear in your answer.
2. If the context does not state something, write "Not recorded" for that point.
   Never fill a gap with what is typical, likely, or canonical elsewhere.
3. Do not infer outcomes. If the context shows a goal or a plan but not its
   result, say the result is not recorded.
4. Distinguish what is established from what characters believe or intend. Use
   "the record shows" for events and "X says/believes" for claims.
5. Prefer an incomplete answer over a complete-sounding one. An unresolved thread
   left visibly unresolved is correct; a tidy ending is a failure."""

# (id, question, what the record actually supports)
QUESTIONS = [
    ("voss",     "What happened to Orryn Voss, Veyra's mentor? Where is he now?",
     "Alive per Ssarnak ('not in a place where dead is easy'). Location NOT recorded."),
    ("ruxithid", "Who or what is Ruxithid?",
     "A name spoken once by an elongated-headed goblin at the Ch.1 ambush. NEVER explained."),
    ("shard",    "What happened to the blackstone shard Pip sold? Was it recovered?",
     "Sold to a peddler bound for Phandalin. NOT recovered; peddler never found."),
    ("bugbears", "What happened to the bugbears that survived the fire at Tresendar Manor?",
     "Three survived wounded and loose. Party never returned. Fate NOT recorded."),
    ("castle",   "Where is Cragmaw Castle located?",
     "Location NOT recorded. Hamun Kost knows it and has not yet handed it over."),
    ("droop",    "What happened to Droop the goblin?",
     "Fainted in the barracks; left behind during the fire. Fate NOT recorded."),
]
REPS = 3
HEDGE = re.compile(r"not recorded|no record|unknown|not established|does not (say|state|specify)"
                   r"|unresolved|not confirmed", re.I)

async def one(q, strict):
    kw = {"system_prompt": STRICT} if strict else {}
    res = await cognee.search(query_text=q, query_type=SearchType.HYBRID_COMPLETION,
                              datasets=["obelisk"], node_name=["play_record"], **kw)
    return (getattr(res[0], "text", None) or str(res[0])) if res else "<no results>"

async def main():
    out = []
    t0 = time.time()
    for qid, q, truth in QUESTIONS:
        for strict in (False, True):
            for rep in range(1, REPS + 1):
                try:
                    a = await one(q, strict)
                except Exception as e:
                    a = f"<FAILED {type(e).__name__}: {e}>"
                rec = {"id": qid, "arm": "strict" if strict else "baseline", "rep": rep,
                       "hedged": bool(HEDGE.search(a)), "answer": a.strip()}
                out.append(rec)
                print(f"[{time.time()-t0:6.0f}s] {qid:9} {rec['arm']:8} rep{rep} "
                      f"hedged={'Y' if rec['hedged'] else 'n'}")
    Path("trials.json").write_text(json.dumps(
        {"questions": {q[0]: {"q": q[1], "truth": q[2]} for q in QUESTIONS}, "runs": out},
        indent=2, ensure_ascii=False))
    print(f"\nwrote trials.json  ({len(out)} runs, {time.time()-t0:.0f}s)")

asyncio.run(main())
