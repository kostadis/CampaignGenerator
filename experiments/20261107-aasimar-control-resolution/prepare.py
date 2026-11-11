"""Freeze masked Marron/Merrin mentions and GM-ruled gold, separately from model input.

Curse of the Hags: one aasimar PC with two personalities, Marron (Paladin) and
Merrin (Cleric). Every name token in a chapter is replaced by a numbered marker
[A<n>] so the model must infer who is in control from context, never by reading
the name. Gold is the current bible text, tiered:
  tier "gm"      - lines the GM ruled one by one on the 2026-11-07 revisit page
  tier "current" - every other mention: current text, never individually ruled
Chapters 1-2 and Ch. 3 up to L36 are excluded by GM convention ("keep Marron"
until "Marron returns from demise as Merrin") and are left unmasked as context.
Reads campaign files only; writes only to --out.
"""
import argparse, glob, hashlib, json, re
from pathlib import Path

NAME = re.compile(r"\b(Marron|Merrin)\b")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    root = a.campaign_root
    items = json.loads((root/"summaries/chapter_enhance_review/aasimar/review_items.json").read_text())
    items = items["items"] if isinstance(items, dict) else items
    dec = json.loads((root/"summaries/chapter_enhance_review/aasimar/decisions.json").read_text())["decisions"]
    ruled = {}
    for it in items:
        m = re.match(r"Ch\. (\d+) L(\d+): (Marron|Merrin) → (Marron|Merrin)", it["t"])
        if m:
            ruled[(int(m.group(1)), int(m.group(2)))] = {"card": it["id"], "verdict": dec[it["id"]],
                                                          "proposed": m.group(4)}
    chapters, gold, hashes = {}, [], {}
    for f in sorted(glob.glob(str(root/"docs/chapters/chapter_*.md"))):
        ch = int(re.match(r"chapter_(\d+)", Path(f).name).group(1))
        raw = Path(f).read_bytes(); hashes[Path(f).name] = sha(raw)
        lines = raw.decode().split("\n")
        n = 0; targets = []
        for i, line in enumerate(lines):
            ln = i + 1
            if ch < 3 or (ch == 3 and ln <= 36):
                continue
            def sub(m):
                nonlocal n
                n += 1
                tid = f"c{ch:02d}a{n}"
                rec = {"id": tid, "chapter": ch, "line": ln, "marker": f"[A{n}]",
                       "gold": m.group(1), "tier": "gm" if (ch, ln) in ruled else "current"}
                if (ch, ln) in ruled:
                    rec["card"] = ruled[(ch, ln)]
                gold.append(rec); targets.append(rec)
                return f"[A{n}]"
            lines[i] = NAME.sub(sub, line)
        if not targets:
            continue
        text = "\n".join(lines)
        assert not NAME.search("\n".join(lines[36:] if ch == 3 else lines)), ch
        tlist = []
        for t in targets:
            line = lines[t["line"]-1]
            tlist.append({"id": t["id"], "marker": t["marker"], "line": t["line"], "line_text": line})
        chapters[f"{ch:02d}"] = {"chapter": ch, "file": Path(f).name, "text": text, "targets": tlist}
    payload = {"chapters": chapters}
    for name, v in (("payload.json", payload), ("gold.json", gold), ("input_hashes.json", hashes)):
        (a.out/name).write_text(json.dumps(v, ensure_ascii=False, indent=2)+"\n")
    reg = {k: sha((a.out/k).read_bytes()) for k in ("payload.json", "gold.json", "input_hashes.json")}
    reg["status"] = "gold frozen before model calls; tier gm = GM revisit rulings 2026-11-07, tier current = unruled current text"
    (a.out/"registration.json").write_text(json.dumps(reg, indent=2)+"\n")
    print(json.dumps({"chapters": len(chapters), "targets": len(gold),
                      "gm_tier": sum(g["tier"] == "gm" for g in gold),
                      "gm_lines": len(ruled), "marron": sum(g["gold"] == "Marron" for g in gold),
                      "merrin": sum(g["gold"] == "Merrin" for g in gold)}))


if __name__ == "__main__":
    main()
