"""Phase 4 smoke tests for the session_doc carve-up.

Verifies:
  - Each new helper module (session_doc_*.py) imports cleanly
  - session_doc.py still exposes every previously-public name via re-export
  - Each new CLI shim (sd_*.py) exits 0 on --help (argparse setup is sane)
"""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HELPERS = [
    "session_doc.io",
    "session_doc.voice",
    "session_doc.roster",
    "session_doc.examples",
    "session_doc.narrate",
]

# (Public name still importable from session_doc, source helper module)
REEXPORTS = [
    ("extract_character_roster",        "session_doc.roster"),
    ("load_voice_files",                "session_doc.voice"),
    ("get_voice_note",                  "session_doc.voice"),
    ("extract_contrast_sample",         "session_doc.voice"),
    ("get_char_examples",               "session_doc.examples"),
    ("load_extractions",                "session_doc.io"),
    ("load_scene_extractions",          "session_doc.io"),
    ("_split_scene_body",               "session_doc.io"),
    ("_SCENE_FRONTMATTER_RE",           "session_doc.io"),
    ("extract_scene_text",              "session_doc.io"),
    ("parse_plan",                      "session_doc.io"),
    ("format_extractions",              "session_doc.io"),
    ("build_narrate_system",            "session_doc.narrate"),
    ("build_narrate_prompt",            "session_doc.narrate"),
    ("estimate_narration_tokens",       "session_doc.narrate"),
    ("NARRATE_SYSTEM_BASE",             "session_doc.narrate"),
    ("EXAMPLES_BLOCK",                  "session_doc.narrate"),
    ("PER_CHAR_EXAMPLES_BLOCK",         "session_doc.narrate"),
    ("VOICE_SPEC_BLOCK",                "session_doc.narrate"),
    ("PREV_VOICE_CONTRAST_BLOCK",       "session_doc.narrate"),
    ("DIALOGUE_INSTRUCTION_FULL",       "session_doc.narrate"),
    ("DIALOGUE_INSTRUCTION_CONDITIONAL","session_doc.narrate"),
    ("PROSE_MODE_INSTRUCTION",          "session_doc.narrate"),
    ("SCENE_ANCHORED_DIRECTIVE",        "session_doc.narrate"),
]

# sd_consistency.py / sd_plan.py / sd_narrate.py moved into session_doc/ and
# now run as console-script entry points (pyproject.toml's [project.scripts])
# rather than at a fixed repo-root path — resolve next to the current
# interpreter, same rationale as tests/test_require_proposal_cli.py's
# PREP_BIN / PLANNING_BIN / SD_PLAN_BIN.
CLI_SHIMS = ["sd_consistency", "sd_plan", "sd_narrate"]


@pytest.mark.parametrize("module_name", HELPERS)
def test_helper_module_imports(module_name):
    mod = importlib.import_module(module_name)
    assert mod is not None


@pytest.mark.parametrize("name,source_module", REEXPORTS)
def test_session_doc_reexport_matches_source(name, source_module):
    """session_doc.X must be the same object as the helper module's X
    (re-exports are pure aliases, not local copies)."""
    sd = importlib.import_module("session_doc")
    src = importlib.import_module(source_module)
    assert getattr(sd, name) is getattr(src, name), (
        f"session_doc.{name} is not the same object as {source_module}.{name}"
    )


@pytest.mark.parametrize("shim", CLI_SHIMS)
def test_cli_shim_help_exits_zero(shim):
    """argparse --help should exit 0 — verifies the CLI is importable and
    the argument set is internally consistent."""
    shim_bin = str(Path(sys.executable).parent / shim)
    result = subprocess.run(
        [shim_bin, "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, (
        f"{shim} --help exited {result.returncode}\n"
        f"stdout:\n{result.stdout[:400]}\n"
        f"stderr:\n{result.stderr[:400]}"
    )
    # Sanity: the help output mentions the shim's name (vs. random failure mode).
    assert shim in result.stdout.lower(), (
        f"{shim} --help output didn't mention the shim name"
    )
