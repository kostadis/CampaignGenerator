#!/usr/bin/env python3
"""Two-stage experiment: finders produce spans, one claim pass per prompt cites them.

Stage 1 (already done, deterministic): union every finder's located quote into
maximal intervals. 89 intervals, 96% of chapter_07.

Stage 2 (this script): run each existing agent prompt as a CLAIM pass over that
span set. Two design rules, both load-bearing:

  * The full chapter is in the prompt. Spans are numbered HINTS, not boundaries.
    A claim pass that only saw its span would inherit an unreviewed scope
    decision from stage 1 -- the exact LLM-structures-LLM-output pattern that
    produced the four-date collapse in the current merge.

  * A claim cites `span_id`, not a free-text source_quote. The span is then the
    merge key BY CONSTRUCTION: two claims either sit on the same span or they
    do not, and no prose comparator ever runs. That is what makes the
    9th/10th/1st-of-next-tenday dates un-collapsible rather than
    collapsed-then-repaired.

Throughput, not single-stream: the prompts run concurrently, alternating boxes.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import pathlib
import re
import sys
import time
import urllib.request

sys.path.insert(0, "/home/kostadis/src/CampaignGenerator")
from campaignlib.textproc import locate_quote  # noqa: E402

CG = pathlib.Path("/home/kostadis/src/CampaignGenerator")
AGENTS = {
    "generalist": CG / "config/agents/extract_facts.md",
    "sweep": CG / "config/agents/extract_facts_sweep.md",
    "temporal": CG / "config/agents/extract_facts_temporal.md",
    "interiority": CG / "config/agents/extract_facts_interiority.md",
}
BOXES = ["http://192.168.1.147:8001/v1", "http://192.168.1.121:8001/v1"]
MODEL = "qwen3.8-flash-next"

SPAN_RULES = """
--- OUTPUT FORMAT OVERRIDE (supersedes source_quote instructions above) ---

The chapter is given in full below, followed by a numbered list of SPANS. The
spans mark passages that earlier extraction located; they are hints about where
the material is, NOT limits on what you may read. Read the whole chapter.

Replace the `source_quote` key with a `span` key:

  {"type": ..., "entity": ..., "fact": ..., "span": <integer span id>}

Rules for `span`:
- It MUST be one of the numbered span ids listed below.
- Pick the single span that best supports the fact.
- Each distinct span is a distinct piece of the chapter. If two facts are
  supported by different spans, they are different facts -- never merge them.
- If a fact is supported by the chapter but by no listed span, use -1.

Emit ONLY the JSON array.
"""


def build_spans(chapter: str, ens_dir: pathlib.Path, lx_path: pathlib.Path):
    raw = []
    for name in ("small", "large", "sweep", "temporal", "interiority"):
        f = ens_dir / f"{name}.json"
        if not f.exists():
            continue
        for r in json.loads(f.read_text(encoding="utf-8")):
            q = (r.get("source_quote") or "").strip()
            if not q:
                continue
            p = locate_quote(q, chapter)
            if p is not None:
                raw.append((p, p + len(q)))
    for r in json.loads(lx_path.read_text(encoding="utf-8")):
        o = r.get("quote_offset")
        if o is not None:
            raw.append((o, o + len(r["source_quote"])))
    merged = []
    for a, b in sorted(set(raw)):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(i + 1, a, b) for i, (a, b) in enumerate(merged)]


def call(endpoint: str, system: str, user: str, max_tokens: int = 16000) -> str:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        # Without this the whole budget goes to `reasoning` and content is None.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        f"{endpoint}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=1800) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"] or ""


def parse(raw: str):
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="chapter_07_murder_most_foul")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()

    ch = args.chapter
    chapter = pathlib.Path(f"docs/chapters/{ch}.md").read_text(encoding="utf-8")
    spans = build_spans(
        chapter,
        pathlib.Path(f"docs/ensemble/per_chapter_rerun/{ch}"),
        pathlib.Path(
            "/tmp/claude-1000/-home-kostadis-out-of-the-abyss-out-of-the-abyss/"
            "2306f443-1ebf-4370-ba0e-11dd134e93ea/scratchpad/lx-proto/"
            f"lx_{ch}.json"
        ),
    )
    span_block = "\n".join(
        f"[{i}] {' '.join(chapter[a:b].split())}" for i, a, b in spans
    )
    covered = sum(b - a for _, a, b in spans)
    print(f"stage 1: {len(spans)} spans, {100*covered/len(chapter):.1f}% coverage")

    user = (
        f"=== CHAPTER (full text, read all of it) ===\n{chapter}\n\n"
        f"=== SPANS ({len(spans)}) ===\n{span_block}\n"
    )

    def run(item):
        name, path = item
        system = path.read_text(encoding="utf-8") + SPAN_RULES
        ep = BOXES[list(AGENTS).index(name) % len(BOXES)]
        t0 = time.time()
        raw = call(ep, system, user)
        facts = parse(raw)
        return name, facts, time.time() - t0, ep, raw

    results = {}
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=len(AGENTS)) as ex:
        for name, facts, dt, ep, raw in ex.map(run, AGENTS.items()):
            box = "spark1" if "147" in ep else "spark2"
            if facts is None:
                print(f"  {name:<12} PARSE FAIL on {box} ({dt:.0f}s) raw[:160]={raw[:160]!r}")
                continue
            ok = sum(1 for f in facts if isinstance(f.get("span"), int))
            print(f"  {name:<12} {len(facts):>4} claims  {ok} with span id  "
                  f"{dt:>5.0f}s on {box}")
            results[name] = facts
    print(f"stage 2 wall clock (4 prompts concurrent): {time.time()-t0:.0f}s")

    args.out.write_text(
        json.dumps({"spans": spans, "passes": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
