"""Shared library for CampaignGenerator scripts.

All file I/O, API calls, clipboard, and logging live in this package so
individual scripts only contain their own logic. Historically this was a
single ``campaignlib.py`` module; it is now a package split by concern
(``config``, ``textproc``, ``npc``, ``scenes``, ``pipelines``, ``util``, and
the ``api`` subpackage). This ``__init__`` re-exports the full public surface,
so ``from campaignlib import X`` and ``campaignlib.X`` keep working unchanged.
"""

from .constants import DEFAULT_MODEL
from .wiring import load_wiring, wiring_get, wiring_path
from .textproc import (
    strip_base64_images,
    chunk_text,
    chunk_by_chapters,
    annotate_chunks_with_pov,
    prepare_chunks,
    norm_subject,
)
from .config import (
    find_default_config,
    load_config,
    load_file,
    load_file_optional,
    load_repo_file,
    _clear_prompt_cache,
    load_agent_prompt,
    assemble_docs,
)
from .util import copy_to_clipboard, save_log, atomic_write_text, atomic_write_json
from .api.client import (
    make_client, call_api, call_api_with_tools, stream_api,
    add_backend_args, client_from_args,
)
from .api.batch import (
    build_batch_request,
    submit_batch,
    poll_batch,
    collect_batch,
    write_batch_sidecar,
    read_batch_sidecar,
    utc_now_iso,
    format_batch_progress,
)
from .npc import (
    parse_dossier,
    normalize_npc_key,
    build_alias_normalizer,
    load_alias_map,
    find_alias_registry,
    extract_player_character_map,
    normalize_vtt_speakers,
    format_npc_roster,
)
from .party import (
    load_party_names,
    load_pc_names,
)
from .registry import (
    find_registry,
    load_registry,
    resolve_registry_arg,
)
from .scenes import (
    parse_gmassist_scenes,
    snapshot_scene_for_rerun,
    run_scene_extraction,
    format_scene_output,
    build_scene_extraction_system_prompt,
    plan_scene_extraction,
)
from .pipelines import run_extract_pipeline, run_synthesize_pipeline

__all__ = [
    # constants
    "DEFAULT_MODEL",
    # external wiring (mneme-owned, rendered)
    "load_wiring",
    "wiring_get",
    "wiring_path",
    # textproc
    "strip_base64_images",
    "chunk_text",
    "chunk_by_chapters",
    "annotate_chunks_with_pov",
    "prepare_chunks",
    "norm_subject",
    # config / file I/O / agent prompts
    "find_default_config",
    "load_config",
    "load_file",
    "load_file_optional",
    "load_repo_file",
    "load_agent_prompt",
    "assemble_docs",
    # util
    "copy_to_clipboard",
    "save_log",
    "atomic_write_text",
    "atomic_write_json",
    # api — client
    "make_client",
    "add_backend_args",
    "client_from_args",
    "call_api",
    "call_api_with_tools",
    "stream_api",
    # api — batch
    "build_batch_request",
    "submit_batch",
    "poll_batch",
    "collect_batch",
    "write_batch_sidecar",
    "read_batch_sidecar",
    "utc_now_iso",
    "format_batch_progress",
    # npc / alias machinery
    "parse_dossier",
    "normalize_npc_key",
    "build_alias_normalizer",
    "load_alias_map",
    "find_alias_registry",
    "extract_player_character_map",
    "normalize_vtt_speakers",
    "format_npc_roster",
    # party / PC names
    "load_party_names",
    "load_pc_names",
    # entity registry
    "find_registry",
    "load_registry",
    "resolve_registry_arg",
    # scenes
    "parse_gmassist_scenes",
    "snapshot_scene_for_rerun",
    "run_scene_extraction",
    "format_scene_output",
    "build_scene_extraction_system_prompt",
    "plan_scene_extraction",
    # pipelines
    "run_extract_pipeline",
    "run_synthesize_pipeline",
]
