"""session_doc package — helpers shared across sd_consistency / sd_plan / sd_narrate.

Phase 4 carved these out of the old monolithic session_doc.py into flat
session_doc_*.py modules; Phase 5 deletes session_doc.py and moves the
helpers into this package. The flat __init__ re-export block preserves
every public name the old module exposed so external imports
(polish.py, server/routers/scene_editor.py, the test suite) keep working
without edits.
"""

from campaignlib import load_agent_prompt

# Standalone constants the old session_doc.py exposed directly.
CONSISTENCY_SYSTEM = load_agent_prompt("session_doc/consistency")
PLAN_SYSTEM        = load_agent_prompt("session_doc/plan")

from session_doc.examples import get_char_examples
from session_doc.io import (
    _SCENE_FRONTMATTER_RE,
    _split_scene_body,
    extract_scene_text,
    format_extractions,
    load_extractions,
    load_scene_extractions,
    smoothed_claim_problems,
    warn_if_smoothed_claims_verbatim,
    parse_plan,
    parse_vtt,
)
from session_doc.narrate import (
    DIALOGUE_INSTRUCTION_CONDITIONAL,
    DIALOGUE_INSTRUCTION_FULL,
    EXAMPLES_BLOCK,
    NARRATE_SYSTEM_BASE,
    PER_CHAR_EXAMPLES_BLOCK,
    PREV_VOICE_CONTRAST_BLOCK,
    PROSE_MODE_INSTRUCTION,
    SCENE_ANCHORED_DIRECTIVE,
    VOICE_SPEC_BLOCK,
    build_narrate_prompt,
    build_narrate_system,
    estimate_narration_tokens,
)
from session_doc.roster import extract_character_roster, roster_from_config
from session_doc.voice import (
    extract_contrast_sample,
    get_voice_note,
    load_voice_files,
    unknown_narrators,
    voice_declaration_problems,
    load_declared_voices,
)

__all__ = [
    "CONSISTENCY_SYSTEM",
    "DIALOGUE_INSTRUCTION_CONDITIONAL",
    "DIALOGUE_INSTRUCTION_FULL",
    "EXAMPLES_BLOCK",
    "NARRATE_SYSTEM_BASE",
    "PER_CHAR_EXAMPLES_BLOCK",
    "PLAN_SYSTEM",
    "PREV_VOICE_CONTRAST_BLOCK",
    "PROSE_MODE_INSTRUCTION",
    "SCENE_ANCHORED_DIRECTIVE",
    "VOICE_SPEC_BLOCK",
    "_SCENE_FRONTMATTER_RE",
    "_split_scene_body",
    "build_narrate_prompt",
    "build_narrate_system",
    "estimate_narration_tokens",
    "extract_character_roster",
    "roster_from_config",
    "extract_contrast_sample",
    "extract_scene_text",
    "format_extractions",
    "get_char_examples",
    "get_voice_note",
    "load_extractions",
    "load_scene_extractions",
    "smoothed_claim_problems",
    "warn_if_smoothed_claims_verbatim",
    "load_voice_files",
    "unknown_narrators",
    "voice_declaration_problems",
    "load_declared_voices",
    "parse_plan",
    "parse_vtt",
]
