# Contract: `library_search` MCP tool (in `pipelines/rlm/mcp_server.py`)

```
library_search(query: str, limit: int = 10, per_book: int = 2) -> str (JSON)
```

## Returns

A SearchResultSet (see data-model.md), with each result's **full passage text**. Agents use it to:

- iterate over several wordings;
- read whole passages;
- quote them verbatim (FR-014).

## Errors

When the library is not configured, not built, has an embedder mismatch, or the guard refuses it, the tool returns `{"error": <code>, "message": <same text as the CLI refusal>}`. The codes are the same as the CLI exit codes, and the tool does not raise.

## Docstring guidance for agents

The tool's docstring is part of this contract. It tells the agent to:

1. try two or three wordings;
2. read the passages before recommending;
3. cite every recommendation as `title (book <id>) — <section path>`;
4. say plainly when nothing matches.

## Companion tool

`library_verify_citation(file: str, quote: str) -> str (JSON)` wraps the CLI `verify-citation`. The `library_search` docstring tells the agent to run it on every quote before presenting a recommendation, and to drop or flag any quote that fails (SC-002).

## Scope

The tool is read-only. It makes no render calls, so the Principle III isolation test applies to it.
