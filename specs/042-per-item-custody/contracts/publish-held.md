# Contract: publish held reasons (US4)

Each NPC still gets its own outcome. A hold for one never stops another (FR-012).

| Cause | `PublishResult.reason` / receipt `reason` | Receipt extra |
|---|---|---|
| The draft changed after composition (the existing check, now names the path) | `draft changed after composition: <draft display path> (changed); run \`summary_native npc-compose\` and recheck it` | `custody_changed: [{"path": <draft>, "state": "changed"}]` |
| The sign-off's dependency set changed (FR-011) | `NPC_DRAFT_SIGNOFF_STALE: sources changed since review <rid> was built: <path> (<state>)[, <path> (<state>)…]; run \`summary_native review refresh <rid> --expected-generation <n>\`, then re-verify and re-sign` | `custody_changed: [{"path", "state"}, …]` |
| There is no current sign-off for these bytes (existing, unchanged) | `NPC_DRAFT_SIGNOFF_REQUIRED: exact draft approval is missing or stale; create a real NPC verification review and run \`summary_native review npc sign\`` | — |
| The draft changed between the check and the write (FR-012) | `NPC_DRAFT_CHANGED_AT_WRITE: <draft display path> changed after its sign-off was checked; nothing was written for this NPC` | `custody_changed: [{"path": <draft>, "state": "changed"\|"missing"}]` |

Rules:

- When several ledger records sign the same draft bytes, which happens with a carried sign-off, the NPC publishes if **any** of them is current, as today. The `NPC_DRAFT_SIGNOFF_STALE` reason names the files of the **most recent** stale one, by `recorded_at`.
- With a spec 039 `dependency_graph`, a record is current only if both of these hold:
  - every source in its FR-003/FR-004 set ∪ the graph's dependencies (where those are custody paths) is `current`;
  - `graph.item_stale(...)` is false.

  The graph can widen the set, never narrow it (FR-011).
- The written body is always the `item.body` planned from the GM dossier whose header names the checked draft sha (research R13).
- Paths use `schema.display_path`, which is campaign-relative.
