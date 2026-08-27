# Data Model: Thread Registry Surface (014)

**Date**: 2026-08-25 · **Plan**: [plan.md](./plan.md) · **Research**: [research.md](./research.md)

Three files on disk, all addressed through `<config>/projections.yaml`. Nothing
here is a database, and nothing is held in the browser (spec FR-023).

| Store | Config field | Format | Written by | Read by |
|---|---|---|---|---|
| Thread registry | `stores.thread_registry` | YAML | `thread_registry add/log/set-status/alias` | `grounding_sections` `threads` section; the Threads page |
| Proposals | `stores.thread_proposals` | YAML | `thread_registry propose` (harvest) and the **new** `rule` verb | the Threads page; `speculate`; **and `grounding_sections`' `emerging` section** — `SPECS["planning"]` declares `Section("emerging", source="thread_proposals", optional=True)`, so the engine's own *"nothing downstream reads this file"* preamble is already false, and every ruling makes the planning `emerging` section stale via `inputs_sha` |
| Adjudication bundle | `stores.thread_adjudication` **(new, D8)** | JSON | `thread_registry rule --status deferred` | a Claude conversation, and the GM |

---

## 1. Thread — the ratified unit of canon

Lives in `stores.thread_registry` under `threads:`. Shape as written today by
`cmd_add`:

| Field | Type | Rules |
|---|---|---|
| `id` | string | **Required, unique.** `check_registry` reports a thread with no id and a duplicate id. Used as the address for every verb. |
| `title` | string | Required. Its normalised form (`norm_title`) must not collide with another thread's title or alias. |
| `status` | enum | One of `open`, `dormant`, `resolved`, `abandoned`. Anything else fails `check`. |
| `opened` | int | The chapter the thread opened in. |
| `resolved` | int \| null | **Required when** `status` is `resolved` or `abandoned` — `check_registry` reports "status X but no `resolved:` chapter". |
| `tracker` | string \| null | Optional link to a GM arc score. **Arc scores are not threads.** |
| `aliases` | list[string] | Alternative titles. Each must normalise uniquely across the whole registry. |
| `notes` | string | Free GM text. |
| `log` | list[LogRow] | Ordered by `(chapter, change)` — `cmd_log` re-sorts on every append. |

**Identity rule (non-negotiable, FR-022)**: `match_thread` compares
`norm_title` of the title and every alias — *exact* normalised equality, never
similarity. `norm_title("Aletra's Boss") == "aletras-boss"`. Two titles that a
human would call the same thread but that normalise differently are **two
candidates for the GM to rule on**, not an automatic merge.

## 2. LogRow — one ratified per-chapter transition

| Field | Type | Rules |
|---|---|---|
| `chapter` | int | **Must be an `int >= 1`.** `check_registry` reports "log row without a real chapter number". This is why a chapterless candidate cannot be accepted unedited (research D4). |
| `change` | enum | One of `opened`, `advanced`, `resolved`, `reopened`, `abandoned`. |
| `summary` | string | Required. Prose the GM confirms; pre-fillable from evidence, never auto-committed. |
| `quote` | string | Optional. Carried verbatim from evidence when the extraction marked it `quote_verified` (Principle IV). |

## 3. Proposal (candidate) — harvested, un-ratified

Lives in `stores.thread_proposals` under `proposals:`, written by `propose`:

| Field | Type | Meaning |
|---|---|---|
| `norm` | string | The normalised-title key. **The address a ruling targets** — stable across re-harvests, which is what makes rulings survivable. |
| `title` | string | The representative surface title. |
| `all_titles` | list[string] | Every spelling seen in the corpus. |
| `matches` | string \| null | The ratified thread id this candidate matched, or null. Decides whether accept means `add`+`log` or `log` alone (research D3). |
| `chapters` | list[int] | Chapters it was found in. **May be empty** when no path segment carried a chapter number. |
| `status` | enum | `pending` \| `ratified` \| `rejected` \| `deferred`. |
| `evidence` | list[Evidence] | Up to 8 rows, sorted by `(chapter, fact)`. |

**Evidence** row: `chapter` (int \| null), `fact` (string), `quote` (string,
present only when `quote_verified`), `source` (string \| null — it is
`fa["source"].get("kind")`, so it can be absent or null; the card renders the
row without a source rather than printing "None").

**New fields the `rule` verb adds** (additive; `propose` must carry them through
the same way it already carries `status`):

