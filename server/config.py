"""Model registry, default model, and campaign-path derivation helpers."""

import os
from pathlib import Path

MODELS = [
    "claude-sonnet-4-6",
    "claude-sonnet-4-20250514",
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
]

DEFAULT_MODEL = "claude-sonnet-4-6"

# Session directory derived sub-paths
DERIVED_SUBDIRS = {
    "extract_dir":          "scene_extractions",
    "roleplay_extract_dir": "vtt_roleplay_extractions",
    "summary_extract_dir":  "vtt_extractions",
}


def derive_campaign_paths(campaign_dir: str, session_dir: str) -> dict:
    """Derive all paths from campaign_dir + session_dir.

    Campaign layout:
        <campaign>/
            docs/               → campaign_state.md, world_state.md, party.md
            voice/              → per-character voice files
            examples/           → handcrafted style references
            summaries/
                <session>/      → VTT, GM recap, extractions, outputs
    """
    cd = Path(campaign_dir).expanduser().resolve()
    sd = Path(session_dir).expanduser().resolve()
    result: dict = {}

    # ── Campaign-level paths ──
    docs = cd / "docs"
    result["campaign_dir"] = str(cd)

    # docs/ files (exist-check each)
    for name, key in [
        ("campaign_state.md", "campaign_state"),
        ("world_state.md", "world_state"),
        ("party.md", "party"),
        ("planning.md", "planning"),
    ]:
        p = docs / name
        result[key] = str(p) if p.exists() else ""

    # summaries file (the big concatenated file)
    for name in ("summaries.md", "all_summaries.md"):
        p = cd / name
        if p.exists():
            result["summaries"] = str(p)
            break
    if "summaries" not in result:
        # Check docs/
        for name in ("summaries.md",):
            p = docs / name
            if p.exists():
                result["summaries"] = str(p)
                break

    # voice/ and examples/ directories
    voice = cd / "voice"
    result["voice_dir"] = str(voice) if voice.is_dir() else ""
    examples = cd / "examples"
    result["examples_dir"] = str(examples) if examples.is_dir() else ""

    # Party config YAML — preferred over flat character/backstory/arc-score flags
    for rel in ("config/party.yaml", "party.yaml"):
        p = cd / rel
        if p.exists():
            result["party_config"] = str(p)
            break
    else:
        result["party_config"] = ""

    # NPC dossier files (individual files, not directory)
    npcs_dir = docs / "npcs"
    if npcs_dir.is_dir():
        npc_files = sorted(npcs_dir.glob("*.md"))
        if npc_files:
            result["plan_npc"] = "\n".join(str(f) for f in npc_files)

    # Context files (campaign_state + world_state + party if they exist)
    ctx = [result[k] for k in ("campaign_state", "world_state", "party") if result.get(k)]
    result["context"] = ctx

    # Planning context: grounding docs for synthesis
    if ctx:
        result["plan_context"] = "\n".join(ctx)

    # ── Session-level paths ──
    result["session_dir"] = str(sd)
    result["output_dir"] = str(sd)

    # Sub-directories
    for key, subdir in DERIVED_SUBDIRS.items():
        result[key] = str(sd / subdir)

    # Auto-detect VTT file
    vtt_files = list(sd.glob("*.vtt"))
    if vtt_files:
        result["vtt_input"] = str(vtt_files[0])

    # Auto-detect GM recap
    for name in ("gm-assist.md", "gm_assist.md", "gmassistant.md", "recap.md"):
        candidate = sd / name
        if candidate.exists():
            result["gm_recap"] = str(candidate)
            break

    # Auto-detect session summary
    for name in ("session-summary.md", "session-clean.md", "session_summary.md"):
        candidate = sd / name
        if candidate.exists():
            result["session_summary"] = str(candidate)
            break

    return result


def derive_session_paths(session_dir: str) -> dict:
    """Legacy: derive sub-paths from a session directory only."""
    return derive_campaign_paths("", session_dir)


def api_key_present() -> bool:
    """Check if ANTHROPIC_API_KEY is set."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def path_exists(path_str: str) -> bool:
    """Check if a file or directory exists."""
    if not path_str or not path_str.strip():
        return False
    return Path(path_str).expanduser().exists()
