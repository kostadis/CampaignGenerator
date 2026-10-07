"""Print every line in each prep that touches a reference fact, for side-by-side judging."""
import re
import sys
from pathlib import Path

CHECKS = {
    "level": r"\blevel(?:\s|-)?(?:9|nine)\b|\b9th[- ]level\b|ninth level",
    "Kalan": r"\bKalan\b",
    "Bookwyrm": r"\bBookwyrm\b|\bSkoda\b",
    "A'lai": r"A'lai|A’lai",
    "Jimjar": r"\bJimjar\b",
    "Edvaldo": r"\bEdvaldo\b",
    "Book hidden as ash": r"\bash(es)?\b.*(illusion|book)|(illusion|book).*\bash(es)?\b",
    "crystals/Echoes": r"crystal|Echo",
    "Robe": r"Robe of the Archmagi|\brobe\b",
    "Manshoon simulacra": r"simulacr",
    "Staff of Power": r"Staff of Power",
    "Sylvira": r"\bSylvira\b",
    "Glabbagool": r"\bGlabbagool\b",
}
for name in sys.argv[1:]:
    text = Path(name).read_text(encoding="utf-8").splitlines()
    print(f"\n######## {name} ({sum(len(t) for t in text)} chars, {len(text)} lines)")
    for label, pat in CHECKS.items():
        hits = [f"L{i + 1}: {t.strip()[:230]}" for i, t in enumerate(text) if re.search(pat, t, re.I)]
        print(f"\n== {label}: {len(hits)} lines")
        for h in hits[:4]:
            print("   ", h)
