"""Blind identity proposals for unnamed characters via the claude-code adapter.

One call per chapter per arm. Arms: context (full chapter + question + canon
candidates) and question_only (question + canon candidates, no chapter). The
Stage 4 agent's evidence is NOT sent in either arm, so the model reads the
chapter itself rather than inheriting another model's framing.
"""
import argparse, hashlib, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from campaignlib.api import make_client, call_api

SYSTEM = """You are evaluating who unnamed characters are in a D&D campaign chronicle
(Curse of Strahd, run as "Curse of the Hags"). Do not call tools or access files.
Use only the supplied text and the supplied canon entries.

The party: Slerdax, Wukong, Gaxim (the half-orc), and one aasimar with two
personalities, Marron (Paladin) and Merrin (Cleric).

For each question, identify each unnamed person, group, or unattributed line
the question asks about. For each one choose a relation to a candidate:
- same_referent: the text establishes this is the named candidate;
- distinct_referents: the text establishes it is NOT that candidate;
- overlap_or_membership: one of a named group, not the whole group;
- ambiguous: the text does not decide. Being plausible, or matching the
  published module, is not enough. A name appearing only in a later chapter
  or only in a canon note is not proof that this unnamed mention is that person.

Return ONLY JSON: {"results":[{"id":"<question id>","referents":[{
"surface":"exact short text from the chapter that refers to the unnamed one",
"candidate":"a supplied canon name, a name used in this chapter, or null",
"relation":"same_referent|distinct_referents|overlap_or_membership|ambiguous",
"confidence":"high|medium|low",
"evidence":[{"quote":"exact substring of the chapter text"}],
"reason":"one or two sentences, including what remains uncertain"}]}]}.
One result per question id. Quotes must be copied exactly from the chapter.
On inputs without chapter text, answer ambiguous with no evidence unless the
question itself settles it. These are proposals for the GM, not canon rulings."""


def sha(b):
    return hashlib.sha256(b).hexdigest()


def build_prompt(ch, arm):
    qs = [{"id": q["id"], "question": q["question"], "canon_candidates": q["canon_candidates"]} for q in ch["questions"]]
    body = {"chapter": ch["chapter"], "questions": qs}
    if arm == "context":
        body["chapter_text"] = ch["text"]
    return json.dumps(body, ensure_ascii=False)


def run_one(run, key, ch, arm, model, effort, psha):
    out = run/arm/f"{key}.response.json"; rec = run/arm/f"{key}.record.json"
    if out.exists() and rec.exists():
        return key, "retained"
    prompt = build_prompt(ch, arm)
    client = make_client(backend="claude-code", model_override=model,
                         claude_code_effort=effort, claude_code_effort_source="explicit")
    data, last = None, None
    for attempt in range(2):
        resp = call_api(client, SYSTEM, prompt, model, max_tokens=32000)
        (run/arm/f"{key}.response.txt").write_text(resp)
        s = resp.strip()
        try:
            d = json.loads(s[s.find("{"):s.rfind("}")+1])
            ids = [r["id"] for r in d["results"]]
            want = {q["id"] for q in ch["questions"]}
            if len(ids) != len(set(ids)) or set(ids) != want:
                raise ValueError("coverage mismatch")
            data = d; break
        except Exception as e:  # noqa
            last = e
    if data is None:
        (run/arm/f"{key}.failure.txt").write_text(repr(last)); return key, f"FAILED {last}"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")
    rec.write_text(json.dumps({"chapter": key, "arm": arm, "backend": "claude-code", "model": model, "effort": effort,
                               "payload_sha256": psha, "system_sha256": sha(SYSTEM.encode()),
                               "prompt_sha256": sha(prompt.encode()), "response_sha256": sha(out.read_bytes()),
                               "attempts": attempt+1}, indent=2)+"\n")
    return key, f"ok ({len(ids)})"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--model", required=True); ap.add_argument("--effort", required=True)
    ap.add_argument("--arm", choices=("context", "question_only"), action="append")
    ap.add_argument("--workers", type=int, default=6); ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    payload = json.loads((a.run/"payload.json").read_text()); psha = sha((a.run/"payload.json").read_bytes())
    jobs = []
    for arm in a.arm or ("context", "question_only"):
        (a.run/arm).mkdir(exist_ok=True)
        jobs += [(arm, k, ch) for k, ch in payload["chapters"].items() if not a.only or k in a.only]
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run_one, a.run, k, ch, arm, a.model, a.effort, psha) for arm, k, ch in jobs]
        for (arm, k, _), f in zip(jobs, futs):
            try: print(arm, *f.result(), flush=True)
            except Exception as e: print(arm, k, "ERROR", repr(e), flush=True)


if __name__ == "__main__":
    main()
