"""Score each draft on facts verified by hand against the OOTA summaries during this experiment."""
import re
import sys
from pathlib import Path

B = Path("/home/kostadis/out-of-the-abyss/out-of-the-abyss/docs/summary_native/ch002-070/drafts")
docs = {
    "opus": (B / "world_state.draft.md", B / "campaign_state.draft.md"),
    "qwen": (Path("run1/world_state.chunked.md"), Path("run1/campaign_state.chunked.md")),
    "dsk": (Path("run2/world_state.chunked.md"), Path("run2/campaign_state.chunked.md")),
}

# Audit items, with the truth established by reading the summaries (chapter / scene in the note).
AUDIT = [
    ("Bloppblippodd — kuo-toa archpriest of Deep Father, confrontation", "SUPPORTED", "008.01"),
    ("Alkrist as killer — party identifies the poisoner", "SUPPORTED", "061 confession"),
    ("Drow prisoners escape Velkynvelve — chapter 1", "SUPPORTED", "004.03"),
    ("Jorlan's Gambit — gate left unlocked", "SUPPORTED", "003.01"),
    ("Defaced Tempus shrine — Silver Marches crossroads", "SUPPORTED", "055 'defiled Tempus shrine'"),
    ("Kestler the half-orc lay brother — first contact (Triboar)", "SUPPORTED", "055 Mountain's Mouth"),
    ("Disguise rosetta cracked — milestone event, level-up to 9", "SUPPORTED", "063 level nine"),
    ("Droki — derro courier, capture objective", "NOT FOUND", "tracked, never captured"),
    ("Kalan — disappearance and presumed death (Pont de Paramours)", "NOT FOUND", "fled ch65, back ch67"),
]


def verdict(camp: str, item: str) -> str:
    m = re.search(rf'^- "{re.escape(item)}" — `(SUPPORTED|NOT FOUND)', camp, re.M)
    return m.group(1) if m else "missing"


def npc(camp: str, name: str) -> str:
    m = re.search(rf"^\| ?{re.escape(name)}(?: ⚠)? \| ([^|]+)\|", camp, re.M)
    return m.group(1).strip() if m else "-"


print(f"{'check':<58}{'truth':>12}" + "".join(f"{k:>12}" for k in docs))
texts = {k: (w.read_text(encoding="utf-8"), c.read_text(encoding="utf-8")) for k, (w, c) in docs.items()}
score = {k: 0 for k in docs}
for item, truth, note in AUDIT:
    row = f"{('audit: ' + item)[:57]:<58}{truth:>12}"
    for k, (_, camp) in texts.items():
        v = verdict(camp, item)
        score[k] += v == truth
        row += f"{v + (' ✓' if v == truth else ' ✗'):>12}"
    print(row)
for name, truth in (("Ilvara Mizzrym", "Dead"), ("Sarith Kzekarit", "Dead"), ("Buppido", "Dead"),
                    ("Eldeth Feldrun", "Alive/Departed"), ("Glabbagool", "Alive")):
    row = f"{('npc: ' + name):<58}{truth:>12}"
    for k, (_, camp) in texts.items():
        v = npc(camp, name)
        if v == "-":
            v = npc(camp, name.split()[0])
        ok = v != "-" and v.split()[0] in truth.split("/")
        score[k] += ok
        row += f"{v[:9] + (' ✓' if ok else ' ✗'):>12}"
    print(row)
for label, pat_ok, pat_bad in (("party level is 9 (ch 63)", r"[Ll]evel:?\**:? *(9|nine)|[Ll]evel 9|level nine|ninth level|9th level", r"Level:?\**:? *8\b"),
                               ("party name = Ember Vanguard", r"Ember Vanguard", r"known as the \"?Ember Grapple")):
    row = f"{label:<58}{'yes':>12}"
    for k, (world, _) in texts.items():
        head = world.split("## Factions")[0]
        ok = bool(re.search(pat_ok, head)) and not re.search(pat_bad, head)
        score[k] += ok
        row += f"{('yes ✓' if ok else 'no ✗'):>12}"
    print(row)
n = len(AUDIT) + 5 + 2
print(f"{'SCORE':<58}{n:>12}" + "".join(f"{score[k]:>12}" for k in docs))
