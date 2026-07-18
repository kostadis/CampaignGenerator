# Roadmap

## In Progress

- **PR #77** — README rewrite (docs/update-readme-and-about branch)

## Planned

### High priority
- **Refactor `planning.py::main`** — cc=84, highest hotspot in the repo; extract subcommand logic into named functions
- **Refactor `ensemble_extract.py::main`** — cc=100, most complex function in the codebase
- **Fix `api_pipeline_status`** in `scene_editor.py` — cc=44, 23 commits (most churned server-side symbol)
- **Fix 138 broken doc links** — run `jdocmunch get_broken_links` and patch

### Medium priority
- **Audit `arc_triggers.py` and `assemble.py`** — both flag all three dead-code signals; confirm abandoned or register as entry points
- **Enable jdocmunch embeddings** — configure an embedding provider for semantic doc search (currently BM25-only)
- **Kanka CE integration** (`kanka_sync` console script, `pipelines/integrations/kanka/kanka_sync.py`) — pull world_state from Kanka CE, push NPC/location updates post-session (see `/opt/proj/campaign-forge`)
- **Extend `mcp_server.py`** — expose `run_prep`, `run_session_pipeline`, `get_world_state` tools for Claude Desktop orchestration

### Low priority / future
- **`extract_player_character_map` refactor** in `campaignlib.py` (cc=26, 24 commits)
- **`stream_api` refactor** in `campaignlib.py` (cc=22, 24 commits)
- **Self-hosted 5e data layer** — Docker-composable Open5e or 5etools API to replace dnd5eapi.co dependency in dnd-mcp

## Completed (recent)

- 2026-06-04 — README rewritten to reflect current project state (PR #77)
- 2026-06-04 — Repo fully indexed in jcodemunch + jdocmunch
