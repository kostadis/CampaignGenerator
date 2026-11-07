"""Score masked-personality proposals against frozen gold; list disagreements for GM review.

Tier gm: GM's 2026-11-07 line rulings (strict). Tier current: unruled current
text (agreement only; a confident disagreement is a question, not an error).
Evidence check: every quote must be an exact substring of what that arm saw.
"""
import argparse, hashlib, json
from collections import Counter
from pathlib import Path


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True)
    a = ap.parse_args()
    reg = json.loads((a.run/"registration.json").read_text())
    for k in ("payload.json", "gold.json", "input_hashes.json"):
        if sha(a.run/k) != reg[k]:
            raise SystemExit(f"registered input changed: {k}")
    payload = json.loads((a.run/"payload.json").read_text())
    gold = {g["id"]: g for g in json.loads((a.run/"gold.json").read_text())}
    report = {}
    for arm in ("context", "sentence_only"):
        res, missing, bad_ev = {}, [], []
        for key, ch in payload["chapters"].items():
            f = a.run/arm/f"{key}.response.json"
            if not f.exists():
                missing.append(key); continue
            seen = ch["text"] if arm == "context" else "\n".join(t["line_text"] for t in ch["targets"])
            for r in json.loads(f.read_text())["results"]:
                r["evidence_valid"] = all(e.get("quote", "") and e["quote"] in seen for e in r.get("evidence", []))
                if not r["evidence_valid"]:
                    bad_ev.append(r["id"])
                res[r["id"]] = r
        tiers = {}
        for tier in ("gm", "current"):
            ids = [i for i, g in gold.items() if g["tier"] == tier and i in res]
            c = Counter()
            for i in ids:
                p, g = res[i]["personality"], gold[i]["gold"]
                c["ambiguous" if p == "ambiguous" else ("match" if p == g else "disagree")] += 1
            tiers[tier] = {"n": len(ids), **c}
        disagreements = []
        for i, r in res.items():
            g = gold[i]
            if r["personality"] not in ("ambiguous", g["gold"]):
                disagreements.append({"id": i, "chapter": g["chapter"], "line": g["line"], "tier": g["tier"],
                                      "text_has": g["gold"], "model": r["personality"],
                                      "confidence": r.get("confidence"), "reason": r.get("reason"),
                                      "evidence": [e["quote"] for e in r.get("evidence", [])],
                                      "evidence_valid": r["evidence_valid"], "card": g.get("card")})
        disagreements.sort(key=lambda d: (d["chapter"], d["line"], d["id"]))
        report[arm] = {"missing_chapters": missing, "scored": len(res), "tiers": tiers,
                       "confidence": dict(Counter(r.get("confidence") for r in res.values())),
                       "evidence_failures": len(bad_ev),
                       "disagreements_by_confidence": dict(Counter(d["confidence"] for d in disagreements)),
                       "disagreements": disagreements}
    # Where the two arms differ: what the wider context bought.
    report["registration"] = reg
    (a.run/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({arm: {k: v for k, v in r.items() if k != "disagreements"}
                      for arm, r in report.items() if arm != "registration"}, indent=2))


if __name__ == "__main__":
    main()