| Field | Type | Meaning |
|---|---|---|
| `note` | string | Optional GM note recorded with the ruling. |
| `ruled_thread` | string \| null | On `ratified`, the thread id the ratification produced — the audit link from candidate to canon. |

## 4. Ruling — the state machine the GM drives

```
                 ┌────────────► ratified ──┐  thread exists in canon
                 │                   ▲     │  NOT terminal: re-offered with its
                 │                   └─────┘  unlogged chapters as they arrive
  pending ───────┼────────────► rejected ──► (terminal for the harvest)
                 │
                 └────────────► deferred ──┐
                                    ▲      │  writes an adjudication entry
                                    └──────┘  re-rulable: deferred → ratified | rejected
```

Rules:

- **One candidate per ruling act** (FR-007). There is no verb, route or control
  that takes a list.
- **Only `rejected` and `deferred` are terminal for harvest purposes** (GM
  ruling, research D17b). `propose`'s short-circuit must be narrowed to those
  two; today it also catches `ratified`, which would freeze an accepted thread
  forever — ratify at chapter 41 and chapters 50–60 never surface again.
- `deferred` is **not** terminal — it is "ask Claude, come back". It stays
  visible and re-rulable (FR-012).
- A `ratified` candidate falls through to the `matches` + `logged` filter and
  is re-offered carrying **only** its unlogged chapters, so re-harvesting is
  idempotent *and* a live thread keeps advancing (FR-009a).

## 5. Adjudication bundle — the conversation hand-off

JSON at `stores.thread_adjudication`. **Appends**, never overwrites: a
conversation may be in progress over an earlier entry (spec edge case).

```json
{
  "version": 1,
  "entries": [
    {
      "norm": "aletras-boss",
      "title": "Aletra's boss",
      "all_titles": ["Aletra's boss", "Aletra's mysterious boss"],
      "matches": null,
      "chapters": [30, 41],
      "note": "unsure this is distinct from the Carver's march",
      "evidence": [ { "chapter": 30, "fact": "…", "quote": "…", "source": "vtt" } ]
    }
  ]
}
```

Contract for the file: **self-sufficient**. Spec SC-007 is measured by handing
this file *alone* to a conversation and getting an accept/reject decision back —
so the evidence travels with the entry rather than being a pointer into the
proposals YAML.

## 6. Section row — the projection payload (US4)

Emitted per section by `grounding_sections list --doc <doc> --json`, consumed by
`GET /api/projections/sections`. Existing keys: `name`, `mode`, `state`,
`inputs`, `provenance` (+ `npc_count` for `per-npc`).

**Added (D11)**: `missing` — the subset of `inputs` that does not exist on
disk. Derived in the engine, where `section_inputs()` already knows; the browser
must not re-derive file existence. **`section_row()` has two return sites** —
the `npc_outlook` branch returns early, before the branch that computes
`missing` — so the key must be added at both, or the `per-npc` row arrives
without it and the Inputs cell breaks on that row alone.

`state` values, unchanged: `fresh` · `stale` · `unbuilt` · `no-input` ·
`optional` · `per-npc`.

## 6b. Backend credential — ~~a declared mapping~~ (withdrawn)

An earlier draft modelled `BACKEND_CREDENTIAL`, a per-backend map of required
environment variables, to feed a corrected pre-flight gate. **It was never
built.** The GM ruled the gate away entirely (#342, PR #343): each backend
checks its own credential at the call, so there is no second place for the
requirement to be declared and nothing here to model. Kept as a heading so the
numbering, and the fact that this was considered, both survive.

## 7. Validation summary — every refusal the surface must render

From `check_registry` and the verbs, all reaching the GM verbatim (FR-021):

| Condition | Message the CLI already produces |
|---|---|
| Duplicate thread id | `error: thread id 'X' already exists` |
| Title collides with an existing thread | `error: title 'X' matches existing thread 'Y' — use log/alias on it instead` |
| Alias collides | `error: alias 'X' already matches thread 'Y'` |
| Unknown thread | `error: no thread 'X'` |
| Bad status / change | `error: bad status 'X'` / `error: bad change 'X'` |
| Close without a chapter | `error: resolving/abandoning needs --chapter` |
| Any post-write invariant failure | `error: refusing to save a registry that fails check` (+ the per-problem lines) |
| Empty corpus glob | `no files matched: [...]` |
| Empty corpus **selection** | 400 from the route, not the CLI — no implicit "all" (Constitution X) |
