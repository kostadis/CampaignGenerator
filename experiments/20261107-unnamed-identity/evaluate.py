"""Check unnamed-identity proposals (no gold): evidence validity, candidate validity,
control abstention, and the list of positive identifications for GM review."""
import argparse, json
from collections import Counter
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("--run", type=Path, required=True)
    a = ap.parse_args()
    payload = json.loads((a.run/"payload.json").read_text())
    report = {}
    for arm in ("context", "question_only"):
        rows, missing = [], []
        for key, ch in payload["chapters"].items():
            f = a.run/arm/f"{key}.response.json"
            if not f.exists(): missing.append(key); continue
            qs = {q["id"]: q for q in ch["questions"]}
            for r in json.loads(f.read_text())["results"]:
                q = qs[r["id"]]
                names = {c["name"] for c in q["canon_candidates"]} | {al for c in q["canon_candidates"] for al in c["aliases"]}
                for ref in r.get("referents", []):
                    cand = ref.get("candidate")
                    errs = []
                    if arm == "context":
                        if ref.get("surface") and ref["surface"] not in ch["text"]: errs.append("surface not in chapter")
                        for e in ref.get("evidence", []):
                            if not e.get("quote") or e["quote"] not in ch["text"]: errs.append("quote not in chapter")
                        if ref["relation"] == "same_referent" and not ref.get("evidence"): errs.append("positive id without evidence")
                    if cand and cand not in names and (arm != "context" or cand not in ch["text"]):
                        errs.append("candidate not supplied or in chapter")
                    rows.append({"chapter": ch["chapter"], "id": r["id"], "question": q["question"], **ref, "errors": errs})
        report[arm] = {"missing": missing, "referents": len(rows),
                       "relations": dict(Counter(x["relation"] for x in rows)),
                       "positive_by_confidence": dict(Counter(x["confidence"] for x in rows if x["relation"] == "same_referent")),
                       "rows_with_errors": sum(bool(x["errors"]) for x in rows), "rows": rows}
    (a.run/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in report.items()}, indent=2))


if __name__ == "__main__":
    main()
