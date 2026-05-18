# CampaignGenerator Documentation

Welcome to the CampaignGenerator documentation. Use the guides below to find the information you need based on your role or task.

## 🗺️ Overview & Architecture
Everything starts here. Understand how the system components interact.
- [System Architecture](core/architecture.md): High-level system map and hard rules.
- [Configuration](core/configuration.md): How to manage tool and campaign settings.

## 🛠️ CLI Tools & Workflows
For running scripts and managing campaign data via the terminal.
- [CLI Tool Guide](cli/cli_tools.md): Command-line flags and general usage.
- [Session Prep Workflow](cli/session_prep_workflow.md): End-to-end guide for session preparation.
- [Session Doc Pipeline](cli/session_doc_pipeline.md): Deep dive into the 5-pass narrative generation.

## 🌐 Web UI & Server
For developers working on the FastAPI backend or Vue 3 frontend.
- [Web UI Overview](web/web_ui.md): Screens, stores, and user flows.
- [UI Configuration & Persistence](web/web_ui_config_persistence.md): How state is saved and managed.

## 🔍 Retrieval-Augmented Language Model (RLM)
Deep dives into the retrieval engine and MCP integration.
- [RLM Architecture](rlm/rlm_architecture.md): The three-pile model and retrieval contract.
- [Retrieval Architecture](rlm/retrieval_architecture.md): Internal mechanics of the search engine.
- [RLM Pipeline](rlm/rlm_pipeline.md): How retrieval feeds into rendering.
- [Dossier Management](rlm/dossier_aliases.md): Aliases and merging rules.
- [Audit Logs](rlm/fivetools_ingest_audit.md): 5etools ingestion status.

## 📋 Specifications
Technical definitions for data formats.
- [Data Formats](specs/formats.md): Input/output structures for tools.

---

## 📂 Other Directories
- `docs/core/`: Core logic and long-lived state docs (mechanics, planning, world_state).
- `docs/design/`: Design docs and RFCs (not yet finalized).
- `docs/archive/`: Deprecated or historical documentation.
