"""UI config management — load/save ui_config.yaml, path derivation."""

import os
from pathlib import Path

import yaml

# ── Config persistence ──────────────────────────────────────────────────────

_SAVE_KEY_PREFIXES = (
    "cs_", "distill_", "party_", "plan_", "query_", "prep_", "npc_",
    "sd_", "sw_", "vtt_", "session_dir", "campaign_dir",
    "narr_", "er_", "cg_",
    "dnd_", "mt_",
    "global_", "summaries",
)

_NEVER_SAVE_KEYS = {
    "sd_server_pid", "_refs_initialized", "__show_guide__",
    "ui_config_loaded", "nav_page", "FormSubmitter",
}

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


def find_ui_config() -> Path:
    """Return the ui_config.yaml path (CWD first, then script dir)."""
    cwd_cfg = Path.cwd() / "ui_config.yaml"
    if cwd_cfg.exists():
        return cwd_cfg
    return cwd_cfg  # default to CWD even if it doesn't exist yet


def load_ui_config(path: Path | None = None) -> dict:
    """Load ui_config.yaml and return its contents."""
    if path is None:
        path = find_ui_config()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_ui_config(values: dict, path: Path | None = None) -> None:
    """Merge values into ui_config.yaml (only saves allowed keys)."""
    if path is None:
        path = find_ui_config()

    existing = load_ui_config(path)

    for k, v in values.items():
        if k in _NEVER_SAVE_KEYS:
            continue
        if not any(k.startswith(p) for p in _SAVE_KEY_PREFIXES):
            continue
        if isinstance(v, (str, int, float, bool, list)):
            existing[k] = v

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(existing, f, default_flow_style=False, allow_unicode=True)


def load_ui_config_raw(path: Path | None = None) -> str:
    """Return the raw YAML text of ui_config.yaml."""
    if path is None:
        path = find_ui_config()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def save_ui_config_raw(text: str, path: Path | None = None) -> None:
    """Overwrite ui_config.yaml with raw YAML text. Validates first."""
    if path is None:
        path = find_ui_config()
    yaml.safe_load(text)  # raises if invalid
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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

    # Context files (campaign_state + world_state + party if they exist)
    ctx = [result[k] for k in ("campaign_state", "world_state", "party") if result.get(k)]
    result["context"] = ctx

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

    # Auto-detect session summary and roleplay summary
    for name in ("session-summary.md", "session-clean.md", "session_summary.md"):
        candidate = sd / name
        if candidate.exists():
            result["session_summary"] = str(candidate)
            break

    rp = sd / "session-roleplay.md"
    if rp.exists():
        result["roleplay_summary"] = str(rp)

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
