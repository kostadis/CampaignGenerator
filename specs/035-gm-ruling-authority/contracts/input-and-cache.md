# Input, Audience, Cache, and Freshness Contract

## Selection resolution

Planning selectors are exact paths or scoped globs from `config/planning.yaml`. Resolution preserves the authored selector and records resolved path, stable record/section ID, reason, digest, and whether the path is external. Results are canonical-path deduplicated and deterministically sorted.

- Missing/unreadable required selector: refuse.
- Required zero-match selector: refuse.
- Explicit empty selection: refuse.
- A planning configuration with no `notes` field remains summary-only; when `notes` is configured it must be non-empty and every selector must resolve.
- Reviewed glob membership changed before run: refuse and require a new preview.

## Audience targets

- `gm`
- `players`
- `characters`
- `character:<stable-id>`

Filtering happens before any prompt, extraction, cache query, deterministic reference, fallback, preview/export, or audience-visible diagnostic is constructed. The policy receives independently classified records, never an entire mixed file. Player grants do not imply character grants.

Existing Summary Native outputs remain GM views. Existing summaries are GM-only by default. A non-GM input contains only complete stable source sections with matching content digests and explicit ledger grants for that audience. Required source with incomplete section coverage refuses; unclassified sections are excluded. It may not assume that summaries or dossiers are public.

`__document__` is the reserved support-only anchor. It grants the exact whole
file to a read-only deterministic adapter, requires a NoteRecord whole-file
digest, and is prohibited for source-correction rulings. It exists so valid
YAML and JSON never need an injected marker.

## Restricted source correction

A GM-only correction cannot become visible to a broader audience. The exact source section is anchored and digest-bound in the ledger. Source apply transactionally updates that section's content digest and retains its grants, unless changed grants are part of the exact reviewed proposal. Audience filtering selects anchored source bytes before extraction. The ledger governs visibility only and may not reinterpret unchanged contradictory source as corrected truth.

## Cache identity

The checked-note extraction cache key and sibling-range cache admission include:

- actual filtered payload digest;
- target audience;
- authority schema and policy version;
- relevant authority record IDs/revisions/metadata digests;
- selected section and source digests;
- selector membership digest;
- existing system/user/backend/model/token/chunk inputs.

Reuse is permitted only when all fields match. Restricted payloads never enter a broader-audience cache. `--force` ignores reusable cache as it does today but does not bypass audience filtering.

## Run-record manifest

Each run records the complete authority input manifest described in `data-model.md`. The record also names the selection preview digest the GM reviewed. Prompts saved for GM audit remain GM-only artifacts; any audience-visible diagnostic excludes forbidden content and metadata.

## Freshness

One shared manifest builder powers run recording and current-state comparison. A draft is stale or refused when any relevant value changes, including:

- ledger/schema/policy revision;
- record classification, status, scope, audience, subject, source, or supersession;
- note/source bytes or selected section bytes;
- selector expression or materialized membership;
- target audience or horizon;
- applied proposal/receipt digest;
- authoritative source digest;
- pending/nonterminal transaction status.

Prior generated artifacts remain stale after apply, withdrawal, audience changes, or note selection changes even when their Markdown file still exists.
