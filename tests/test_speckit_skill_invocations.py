"""A speckit skill must not document an invocation its own script rejects.

spec-kit 1.0.4 changed the argument loop in most of its bash helpers. The `*)`
case used to collect stray tokens into `ARGS+=("$arg")`; it now does:

    echo "ERROR: Unknown option '$arg'" >&2
    exit 1

The skills that call those scripts kept a sentence that only makes sense when
arguments are passed — "For single quotes in args like "I'm Groot", use escape
syntax" — so a caller following it runs `setup-plan.sh --json "add a feature"`
and gets exit 1 under `set -e` instead of a plan (#404).

#404 reported this for `speckit-plan` alone. It was in **eight** skills, and in
every one of them the script being invoked rejects positionals. It was absent
from `speckit-specify`, whose `create-new-feature.sh` is the one helper that
still takes a `<feature_description>` positional — that is, present in exactly
the places it was wrong and missing from the one place it would have been right.

These files are vendored `specify` output, not hand-written, so the sentence can
return with the next upgrade. That is what this module is for. It derives the
rule from the scripts rather than from a list of skill names, so it needs no
edit when spec-kit changes which helpers take arguments: make a script tolerant
again and its skill is free to document arguments; add a skill and it is covered
on arrival.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = _REPO_ROOT / ".agents" / "skills"
SCRIPTS_DIR = _REPO_ROOT / ".specify" / "scripts" / "bash"

#: How spec-kit spells "this is not a flag I know" since 1.0.4.
_REJECTION = "ERROR: Unknown option"

#: The vestigial guidance. Matched narrowly and on its distinctive opening
#: rather than on the word "args", which appears in legitimate prose ("CLI args
#: for tools") and would make this test fire on text that is perfectly correct.
_ARG_GUIDANCE = "For single quotes in args"

_SCRIPT_REF = re.compile(r"\.specify/scripts/bash/([A-Za-z0-9_-]+\.sh)")


def _skill_files() -> list[Path]:
    return sorted(SKILLS_DIR.glob("speckit-*/SKILL.md"))


def _rejects_positionals(script: Path) -> bool:
    return script.is_file() and _REJECTION in script.read_text(encoding="utf-8")


pytestmark = pytest.mark.skipif(
    not SKILLS_DIR.is_dir() or not SCRIPTS_DIR.is_dir(),
    reason="spec-kit is not installed in this checkout",
)


def test_the_skills_and_scripts_are_actually_present():
    """Guards the two tests below from passing vacuously."""
    assert _skill_files(), f"no speckit skills under {SKILLS_DIR}"
    assert list(SCRIPTS_DIR.glob("*.sh")), f"no helper scripts under {SCRIPTS_DIR}"


def test_no_skill_documents_arguments_for_a_script_that_rejects_them():
    offenders = []
    for skill in _skill_files():
        text = skill.read_text(encoding="utf-8")
        if _ARG_GUIDANCE not in text:
            continue
        strict = sorted(name for name in set(_SCRIPT_REF.findall(text))
                        if _rejects_positionals(SCRIPTS_DIR / name))
        if strict:
            offenders.append(f"{skill.parent.name} -> {', '.join(strict)}")
    assert not offenders, (
        "these skills tell a caller how to quote arguments for a script that "
        f"exits 1 on any positional: {offenders}"
    )


def test_the_one_helper_that_takes_a_positional_still_does():
    """The other half of the rule, so it cannot pass by everything rejecting.

    If spec-kit ever makes this one strict too, nothing in the repo should be
    documenting arguments for it either — and this failing is how we find out,
    rather than by a `$speckit-specify` run dying on its own description.
    """
    script = SCRIPTS_DIR / "create-new-feature.sh"
    if not script.is_file():
        pytest.skip("create-new-feature.sh is not installed")
    body = script.read_text(encoding="utf-8")
    assert 'ARGS+=("$arg")' in body, "the feature-description positional is gone"
    assert _REJECTION not in body
