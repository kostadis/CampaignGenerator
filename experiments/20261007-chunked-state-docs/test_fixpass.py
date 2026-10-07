"""Synthetic checks for fixpass's code gates: DELETE licensing, MOVE placement, per-claim splitting."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixpass as fp  # noqa: E402

E = lambda line, text, sec="## Items and Artifacts", grp="Party-held and significant": fp.Entry(line, sec, grp, text, "X")  # noqa: E731

# DELETE: a bare reviewer suspicion is not enough; an older citation is not enough; a later one is.
e = E(5, "- **Staff** — Manshoon's staff [ch 070 / 070.01]")
assert fp.delete_allowed(e, [fp.Flag(e, "reviewer", "wrong heading [ch 070 / 070.01]")]) is None
assert fp.delete_allowed(e, [fp.Flag(e, "stale", "later notes")]) is None
assert fp.delete_allowed(e, [fp.Flag(e, "pc-in-npc-section", "pc")]) == "player character in an NPC section"
e2 = E(5, "- **Book** — evidence [ch 059 / items]")
assert fp.delete_allowed(e2, [fp.Flag(e2, "reviewer", "returned later [ch 061 / 061.02]")]) is None  # reviewer never deletes
assert fp.delete_allowed(e2, [fp.Flag(e2, "cross-section", "newer elsewhere")]) is not None

# MOVE: to a new label, created before the section's _Full notes footer, in the same section.
lines = ["## Items and Artifacts", "**Party-held and significant**", "", "- **Robe** — worn [ch 070 / 070.01]",
         "- **Staff** — Manshoon's staff [ch 070 / 070.01]", "", "_Full notes: x_", "", "## Active Threats", "- t [ch 070 / 070.04]"]
e = E(4, lines[4])
assert fp.apply_move(lines, e, "Held by enemies") is None
out = [ln for ln in lines if ln is not None]
i_label, i_staff, i_foot = out.index("**Held by enemies**"), out.index(e.text), out.index("_Full notes: x_")
assert i_label < i_staff < i_foot < out.index("## Active Threats"), out
assert out.count(e.text) == 1 and "- **Robe** — worn [ch 070 / 070.01]" in out

# MOVE to a section name or the entry's own group is refused, and the line stays put.
lines2 = ["## Items and Artifacts", "**Party-held and significant**", "- **Robe** — worn [ch 070 / 070.01]"]
e3 = E(2, lines2[2])
assert fp.apply_move(lines2, e3, "## Items and Artifacts") is not None and lines2[2] == e3.text
assert fp.apply_move(lines2, e3, "Party-held and significant") is not None and lines2[2] == e3.text

# Per-claim split: each piece ends with its own citation.
parts = fp.claims_of("A fled [ch 065 / 065.03]. B came [ch 067 / 067.01].")
assert parts == ["A fled [ch 065 / 065.03]", ". B came [ch 067 / 067.01]"], parts
print("ok")
