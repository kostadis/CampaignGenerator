"""Blind masked-personality attribution via CampaignGenerator's claude-code adapter.

Reads payload.json only, never gold.json. One call per chapter per arm.
Arms: context (whole masked chapter) and sentence_only (the target lines alone).
Completed chapter/arm records are retained and never re-called.
"""
import argparse, hashlib, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from campaignlib.api import make_client, call_api

SYSTEM = """You are attributing masked name mentions in a D&D campaign chronicle.
Do not call tools or access files. Use only the supplied text.

One player character is an aasimar with a split personality: two personalities
share one body, which is always "she".
- Marron is the Paladin personality.
- Merrin is the Cleric personality.
Either may take control; switches can follow death, unconsciousness, a relic,
an argument between the personalities, or be stated outright. Paladins and
clerics share some spells (e.g. bless, cure wounds), so a shared spell alone is
weak evidence. Other characters' words about "the cleric" or "the paladin" are
evidence; so are stated switches and the personality's own speech.
Control persists: once a personality is shown in control, it stays in control
until the text shows a switch (a stated change, a death or knockout followed by
the other personality acting, or the other personality's cues). You are not told
who was in control at the end of the previous chapter, so near the start of a
chapter rely on the cues in this text.

Every occurrence of either name has been replaced by a marker such as [A7].
For each requested marker decide which personality it names. Convention: a
narrative mention names the personality in control at that moment; where the
text depicts the two personalities addressing each other, each marker names the
one acting or speaking there. Answer "ambiguous" when the text does not let you
decide; never guess from base rates.

Return ONLY JSON: {"results":[{"id":"<target id>","personality":"Marron|Merrin|ambiguous",
"confidence":"high|medium|low","evidence":[{"quote":"exact substring of the supplied text"}],
"reason":"one or two sentences"}]}.
Give one result per requested target id. Evidence quotes must be copied exactly
from the supplied text, markers included, and must show the cue you relied on.
These are experimental proposals, not canon rulings."""


def sha(b):
    return hashlib.sha256(b).hexdigest()


def build_prompt(ch, arm):
    targets = [{"id": t["id"], "marker": t["marker"], "line": t["line"]} for t in ch["targets"]]
    if arm == "context":
        return json.dumps({"chapter": ch["chapter"], "text": ch["text"], "targets": targets}, ensure_ascii=False)
    return json.dumps({"chapter": ch["chapter"], "note": "Only the target lines are supplied.",
                       "targets": [{"id": t["id"], "marker": t["marker"], "line_text": t["line_text"]}
                                   for t in ch["targets"]]}, ensure_ascii=False)


def run_one(run, key, ch, arm, model, effort, payload_sha):
    out = run/arm/f"{key}.response.json"; rec = run/arm/f"{key}.record.json"
    if out.exists() and rec.exists():
        return key, "retained"
    prompt = build_prompt(ch, arm)
    client = make_client(backend="claude-code", model_override=model,
                         claude_code_effort=effort, claude_code_effort_source="explicit")
    last = None
    for attempt in range(2):
        resp = call_api(client, SYSTEM, prompt, model, max_tokens=32000)
        (run/arm/f"{key}.response.txt").write_text(resp)
        s = resp.strip()
        if s.startswith("```"):
            s = s.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            data = json.loads(s[s.find("{"):s.rfind("}")+1])
            ids = [r["id"] for r in data["results"]]
            want = {t["id"] for t in ch["targets"]}
            if len(ids) != len(set(ids)) or set(ids) != want:
                raise ValueError(f"coverage mismatch: missing {sorted(want-set(ids))[:5]} extra {sorted(set(ids)-want)[:5]}")
            break
        except Exception as e:  # noqa
            last = e; data = None
    if data is None:
        (run/arm/f"{key}.failure.txt").write_text(repr(last))
        return key, f"FAILED {last}"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")
    rec.write_text(json.dumps({"chapter": key, "arm": arm, "backend": "claude-code", "model": model,
                               "effort": effort, "payload_sha256": payload_sha,
                               "system_sha256": sha(SYSTEM.encode()), "prompt_sha256": sha(prompt.encode()),
                               "response_sha256": sha(out.read_bytes()), "attempts": attempt+1,
                               "gold_sent": False}, indent=2)+"\n")
    return key, f"ok ({len(ids)})"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--effort", required=True)
    ap.add_argument("--arm", choices=("context", "sentence_only"), action="append")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    payload = json.loads((a.run/"payload.json").read_text())
    psha = sha((a.run/"payload.json").read_bytes())
    jobs = []
    for arm in a.arm or ("context", "sentence_only"):
        (a.run/arm).mkdir(exist_ok=True)
        for key, ch in payload["chapters"].items():
            if a.only and key not in a.only:
                continue
            jobs.append((arm, key, ch))
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run_one, a.run, k, ch, arm, a.model, a.effort, psha) for arm, k, ch in jobs]
        for (arm, k, _), f in zip(jobs, futs):
            try:
                print(arm, *f.result(), flush=True)
            except Exception as e:
                print(arm, k, "ERROR", repr(e), flush=True)


if __name__ == "__main__":
    main()
