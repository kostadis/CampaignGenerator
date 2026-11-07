"""Freeze the 65 Curse of the Hags unnamed-character questions with their chapter text.

Input per question: the GM-facing question, the agent's quoted evidence, the full
chapter text, and the canon entries (entity registry + party.yaml) for every name
the question mentions. There is no gold: the GM ruled "leave unnamed", which
settles the text, not identity. Outputs are proposals for GM review.
Reads campaign files only; writes only to --out.
"""
import argparse, glob, hashlib, html, json, re
from pathlib import Path
import yaml


def sha(b):
    return hashlib.sha256(b).hexdigest()


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("  ", " ").strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(); a.out.mkdir(parents=True, exist_ok=False); root = a.campaign_root
    items = json.loads((root/"summaries/chapter_enhance_review/unnamed_review_items.json").read_text())
    items = items["items"] if isinstance(items, dict) else items
    reg = yaml.safe_load((root/"docs/entity_registry.yaml").read_text())["entities"]
    party = yaml.safe_load((root/"config/party.yaml").read_text())["characters"]
    canon = [{"name": e["name"], "aliases": e.get("aliases", []), "type": e.get("type"), "note": e.get("note")} for e in reg]
    canon += [{"name": p["name"], "aliases": [], "type": "pc", "note": p.get("note")} for p in party]
    for line in (root/"notes/vtt_known_additions.md").read_text().splitlines():
        m = re.match(r"- \*\*(.+?)\*\* \u2014 (.*)", line)
        if m:
            nm = m.group(1); first = nm.split()[0]
            canon.append({"name": nm, "aliases": [first] if first != nm and first.lower() not in ("the", "ms.", "mme.", "mr.") else [], "type": "known_addition", "note": m.group(2)})
    files = {int(re.match(r"chapter_(\d+)", Path(f).name).group(1)): f for f in glob.glob(str(root/"docs/chapters/chapter_*.md"))}
    hashes = {}
    chapters = {}
    for it in items:
        m = re.match(r"Ch\. (\d+): (.*)", it["t"]); ch = int(m.group(1))
        key = f"{ch:02d}"
        if key not in chapters:
            raw = Path(files[ch]).read_bytes(); hashes[Path(files[ch]).name] = sha(raw)
            chapters[key] = {"chapter": ch, "file": Path(files[ch]).name, "text": raw.decode(), "questions": []}
        ev = clean(it["ev"])
        ev = ev.split("Agent:")[0].strip()
        blob = m.group(2) + " " + ev
        cands = [c for c in canon if any(re.search(r"\b"+re.escape(n)+r"\b", blob) for n in [c["name"], *c["aliases"]] if len(n) > 2)]
        chapters[key]["questions"].append({"id": it["id"], "question": m.group(2), "reviewer_evidence": ev,
                                           "canon_candidates": cands})
    payload = {"chapters": chapters}
    (a.out/"payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n")
    (a.out/"input_hashes.json").write_text(json.dumps(hashes, indent=2)+"\n")
    (a.out/"registration.json").write_text(json.dumps({"payload.json": sha((a.out/"payload.json").read_bytes()),
        "input_hashes.json": sha((a.out/"input_hashes.json").read_bytes()),
        "status": "no gold: GM ruled the text stays unnamed; identities are open questions"}, indent=2)+"\n")
    print(json.dumps({"chapters": len(chapters), "questions": sum(len(c["questions"]) for c in chapters.values()),
                      "with_canon_candidates": sum(bool(q["canon_candidates"]) for c in chapters.values() for q in c["questions"])}))


if __name__ == "__main__":
    main()
