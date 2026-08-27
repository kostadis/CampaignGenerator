# Implementation Plan: Codex CLI Subscription Backend

**Branch**: `015-codex-cli-backend` (feature metadata; worktree branch `fix/348`) | **Date**: 2026-08-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/015-codex-cli-backend/spec.md`

## Summary

Add `codex-cli` as a shared, keyless model backend for consistency audits. A new
`campaignlib/api/codex_cli.py` adapter will invoke `codex exec` once per request
using the operator's ChatGPT subscription login, pass developer and user content
through separate Codex channels, remove API-key variables, execute from an
isolated temporary directory with read-only/no-tool policy, and return the final
Markdown response through the existing `call_api`/`stream_api` facade. The
consistency CLI will expose this backend without inheriting a Claude model name,
will retain its single-document and human-review workflow, and will continue to
reject Batch API use. The installed consistency skills will be updated at their
canonical source in the separate dotfiles repository.

## Technical Context

**Language/Version**: Python >=3.9  
**Primary Dependencies**: Python standard library (`subprocess`, `tempfile`,
`json`, `os`, `pathlib`); existing `campaignlib.api` facade; external Codex CLI
0.150.1-compatible command surface; no new Python package  
**Storage**: Existing Markdown consistency report plus per-invocation temporary
directory; subscription credentials remain in Codex-owned storage  
**Testing**: pytest with mocked subprocess boundaries, existing seam/CLI
regressions, and an intentional manual authenticated smoke test  
**Target Platform**: Local Linux, WSL, or macOS command-line host with `codex`
installed and authenticated through ChatGPT  
**Project Type**: Python library and CLI, plus operator skills maintained in an
external dotfiles repository  
**Performance Goals**: One child process per audit; complete within the configured
timeout (600 seconds by default); start no MCP, plugin, browser, shell, or agent
processes  
**Constraints**: No child API credentials; forced ChatGPT authentication;
repository-instruction isolation; read-only sandbox; no executable tools, web
search, subagents, retries, or provider fallback; one text-only user turn; final
response only (no true token streaming); no UI selector; no persistent state
migration  
**Scale/Scope**: Single-operator, single-document audits with potentially large
campaign context and one Markdown report artifact

## Constitution Check

*GATE: Passed before Phase 0 research and passed again after Phase 1 design.*

| Principle | Verdict | Design evidence |
|---|---|---|
| I. Disk is Truth, the Model is a Draft | PASS | Only a non-empty Markdown report is persisted, and it remains a draft for review. |
| II. The Human Checkpoint is Non-Negotiable | PASS | The backend reports possible inconsistencies; the skill preserves explicit human approval before any correction. |
| III. Retrieval and Render are Separated | PASS | Existing prompt assembly and retrieval remain unchanged; the adapter only crosses the model boundary. |
| IV. Verbatim is Sacred | PASS | Input files are read unchanged and findings do not rewrite quoted source material. |
| V. One Seam per Boundary | PASS | All Codex process integration is centralized in `campaignlib/api/codex_cli.py` and reached through the existing API facade. |
| VI. CLI is the Engine, UI is a Face | PASS | The capability is implemented in the shared client and exposed first through `check_consistency.py`. |
| VII. Extract Once, Synthesize Deliberately | N/A | No extraction or synthesis pipeline is changed. |
| VIII. State is Discoverable | PASS | Success produces the requested report; failures are explicit CLI errors with no hidden fallback state. |
| IX. The UI Mechanizes; Claude Converses | PASS | The skill remains conversational and the file remains the interchange artifact. |
| X. Selection is Explicit; There is No Silent "All" | PASS | The command accepts one explicit document and continues to refuse Batch API operation for this backend. |
| XI. Parity is Bidirectional; Every CLI Capability Has a Face | PASS WITH EXPLICIT EXEMPTION | The user adopted GitHub issue #348, whose author explicitly deferred the frontend selector because this feature is for the consistency-skill workflow. That recorded human ruling supplies the constitution's narrow no-UI exemption. |
| XII. One Spelling per Option; No Configuration Drift Across CLIs | PASS | The shared spelling is `codex-cli`; `CG_CODEX_MODEL` and `CG_CODEX_TIMEOUT` are resolved once in the adapter boundary. |
| XIII. Breaking State Changes Migrate Out of Band | N/A | No config schema, workspace layout, or persistent filename convention changes. |

The post-design re-check produced no changed verdicts. Research narrowed the
isolation claim to what the verified CLI can enforce: repository/project
instructions, user-configured plugins/MCP, and executable tools are disabled;
administrator or bundled instruction metadata is not claimed to be absent.

## Project Structure

### Documentation (this feature)

```text
specs/015-codex-cli-backend/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── adapter.md
│   ├── cli.md
│   └── skills.md
└── tasks.md             # Created later by $speckit-tasks
```

### Source Code (repository root)

```text
campaignlib/
├── __init__.py
└── api/
    ├── __init__.py
    ├── client.py
    └── codex_cli.py     # New, sole Codex subprocess boundary

session_doc/
└── check_consistency.py

tests/
├── test_codex_cli_backend.py
├── test_check_consistency_codex.py
├── test_openrouter_seam.py
├── test_backend_seam_guardrails.py
└── test_no_credential_gate.py

docs/
├── cli/cli_tools.md
├── core/configuration.md
└── system/
    ├── component-campaigngenerator.md
    └── index.md

# Canonical external skill sources (separate repository/delivery unit)
/home/kroussos/src/mytools/dotfiles/codex/skills/
├── consistency-check/SKILL.md
└── staged-consistency/SKILL.md
```

**Structure Decision**: Preserve the existing shared-client architecture and add
one focused adapter rather than extending the already multi-provider
`backends.py`. Route selection and credential policy stay in `client.py`; the
consistency CLI stays a consumer of that facade. Skill edits target their
canonical dotfiles sources, not generated `~/.codex` links, and must be committed
or delivered separately from the CampaignGenerator change.

## Complexity Tracking

No unjustified constitutional violations remain. The only parity exception is
the explicit no-UI ruling recorded under Principle XI.
