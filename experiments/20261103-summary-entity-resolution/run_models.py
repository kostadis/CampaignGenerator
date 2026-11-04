"""Blind text-only contextual reference experiment using CampaignGenerator's adapter.

Receives only payload.json, never gold.json. Resumes completed arms without
new calls; records the exact prompts, outputs, model selection, and input hash.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from campaignlib.api import make_client, call_api

SYSTEM = """You are evaluating mention identity in actual campaign summary passages.
Do not call tools or access files. Use only the supplied passages and marked
reference spans. Expected answers are not supplied. References may share a
generic species label without sharing an identity. Names and combat numbers
are not globally unique; respect encounter scope. Location is evidence of
scope, not a permanent entity key. A group is not an individual, a subset is
not its entire group, affiliation is not coidentity, and a corpse can still be
the same individual. Follow corrected source readings rather than ASR tokens.
Use the closest discourse context, not a chapter-wide default location. An
earlier creature mentioned inside a later encounter remains an earlier referent.
When a surface and marked_excerpt are supplied, they identify the exact target;
do not substitute another creature mentioned elsewhere in the same passage.
The [[TARGET]] delimiters are display aids, not source text. Evidence quotations
must come from the unmodified passage text without display delimiters.

For each pair choose exactly one relation:
- same_referent: source supports the same individual or exactly the same group;
- distinct_referents: source establishes different individuals or opposed/disjoint
  groups at the referenced moment, not merely different location mentions;
- separate_scope: different encounter/location reference scopes are available,
  but exact membership continuity or disjointness is not established;
- overlap_or_membership: explicit subset/member relation, not exact identity;
- ambiguous: insufficient evidence to decide; do not make a confident merge;
- corrected_nonreferent: at least one marked species token is explicitly
  corrected as a transcription error and does not denote that creature here.

Return ONLY JSON: {"results":[{"id":"q01","relation":"...",
"left_context":{"granularity":"individual|group|kind|unknown|nonreferent",
"location":"source-supported location or null","encounter":"brief source scope or null"},
"right_context":{"granularity":"...","location":null,"encounter":null},
"evidence":[{"reference":"supplied r-ID","quote":"exact supporting passage substring"}],
"reason":"short explanation and remaining uncertainty"}]}.
For evidence-bearing decisions quote both sides (unless they share a passage).
Every evidence quote must cover the actual marked occurrence of its reference,
not just another sentence about a similar creature in that passage. When two
references share a passage, one quote may cover both marked occurrences.
On context-removed inputs, abstain when bare labels do not establish identity.
These are experimental proposals, not canonical registry writes or GM rulings.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--arm", choices=("context", "surface_only"), action="append")
    args = parser.parse_args()
    payload_path = args.run / "payload.json"
    full = json.loads(payload_path.read_text())
    for arm in args.arm or ("context", "surface_only"):
        output = args.run / f"{arm}.response.json"
        record = args.run / f"{arm}.record.json"
        if output.exists() or record.exists():
            if not (output.exists() and record.exists()):
                raise ValueError("incomplete arm; preserve files and inspect before retry")
            saved = json.loads(record.read_text())
            if saved["model"] != args.model or saved["effort"] != args.effort or saved["payload_sha256"] != hashlib.sha256(payload_path.read_bytes()).hexdigest():
                raise ValueError("existing arm has different inputs/model")
            if saved["response_sha256"] != hashlib.sha256(output.read_bytes()).hexdigest():
                raise ValueError("existing arm response changed")
            print(f"{arm}: retained successful response", flush=True)
            continue
        payload = deepcopy(full)
        if arm == "surface_only":
            refs = {r["id"]: r for r in full["references"]}
            payload["references"] = [{"id": rid, "surface": full["passages"][r["passage"]]["text"][r["start"]:r["end"]]}
                                     for rid, r in refs.items()]
            payload["passages"] = {}
        prompt = json.dumps(payload, ensure_ascii=False)
        (args.run/f"{arm}.prompt.txt").write_text(prompt)
        (args.run/f"{arm}.system.txt").write_text(SYSTEM)
        client = make_client(backend="codex-cli", model_override=args.model,
                             reasoning_effort=args.effort, reasoning_effort_source="explicit")
        response = call_api(client, SYSTEM, prompt, args.model, max_tokens=10000)
        (args.run/f"{arm}.response.txt").write_text(response)
        parsed = response.strip()
        if parsed.startswith("```"):
            parsed = parsed.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(parsed)
        expected = {c["id"] for c in full["cases"]}
        actual = [r["id"] for r in data["results"]]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("missing/duplicate/unrequested case results")
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")
        record.write_text(json.dumps({"arm": arm, "backend": "codex-cli", "model": args.model,
                                     "effort": args.effort,
                                     "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
                                     "system_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
                                     "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                                     "response_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                                     "status": "response_received_not_yet_scored", "gold_sent": False}, indent=2)+"\n")
        print(f"{arm}: {len(actual)} responses received", flush=True)


if __name__ == "__main__":
    main()
