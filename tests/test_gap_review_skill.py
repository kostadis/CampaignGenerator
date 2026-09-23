"""The gap-review skill is a face on the CLIs, not a second implementation (#455).

The skill exists so the loop can be driven from a phone over Remote Control,
where typing shell commands is the friction. That makes it the one surface most
likely to drift: prose is easy to write and nothing runs it.

These are cheap structural checks, not a substitute for using it. They catch the
two failures that would matter — the skill going missing from the tracked tree,
and it acquiring the ability to decide something that is the GM's.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TRACKED = ROOT / ".agents/skills/gap-review/SKILL.md"

# `.claude/` is gitignored in this repo, so a skill that lives only there is
# absent from every fresh clone — the defect recorded for spec-kit's own ten.
if not TRACKED.is_file():
    raise AssertionError(
        f"the gap-review skill is missing from the tracked tree: {TRACKED}. "
        "A copy under .claude/skills/ does not survive a clone."
    )

SKILL = TRACKED.read_text(encoding="utf-8")

#: Prose in a skill is hard-wrapped, so a phrase that reads as one line in the
#: file may carry a newline in the middle. Match against this for anything that
#: is a sentence rather than a token, or the test fails on formatting.
FLAT = " ".join(SKILL.split())


def test_it_has_frontmatter_that_says_when_to_use_it():
    assert SKILL.startswith("---")
    assert re.search(r"^name:\s*gap-review\s*$", SKILL, re.M)
    assert re.search(r"^description:\s*\S", SKILL, re.M)


def test_every_command_it_names_is_a_real_console_script():
    """A skill that tells a phone to run a command that does not exist is worse
    than no skill: the failure surfaces as a shell error the GM has to decode."""
    import tomllib

    scripts = set(tomllib.loads((ROOT / "pyproject.toml").read_text())
                  ["project"]["scripts"])
    named = set(re.findall(r"^\s*(sd_\w+|assemble)\b", SKILL, re.M))
    assert named, "the skill names no commands at all"
    assert named <= scripts, f"not installed as console scripts: {sorted(named - scripts)}"


def test_it_refuses_to_decide_a_gap():
    """The whole feature exists to put this decision with the human. A skill
    that quietly wrote a passage into the record would undo it in the one place
    nobody re-reads."""
    assert "refuse" in FLAT.lower()
    assert "gm-gaps-selffill" in SKILL          # the evidence, not just the rule
    assert "never write into" in FLAT or "never write" in FLAT


def test_it_tells_the_reader_not_to_reimplement_the_clis():
    assert "Do not reimplement" in FLAT


def test_it_distinguishes_ruled_from_written():
    """The two completions are the thing most likely to be flattened into one
    'how much is left', which would report a finished triage as unfinished."""
    assert "**ruled**" in SKILL and "**written**" in SKILL
    assert "finished triage" in FLAT


def test_it_surfaces_the_stale_review_case():
    """`sd_compose` refuses a stale record; a GM writing more against that scene
    is wasting an evening, so it is worth saying unprompted."""
    assert "REVIEW STALE" in SKILL


def test_the_invocable_copy_matches_the_tracked_one():
    """`.claude/skills/` is where it is invoked from and is gitignored, so the
    two can silently diverge."""
    live = ROOT / ".claude/skills/gap-review/SKILL.md"
    if not live.is_file():
        return          # not installed in this checkout; the tracked one is canon
    assert live.read_text(encoding="utf-8") == SKILL
