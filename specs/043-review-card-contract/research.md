# Research: Review Card Contract (043)

Every decision below comes from reading the code on `main` at `33aadfc`. The CampaignGenerator review package is `pipelines/summary_native/review/`. The two kits are in `~/src/mytools/dotfiles/`, read only:

- K is `claude/skills/_shared/review-artifact/`;
- C is `codex/skills/_shared/review-page/`.

File and line references are to those trees.

## R1: Where the packet lives, and how it is written

**Decision**:

- **Location.** `docs/reviews/<review>/packets/<packet_id>.json`.
- **How it is written.** One journaled transaction under the exclusive `authority_lock`, after `require_no_pending_transaction`. This copies `export_review` (store.py:877-899): build, hash, write only if absent, then `_prepare_transaction_locked` and `recover_transaction(_already_locked=True)`.
- **The id.** `packet_id = "packet-" + sha256(canonical_bytes(body))[:20]`.
  - The body has no timestamp. So the same review state exports to the same id, and a re-export is an idempotent no-op returning the existing packet.
  - If the path already exists with different bytes, export refuses with `REVIEW_CARDS_PACKET_CONFLICT`.
- **Alteration.** At decide time the stored file is re-read and re-hashed. If the digest no longer matches the id, decide refuses with `REVIEW_CARDS_PACKET_ALTERED` (spec edge case: packet edited by hand).

**Rationale**: `exports/` and `runs/selections/` (verification.py `preview_rerun`) are the existing precedents for an immutable artifact inside a review. A content-addressed id makes the alteration check free, and makes duplicate exports harmless (spec edge case: two packets from one review).

**Alternatives**:

- A random id plus a stored digest. Rejected: it needs two fields to agree, and repeat exports pile up.
- Keeping the packet outside the review, handed to the agent. Rejected by FR-001: the GM must not hold the only copy.

## R2: Which items a packet covers, and how cards are built

**Decision**: cards are built in CampaignGenerator by porting `npc_review_items.py`'s rules (K/npc_review_items.py:121-310). The kit copy is then deleted (R12).

- **Review kind.** Only `npc_verification` reviews, in this slice. Any other kind is refused with `REVIEW_CARDS_KIND`. Identity and document reviews are out of the spec's scope.
- **Items covered.** An item belongs in the packet when it has **no current approve or reject**. "Current" means on the item's current revision and digest, and not in `stale_ids`. This is `delegated._current_decision`, restricted to approve and reject.
  - A Discuss is not a ruling, so a discussed item is re-offered. This matches the kit's `current_decisions` (:67-80).
  - When the GM later marks it, the change is a listed supersede (spec edge case: Discuss later approved).
- **Noise class cards.** Members are the item's undecided noise items of exactly one code. This is `delegated._noise_members`, so the class rule has one home (V).
  - Card id: `noise-class:<class>`.
  - A class with no undecided members gets no card.
- **Sign-off cards.** One member, the `signoff_npc_draft` item. The card carries `draft_sha256` from the item's details and the draft text.
  - Export runs `npc_signoff_blocker` (delegated.py:79-97). A sign-off already stale at export is **not** carded. It is listed in the export result as `skipped_signoffs` with the blocker code.
  - The kit's `--allow-stale` (render a STALE card) is dropped. A card the GM cannot validly approve is never shown as approvable.
