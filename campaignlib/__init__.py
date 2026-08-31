"""Shared library for CampaignGenerator scripts.

All file I/O, API calls, clipboard, and logging live in this package so
individual scripts only contain their own logic. Historically this was a
single ``campaignlib.py`` module; it is now a package split by concern
(``config``, ``textproc``, ``npc``, ``scenes``, ``pipelines``, ``util``, and
the ``api`` subpackage). This ``__init__`` re-exports the full public surface,
so ``from campaignlib import X`` and ``campaignlib.X`` keep working unchanged.
"""

from .constants import CONFIG_DIR_NAME, DEFAULT_MODEL, config_path
from .wiring import load_wiring, wiring_get, wiring_path
from .textproc import (
    strip_base64_images,
    locate_quote,
    chunk_text,
    chunk_text_with_offsets,
    chunk_by_chapters,
    chunk_by_scenes,
    annotate_chunks_with_pov,
    prepare_chunks,
    norm_subject,
    split_frontmatter,
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
    add_backend_args, add_codex_reasoning_arg, client_from_args,
    resolve_cli_reasoning,
)
from .api.codex_cli import CodexCliError, _CodexCliClient
from .api.batch import (
    build_batch_request,
    submit_batch,
    poll_batch,
    collect_batch,
    run_batch,
    run_single_batch,
    write_batch_sidecar,
    read_batch_sidecar,
    utc_now_iso,
    format_batch_progress,
)
from .npc import (
    parse_dossier,
    normalize_npc_key,
    build_alias_normalizer,
    strip_protected_spans,
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
from .players_config import (
    GM_LABEL,
    PLAYERS_CONFIG_FILENAME,
    Player,
    PlayersConfig,
    load_players_config,
    load_players_config_arg,
    player_name_for,
    save_players_config,
    speaker_map,
    speaker_map_from_configs,
)
from .registry import (
    canonical_context_section,
    find_registry,
    load_registry,
    resolve_registry_arg,
)
from .lineage import (
    SourceDecision,
    compose_scenes,
    compose_summary_scenes,
    load_approved_rows,
    resolve_source,
    route_plan,
)
from .scenes import (
    find_scenes_section,
    parse_gmassist_scenes,
    snapshot_scene_for_rerun,
    run_scene_extraction,
    format_scene_output,
    build_scene_extraction_system_prompt,
    plan_scene_extraction,
    run_batched_scene_extraction,
    group_scenes,
    split_batched_response,
    project_scene_output,
    render_batched_user_prompt,
)
from .pipelines import (
    run_extract_pipeline,
    run_synthesize_pipeline,
    resolve_extract_output,
    CITED_EXTRACT_MAX_TOKENS,
)
from .citations import (
    Citation,
    CitationIdAssigner,
    IdCitation,
    CITATION_RULES_EXTRACT,
    CITATION_RULES_SYNTHESIZE,
    extract_citations,
    find_citation_refs,
    find_uncited_bullets,
    find_unreferenced_claims,
    render_report,
    render_sources_section,
    render_synthesis_report,
    strip_citation_tags,
    verify_citations,
    verify_id_citations,
)
from .citation_checks import check_citations, check_synthesis_citations

__all__ = [
    # constants
    "DEFAULT_MODEL",
    # external wiring (mneme-owned, rendered)
    "load_wiring",
    "wiring_get",
    "wiring_path",
    # textproc
    "strip_base64_images",
    "locate_quote",
    "chunk_text",
    "chunk_text_with_offsets",
    "chunk_by_chapters",
    "chunk_by_scenes",
    "annotate_chunks_with_pov",
    "prepare_chunks",
    "norm_subject",
    "split_frontmatter",
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
    "add_codex_reasoning_arg",
    "client_from_args",
    "resolve_cli_reasoning",
    "call_api",
    "call_api_with_tools",
    "stream_api",
    "CodexCliError",
    "_CodexCliClient",
    # api — batch
    "build_batch_request",
    "submit_batch",
    "poll_batch",
    "collect_batch",
    "run_batch",
    "run_single_batch",
    "write_batch_sidecar",
    "read_batch_sidecar",
    "utc_now_iso",
    "format_batch_progress",
    # npc / alias machinery
    "parse_dossier",
    "normalize_npc_key",
    "build_alias_normalizer",
    "strip_protected_spans",
    "load_alias_map",
    "find_alias_registry",
    "extract_player_character_map",
    "normalize_vtt_speakers",
    "format_npc_roster",
    # party / PC names
    "load_party_names",
    "load_pc_names",
    # player entity (feature 009) — the one place player identity is authored
    "GM_LABEL",
    "PLAYERS_CONFIG_FILENAME",
    "Player",
    "PlayersConfig",
    "load_players_config",
    "load_players_config_arg",
    "player_name_for",
    "save_players_config",
    "speaker_map",
    "speaker_map_from_configs",
    # entity registry
    "canonical_context_section",
    "find_registry",
    "load_registry",
    "resolve_registry_arg",
    # source lineage (issue #213 Phase 1)
    "SourceDecision",
    "compose_scenes",
    "compose_summary_scenes",
    "load_approved_rows",
    "resolve_source",
    "route_plan",
    # scenes
    "find_scenes_section",
    "parse_gmassist_scenes",
    "snapshot_scene_for_rerun",
    "run_scene_extraction",
    "format_scene_output",
    "build_scene_extraction_system_prompt",
    "plan_scene_extraction",
    # scenes — batched engine (013-batched-scene-extraction)
    "run_batched_scene_extraction",
    "group_scenes",
    "split_batched_response",
    "project_scene_output",
    "render_batched_user_prompt",
    # pipelines
    "run_extract_pipeline",
    "run_synthesize_pipeline",
    "resolve_extract_output",
    "CITED_EXTRACT_MAX_TOKENS",
    # citations (extract/synthesize grounding checks — shared across
    # distill.py/planning.py/party.py)
    "Citation",
    "CitationIdAssigner",
    "IdCitation",
    "CITATION_RULES_EXTRACT",
    "CITATION_RULES_SYNTHESIZE",
    "extract_citations",
    "find_citation_refs",
    "find_uncited_bullets",
    "find_unreferenced_claims",
    "render_report",
    "render_sources_section",
    "render_synthesis_report",
    "strip_citation_tags",
    "verify_citations",
    "verify_id_citations",
    # citation_checks (file I/O + reporting wiring over citations.py)
    "check_citations",
    "check_synthesis_citations",
]
