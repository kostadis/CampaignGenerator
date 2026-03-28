"""Config API routes — load/save ui_config, path validation, status."""

from fastapi import APIRouter
from pydantic import BaseModel

from server.config import (
    DEFAULT_MODEL,
    MODELS,
    api_key_present,
    derive_campaign_paths,
    derive_session_paths,
    find_ui_config,
    load_ui_config,
    load_ui_config_raw,
    path_exists,
    save_ui_config,
    save_ui_config_raw,
)

router = APIRouter()


@router.get("/")
def get_config():
    """Return the full ui_config.yaml contents."""
    cfg = load_ui_config()
    return cfg


class ConfigUpdate(BaseModel):
    values: dict


@router.put("/")
def put_config(update: ConfigUpdate):
    """Merge values into ui_config.yaml."""
    save_ui_config(update.values)
    return {"ok": True}


@router.get("/raw")
def get_config_raw():
    """Return the raw YAML text and file path."""
    return {"text": load_ui_config_raw(), "path": str(find_ui_config())}


class ConfigRawUpdate(BaseModel):
    text: str


@router.put("/raw")
def put_config_raw(update: ConfigRawUpdate):
    """Overwrite ui_config.yaml with raw YAML text."""
    try:
        save_ui_config_raw(update.text)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/campaign-paths")
def get_campaign_paths(campaign_dir: str, session_dir: str):
    """Derive all paths from campaign directory + session directory."""
    return derive_campaign_paths(campaign_dir, session_dir)


@router.get("/session-paths")
def get_session_paths(session_dir: str):
    """Derive sub-paths from a session directory (legacy)."""
    return derive_session_paths(session_dir)


@router.get("/path-status")
def get_path_status(path: str):
    """Check if a file or directory exists."""
    return {"exists": path_exists(path)}


@router.get("/models")
def get_models():
    """Return the list of available Claude models."""
    return {"models": MODELS, "default": DEFAULT_MODEL}


@router.get("/status")
def get_status():
    """Return API key status and working directory."""
    import os
    return {
        "api_key_present": api_key_present(),
        "cwd": os.getcwd(),
    }