- **Finding cards.** One card per remaining item, one member.
- **Card ids.** The card id of a single-member card is its item id. Item ids are ASCII (#630).
- **Order.** The kit's order is kept: noise class cards first, in `noise.CLASSES` order; then per draft, findings in line order, then the sign-off.
- **Filters.** `--item ID` (repeatable) and `--action NAME` (repeatable) narrow the packet. They keep parity with the kit's `--ids` and `--action` so the shim loses nothing.
  - Neither filter is a silent "all" (X). Export **decides nothing**: a packet is an offer, and only an explicit card verdict records anything.

**Rationale**: FR-020 moves card building out of the kit. Porting the existing rules keeps the GM's page unchanged on day one.

## R3: One expansion rule (FR-008)

**Decision**: a new pure function in `review/cards.py` does the expansion. Both `review cards decide` and `plan_noise_class` call it:

```text
expand(snapshot, *, member_ids, verdict, disposition_for, gm_note) -> Expansion
```

- For every member it validates the pair with `store._validate_action_decision`. It classifies the member against the store as `new`, `identical` or `differs` (see R5), and computes `expected_decision_revision` from the live events.
- `plan_noise_class` keeps its own **policy** over that classification:
  - `identical` or `differs` both mean "already decided, skip". That is today's behaviour, required by FR-023.
  - Its note text is unchanged: `GM class verdict on batch card [noise-<class>] (<n> occurrences): <note>`.
- `cards decide` turns `differs` into a listed supersede.
- The latest-decision lookups in `delegated.py` (`_latest`, `_active_revision`, `_current_decision`) become the single implementation that `cards.py` imports.
  - `cli.py`'s own `_fresh_decision` and `store.review_status`'s inline copy are **not** touched. Unifying them is not needed for this feature, and it would change `review status` counts.
  - That third copy is filed as a follow-up issue.

**Alternatives**: putting the expansion in the kit (status quo). Rejected; that is the defect.

## R4: Verdict to disposition (FR-009) and the #655 table (FR-016, FR-017)

**Decision**:

- **Where the map lives.** `cards.DISPOSITION_FOR[(action, verdict)]` is the one map from a page verdict to a stored disposition.
- **Approve.**
  - A sign-off (`signoff_npc_draft`) maps to `document_signoff`.
  - Any finding (`review_claim_against_evidence`, `review_presentation`, `review_classified_noise`, and the other verification actions) maps to `accept_no_change`.
- **Reject** maps to `reject_action`, and **Discuss** to `defer`, for every action.
- **The store table.** `_validate_action_decision`'s `allowed_by_action` gains a row for **every action the code produces** (table in the research report: verification.py `_action`, review/cli.py, claims/cli.py):

| Action | Allowed pairs |
|---|---|
| `review_claim_against_evidence`, `review_presentation`, `review_classified_noise`, `rerun_selected_check`, `repair_or_recheck_pointer`, `review_supersession`, `review_audience_and_knowledge`, `acknowledge_claim_coverage` | approve/accept_no_change, reject/reject_action, discuss/defer |
| `adjudicate_identity` | approve/merge, approve/distinct, reject/reject_action, discuss/defer (identity.py:103, :1913 read `distinct` and `merge`) |
| existing rows and the sign-off branch | unchanged |

- **Fail closed.** The `if allowed is None: return` branch becomes `REVIEW_ACTION_MISMATCH: no decisions are declared for action <a>`.
- **What the table does not cover.** `approve/source_correction` stays limited to `prepare_claim_source_correction`. No test or document records `source_correction` on an NPC verification action. Correction proposals go through `review correction prepare` on claim items (spec 036 data-model).

**Verification gate**: the full suite must pass with the stricter table. Any existing test that records a pair outside the table is a **stop-and-ask**, not a table widening. The suite is the inventory of real GM workflows.

**Rationale**: every path into the store (`review decide`, routes, the capability web app, `npc sign`, delegated commands, `cards decide`) ends in `save_decisions`, which calls `_validate_action_decision`. One table therefore covers every path (SC-004).

## R5: Diffing against the store (FR-011, US3)

**Decision**: "identical" means the same `verdict`, the same `disposition` and the same `note` as the member's current, fresh decision. Otherwise:

- a fresh decision that differs is a **supersede**, recorded with `expected_decision_revision` set to the live active revision;
- no fresh decision means the member is **new**.

To keep re-exports and re-saves stable, the note `cards decide` stores **carries no packet id and no counts**:

```text
GM card verdict [<card_id>]: <gm note>      (or just "GM card verdict [<card_id>]" when the note is empty)
```

- So the same verdict and note saved from a later packet is a no-op, not a spurious supersede.
- A CLI decision on the same finding with any other note is a listed supersede (US3 scenario 3).
- That is never silent, and never a whole-file refusal.

**The member's own revision.** If a member's `item_revision` or `review_digest` no longer matches the packet's, the item itself moved and the packet is stale for that member. The card is refused with `REVIEW_CARDS_MEMBER_STALE`, listed in the plan. A generation move refuses the whole packet first (R7).

## R6: Provenance (FR-015)

**Decision**: provenance goes in the request id, and there is no model change.

- `DecisionEvent` has no packet field and is `extra="forbid", frozen` (models.py:563-603).
- But every event already stores its `request_id`, and every request has a receipt under `requests/`.
- `cards decide` submits with `prefix = f"cards-{packet_id}"`, so each request id is `cards-<packet_id>-<20 hex>`. That fits the store's charset and needs no schema change.

So "which decisions came from packet P" is a filter on `request_id`. `review history` already shows events.

**Alternatives**:

- A new optional `packet_id` field on `DecisionEvent`. Rejected: it changes a persisted model's shape (XIII) for information the existing field already carries.
- The packet id in the note. Rejected, because it breaks R5's stability.

## R7: Refusal granularity

**Decision**: two tiers.

**The whole file is refused** (nothing recorded, store byte-identical, SC-002) when the file's contract is broken:

| Refusal | Code |
|---|---|
| Unknown schema version | `REVIEW_CARDS_SCHEMA` |
| A key outside the schema | `REVIEW_CARDS_INVALID` |
| Packet missing | `REVIEW_CARDS_PACKET_UNKNOWN` |
| Packet altered | `REVIEW_CARDS_PACKET_ALTERED` |
| Review id differs | `REVIEW_CARDS_REVIEW_MISMATCH` |
| Packet generation is not the manifest's | `REVIEW_CARDS_PACKET_STALE` (exit 3; remedy: export a new packet) |
| Unknown card id | `REVIEW_CARDS_UNKNOWN_CARD`, naming every offending id |
| Echoed member list differs | `REVIEW_CARDS_MEMBER_MISMATCH`, naming the cards |
| Sign-off echo differs from the packet's fingerprint | `REVIEW_CARDS_FINGERPRINT_MISMATCH` |
| Note over `max_note_chars` | `REVIEW_CARDS_NOTE_TOO_LONG` |

**A card is refused** (listed under `refused` in the plan, with the rest still recorded) when the problem is the **freshness of the world, not the file**:

- **A sign-off whose draft bytes no longer match** gives the `npc_signoff_blocker` code, for example `REVIEW_NPC_SIGNOFF_STALE`. This applies to Approve, which is the only verdict that signs. A Reject or Discuss on a sign-off records no signature, so it needs the echo check only.
- **A member whose item moved** gives `REVIEW_CARDS_MEMBER_STALE`.
- **A member whose source custody is stale** gives `REVIEW_STALE_CUSTODY`, with the spec 042 detail. Planning calls `custody.stale_report` over the members to be recorded. Stale cards drop out of the batch, so `submit_decisions`' pre-check then passes.

**Rationale**: a structural error means the page or file is wrong, so trusting any of it is unsafe (US2). A stale draft means the GM's other rulings are still valid, and the GM confirmed the plan that lists the refusal (R8). This matches US2 scenario 5 ("refuses that sign-off and names the draft").

## R8: Plan, then write (FR-012), and the confirmation hash

**Decision**:

- **Dry run by default.** `cards decide` follows `carry`, `policy` and `noise decide` (XII): it is a dry run unless `--write`. It needs `--reviewer`, because the decisions file carries no reviewer (FR-005) and the store requires one.
- **The plan hash.** The plan is a canonical document: per card and member, it gives the category and, for records, the exact decision dict including `expected_decision_revision`. Its `plan_sha256` is reported.
- **`--write` requires `--plan-sha256`.** The flag is spelled as `review migrate` spells it. Decide rebuilds the plan, and refuses with `REVIEW_CARDS_PLAN_CHANGED` if the hash differs.

So what is recorded is exactly what the GM saw (US1: "shows a plan … then records exactly that"). A concurrent CLI decision between plan and write cannot slip a different set through.

**Alternatives**: `--write` without a hash. Rejected; the plan would be advisory, and the UI's "confirm" would confirm nothing.

## R9: Batches across the 100-decision cap (FR-013)

**Decision**:

- **Packing.** Records go through `submit_decisions`, with batches packed **card-aligned**: greedy, never splitting a card unless one card alone exceeds the cap. A 300-member noise class necessarily spans transactions.
- **Partial failure.** `submit_decisions` gains structured partial reporting. When a later batch fails, it raises with `detail = {"recorded": [item ids], "not_recorded": [item ids], "cause": <inner detail or null>}` in place of the prose-only count (delegated.py:395-401). `cards decide` relays it as the envelope's `data`, with the inner code.
- **Effect on existing commands.** `noise`, `carry` and `policy` get the same structured detail for free. That is additive, and their behaviour is unchanged (FR-023).
- **Recovery.** Request ids are content-derived, and R5 makes recorded members no-ops. So **re-running the same decide finishes the job**. The plan after a partial save shows the recorded members as `noop` and the rest as `new`.

## R10: The decisions-file shape, and why it echoes members and fingerprints

**Decision**: the decisions file is

```text
{schemaVersion, packetId, reviewId, savedAt, cards: {card_id: {verdict, note?, members, draftSha256?}}}
```

- `members` is required for every marked card. It is the member list **as the page received it**, echoed back.
- `draftSha256` is required for every marked sign-off card.
- No other key is accepted. Unmarked cards are simply absent.
- The file carries no dispositions, revisions or packet body (FR-005).

**Why echo**: the echo is evidence of **what page the GM looked at**, not data decide trusts.

- Decide compares each echo with the stored packet, and refuses on any difference (FR-007, US2 scenario 5).
- A page built from an older packet, a hand-edited file, or a page that regrouped cards is caught. Decide still expands from the **stored** packet, never from the echo.

**How pages produce it**: the shared kit passes extra card fields through to the page (K/CONTRACT.md:299-301). So the packet's `members` and `draftSha256` ride in the page's `ITEMS`. The kit's NPC decision reader takes them **from the saved page bytes**, so the echo comes from the page itself and not from a fresh export.

**`savedAt`**: required and non-null, which keeps the kit's "an unsaved page is not a save" rule (K/read_decisions.py:126-129).

## R11: Schemas, golden fixtures and versioning (FR-018, FR-019, SC-005)

**Decision**:

- **One source for each shape.** The packet and the decisions file are strict pydantic models (`extra="forbid"`) in `review/cards.py`. That one model set is CampaignGenerator's validator.
- **The published schemas** are `pipelines/summary_native/review/schemas/card-packet.v1.schema.json` and `card-decisions.v1.schema.json`. They are generated from the models (`model_json_schema()`) and checked in.
  - A test regenerates them and compares with the checked-in files. A shape change not reflected in the schema fails (SC-005).
  - The schemas are added to pyproject's `force-include`, alongside the web viewer files.
- **Golden fixtures** live in `tests/fixtures/review_cards/`. They are a packet exported from the `_custody_fixture` review and a decisions file of the kit's shape.
  - Tests validate them, and every exported packet in the suite, with `jsonschema`. They also assert a round trip (parse, dump, then equal bytes).
  - `jsonschema` is added to the `test` extra in pyproject. It is installed in `~/.venv` (4.26.0) but undeclared, and the only user today guards it with `importorskip`.
- **Versioning.** `schemaVersion` is an integer **major** version. CampaignGenerator accepts `{1}` and refuses anything else with `REVIEW_CARDS_SCHEMA: schemaVersion <v> is not supported; accepted: [1]`.
  - Additive changes are not possible under `extra="forbid"` without a version bump. That is deliberate in a single-user system: the kit and CampaignGenerator move together.

**Text safety (US4 scenario 3)**: every packet text field is a plain string, never HTML. The schema describes the fields as plain text, and CampaignGenerator never converts them.

- The **kit shim** HTML-escapes them before they reach `build_review.py`, whose `y`, `n` and `ev` fields render as markup.
- A kit test puts `<script>` and `<b>` in campaign text and asserts they arrive escaped in the page.
- A CampaignGenerator test asserts the packet carries the literal characters.

## R12: The kit after this feature (FR-020, FR-021, US5)

**Decision**: one kit, `review-artifact`, with a canonical home under `dotfiles/shared/` and linked into both agents' trees.

- **NPC builder.** `npc_review_items.py` becomes a shim.
  1. It runs `summary_native review cards export REVIEW --out <tmp> --json`, and maps `--ids` to `--item` and `--action` to `--action`.
  2. It reads the packet copy from `<tmp>`. That is a CLI output, not a store file.
  3. It maps each card to a kit item. Text is escaped (R11). `members` and `draftSha256` are passed through, and `reviewId` is the packet id.
  - It no longer opens `manifest.json`, `items/` or `events/`. A test asserts that no kit file references `docs/reviews` or those names (SC-006).
- **NPC reader.** `read_decisions.py --npc` reads the saved page and writes a contract decisions file (R10). It takes `members` and `draftSha256` from the saved page's `ITEMS`, and `reviewId` from a flag.
  - Applying the file is `summary_native review cards decide`. The class-card expansion (:164-218) and the `classes` output are deleted from the kit. That expansion now lives only in CampaignGenerator (FR-008).
- **One kit for both agents.**
  - `build_review.py` gains `--save artifact|local` (default `artifact`). `local` produces the C page's save surface: Copy output, a Save output download, and Save to VM when served, all keyed on the `codex-review-save` meta.
  - `read_decisions.py` gains C's `--in decisions.json` mode and its `normalize()`.
  - C's `serve_review.py` moves into the kit **unchanged**, including its bind default. Hosting is slice 2's to change.
  - C's tests move with it.
- **Paths and links.**
  - The canonical directory becomes `dotfiles/shared/skills/_shared/review-artifact/`. `claude/skills/_shared/review-artifact` and `codex/skills/_shared/review-artifact` are symlinks to it.
  - `skill-layout.json` moves `_shared/review-artifact` out of `claude_only`, and drops `_shared/review-page` from `codex_only`. `check-skill-sync.sh` and `tests/test-codex-links.sh` must pass.
  - The Claude-side path `~/.claude/skills/_shared/review-artifact/...` is unchanged, so the ~15 Claude skill references keep working.
  - **Fallback.** If `check-skill-layout.py` cannot express a shared `_shared/` directory, the layout script gets the smallest change that does. The real directory stays in `claude/skills/_shared/` with a Codex-side link. The decision is made by running the layout check, not by guessing.
- **Codex references.** Every Codex reference to `_shared/review-page` changes to `_shared/review-artifact`, and the pages are built with `--save local`. That covers the SKILL.md files, `dialogue-edit/references/review-and-apply.md`, the dialogue-edit test, `vtt-spell-pass/render_review.py:18`, and `_shared/batch-chapters/batch.py:46`. Then `codex/skills/_shared/review-page/` is deleted.

**Conflict with the GM's uncommitted work.** In the mytools main checkout, `codex/skills/vtt-spell-pass/SKILL.md` has the GM's uncommitted 5-line hunk at :428. The retirement edits other lines of the same file (:1034, :1051-1055, :1138).

- The mytools work is done in a separate worktree, so the GM's checkout is never touched.
- But once the PR merges, a pull into the dirty checkout will refuse to overwrite that file until the GM commits their hunk.
- **Resolved (GM ruling, 2026-11-12).** The GM's edits were committed and merged as mytools #114 (`5c5e5d5`). The 043 kit branch starts from that main.

## R13: The web face (FR-022, XI)

**Decision**: two routes in `server/routers/review_routes.py`, each one fixed argv through the existing bounded JSON runner (VI):

- `POST /api/reviews/{id}/cards/export`, body `{items?: [str], actions?: [str]}`, runs `review cards export ID [--item …] [--action …]`.
- `POST /api/reviews/{id}/cards/decide`, body `{decisions_path: str, reviewer: str, write: bool, plan_sha256?: str}`, runs `review cards decide ID --decisions PATH --reviewer R [--write --plan-sha256 H]`.
  - The path goes through `_contained_file`, so it must be inside the campaign and exist.
  - The file stays on disk, the interchange (IX). The browser never uploads or holds it.

The new codes map through `_status_for`:

- `…_STALE` gives 409;
- `…_MISMATCH` gives 422;
- `REVIEW_CARDS_PACKET_UNKNOWN` gets an `_EXACT_STATUS` entry for 404;
- the other refusals give 400.

**`ReviewLauncher.vue`** gets one "Card packet" fieldset. It has three controls:

- **Export** shows the packet id, the card count, the member count and `skipped_signoffs`.
- **Plan** takes the decisions path and the reviewer, and shows the plan grouped as record / noop / supersede / unmarked / refused.
- **Confirm** is enabled only after a plan, and sends that plan's `plan_sha256` with `write: true`.

Refusals render the CLI message and `data` exactly as the existing panel does (US6 scenario 3).

## R14: Performance (SC-007)

**Decision**:

- **Export** reads the snapshot once under a shared lock. It hashes each NPC draft once, for the sign-off blockers, about 165 drafts, then writes one file.
- **Decide** reads the snapshot once. It runs `custody.stale_report` once over the to-be-recorded items, which is spec 042's per-item cost. It re-hashes each approved sign-off's draft once, and submits ⌈n/100⌉ transactions.
- **The 800-item test.** `_custody_fixture.build(extra_npcs=…)` scales to about 800 items. A test asserts that export and a full decide each finish well inside 60 s, timed loosely to avoid CI flake. The real stormgiants review is never written to (standing rule). An optional `STORMGIANTS` replay may run **export only** against a copy in `tmp_path`.

## R15: Testing in a worktree

The editable install's `.pth` points at the main checkout, so tests run with `PYTHONPATH=$WT`, and the first line of the quickstart proves which tree is imported (spec 042 R15). `--basetemp` must have an existing parent directory (`mkdir -p`). A missing one gave 5125 setup errors during #644.
