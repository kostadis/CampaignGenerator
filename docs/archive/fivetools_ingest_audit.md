# `fivetools_ingest.py` — Audit Against the 5etools Schema

**Audited file:** `/home/kroussos/src/CampaignGenerator-rlm/fivetools_ingest.py` (610 lines).
**Schema reference:** [`~/src/5etools-kostadis/JSON_FORMAT.md`](~/src/5etools-kostadis/JSON_FORMAT.md), [`~/src/5etools-kostadis/DATA_INVENTORY.md`](~/src/5etools-kostadis/DATA_INVENTORY.md).
**Audit date:** 2026-04-30. **Last refreshed:** 2026-05-01.
**Scope:** does the current ingest faithfully consume what pdf-translators produces *and* what the canonical 5etools `data/` corpus contains? What capability is preserved, lost, or never wired up?

---

## 0. Reading order under the three-pile model

This audit predates the **three-pile architecture** that the serene-harbor plan shipped in 2026-05-01. Read [`docs/rlm_architecture.md`](rlm_architecture.md) §1–§4 first for the model and §16 for the rejected alternatives. In short:

- The retriever consults the per-campaign palace **plus** two awareness catalogs (rpg-library over HTTP, `fivetools_catalog` in-process). It surfaces drawers/statblocks (already ingested) alongside cost-tagged candidates (not yet ingested).
- A **`candidate (cost: cheap)`** points at canonical 5etools JSON sitting in `~/src/5etools-kostadis/data/`. The ingest one-liner is `fivetools_ingest.py <path> --palace <campaign> --filter "name=…"` (or `chapter=N` for adventure-shape docs).
- A **`candidate (cost: expensive)`** points at a PDF in rpg-library. The ingest pair is `pdf_to_5etools_v2.py convert ...` then `fivetools_ingest.py ...`.

The Step 1 of that plan landed wrapper-key dispatch, the `_copy` resolver, and full statblock rendering — the three S1 gaps that this audit identified as schema-shape blindness. Batches A and B below are therefore **shipped**; Batch C remains enrichment-only post-MVP work. §6 below resolves the two decision points the audit closed with by referencing the plan's resolved D1, D2, and D6.

If a section of this audit conflicts with the architecture doc, the architecture doc wins — this audit is the historical gap analysis that the architecture is the answer to.

---

## TL;DR

**The headline gaps this audit identified — schema-shape blindness, statblock content loss, two-wing flattening — are closed as of Step 1 of the serene-harbor plan (commit `ceba57f`).** `fivetools_ingest.py` now dispatches on the wrapper key (`monster` / `spell` / `item` / `class` / `subclass` / `classFeature` / `subclassFeature` / `race` / `background` / `feat` / `*Fluff` / `data`), routes to the typed wing taxonomy from [`rlm_architecture.md §8`](rlm_architecture.md), resolves `_copy` cross-shard via `_meta.dependencies`, and renders full statblocks per `JSON_FORMAT.md §6.1`. The canonical 5etools tree at `~/src/5etools-kostadis/data/` is now ingestable at per-entity granularity via `--filter "name=…"` (catalog shape) or `--filter "chapter=N"` (adventure shape).

Step 3 (commit `f84144f`) added the retrieval surface that consumes this — `rpg_retriever.retrieve()` merges palace hits with `fivetools_catalog` cheap candidates and rpg-library expensive candidates into a single ranked tiered list.

**What's still open** is enrichment-only Batch C work — reprint canonicalization via `gendata-tag-redirects.json`, pre-built lookup ingestion (`gendata-spell-source-lookup.json`, `bookref-quick.json`), magic variant template expansion, `{@tag}` per-tag *metadata* extraction (the flattening for embeddings already shipped), and `--replace` actually replacing. None of these block correctness of the cheap-path ingest; they are quality-of-retrieval upgrades pending the cheap-path model demonstrating value on real campaigns.

The original "audit-as-of-2026-04-30" body that follows describes the pre-Step-1 state. Read §0 above for the current model and §4 for what's shipped vs. deferred. §6 closes out the two open decision points the original audit ended with.

---

## 1. What the ingest does today (faithful summary)

| Step | Code | Behavior |
|---|---|---|
| Validate | `validate_adventure_json` (line 97) | Loads `pdf-translators/adventure_model.py` and runs `parse_document`. **Adventure-schema validator only.** Will warn or error on a bestiary-only or spells-only file because the structure doesn't match. |
| Find top-level entries | `_iter_top_level_entries` (line 188) | Recognizes three shapes: `{adventureData: [{data: [...]}]}` (homebrew), `{data: [...]}` (official adventure), bare top-level list, or `{entries: [...]}`. **Does not recognize wrapper-key shapes** like `{spell: [...]}`, `{monster: [...]}`, `{item: [...]}`, `{class: [...]}`, etc. |
| Walk | `_walk_entries` (line 212) | Depth-first walks `entries: [...]` arrays, yielding every dict node with its section path (chain of parent `name` fields). |
| Route | `build_drawer` (line 248), line 270: `wing = "wing_bestiary" if is_statblock else "wing_rpglib"` | **Binary routing.** `statblock` / `statblockInline` → `wing_bestiary`; everything else → `wing_rpglib`. |
| Render content | `_render_entry_content` (line 301) | Emits a `# header\n\nbody` markdown blob per drawer. For statblocks: just `# Name\ntag:\nsource:\npage:`. For prose containers: header + flat text of *direct* children's `entry` strings. For tables: header + colLabels row only. |
| Idempotence | `read_state` / `write_state` / `file_signature` | Records `(json_path, size, mtime)` in `<json_dir>/.fivetools_ingest/<digest>.json`. Re-running on an unchanged file is a no-op. `--force` overrides. |
| Write | `mp_client.add_drawer(wing, room, content, metadata)` (line 502) | One `add_drawer` MCP call per drawer. Metadata fields: `entry_type`, `section_name`, `section_path`, `page`, `source_filepath`, plus rpglib-derived `book_id`, `display_title`, `publisher`, `game_system`, `product_type`, `series`, `tags`. Statblocks add `statblock_name`, `statblock_source`, `statblock_tag`. |
| Replace flag | line 495 | **No-op.** Comment: "deferred until that lands; for now `--replace` is a no-op with a warning so callers notice." |

The shape of input it expects: `pdf-translators/pdf_to_5etools_v2.py` output, which is an **adventure** JSON tree (a `data: [...]` array of `section`/`entries`/`inset`/`quote`/`table` blocks) optionally with a sibling `*-bestiary.json` produced by `--extract-monsters`. Both are walked by the same script — the bestiary file's monsters appear at the top level of `data` and get routed to `wing_bestiary` because they carry `type: "statblock"` (or `statblockInline`) markers.

---

## 2. Schema coverage matrix

What the current ingest does for each entity type the 5etools schema defines:

| Entity type | Wrapper key | Iterated? | Routed correctly? | Facets preserved? | Notes |
|---|---|:-:|:-:|:-:|---|
| Monster | `monster` | ❌ | ❌ | ❌ | Wrapper not iterated. Only finds monsters if they're embedded as `statblock` entries inside an adventure `data` tree. |
| Spell | `spell` | ❌ | ❌ | ❌ | Same. No `wing_spells`; level/school/components/range never extracted. |
| Item (magic) | `item`, `itemGroup` | ❌ | ❌ | ❌ | No `wing_items`. |
| Item (mundane) | `baseitem`, `itemProperty`, `itemType`, `itemMastery`, `itemEntry` | ❌ | ❌ | ❌ | The vocabulary tables that decode `item.property`, `item.type`, etc. are never loaded. |
| Magic variant | `magicvariant` | ❌ | ❌ | ❌ | Templates not expanded; `+1 Longsword` etc. invisible. |
| Class | `class` | ❌ | ❌ | ❌ | `class-<name>.json` files have FOUR parallel arrays (class/subclass/classFeature/subclassFeature); none iterated. |
| Subclass | `subclass` | ❌ | ❌ | ❌ | Same. |
| Class feature | `classFeature` | ❌ | ❌ | ❌ | Same. Level/className/classSource never indexed. |
| Subclass feature | `subclassFeature` | ❌ | ❌ | ❌ | Same. |
| Race / subrace | `race`, `subrace` | ❌ | ❌ | ❌ | No race data ingested. |
| Background | `background` | ❌ | ❌ | ❌ | |
| Feat | `feat` | ❌ | ❌ | ❌ | |
| Optional feature | `optionalfeature` | ❌ | ❌ | ❌ | featureType (EI/MV/FS/MM/etc.) never extracted. |
| Action | `action` | ❌ | ❌ | ❌ | The 48 generic actions (Dodge, Disengage, Grapple, …) referenced everywhere are never indexed. |
| Condition / disease / status | `condition`, `disease`, `status` | ❌ | ❌ | ❌ | Universal vocabulary referenced from monsters/spells/items via `{@condition}` — invisible. |
| Variant rule | `variantrule` | ❌ | ❌ | ❌ | Heavy `{@variantrule}` cross-ref target. |
| Deity | `deity` | ❌ | ❌ | ❌ | |
| Object / Trap / Hazard / Vehicle | `object`, `trap`, `hazard`, `vehicle`, `vehicleUpgrade` | ❌ | ❌ | ❌ | |
| Reward / Cult / Boon / Deck / Card / Recipe / Charoption / Psionic | various | ❌ | ❌ | ❌ | |
| Adventure prose | `data` (entries tree) | ✅ | ⚠️ | ⚠️ | Walked. Routed to `wing_rpglib`. Section path preserved as a metadata string. **No (id, chapter, header) chunking** — every nested entries dict becomes its own drawer regardless of size. |
| Sourcebook prose | `data` (entries tree) | ✅ | ⚠️ | ⚠️ | Same as adventure. The `book-<id>.json` files are very large (50k+ lines for PHB); the ingest would produce thousands of fragmented drawers, not the recommended "chunk by `(id, chapter, header)` with 2-3 paragraphs per chunk" shape from `DATA_INVENTORY.md` §2.4. |
| Statblock (inside adventure) | `type: "statblock"` | ✅ | ✅ | ❌ | Routed to `wing_bestiary`. **Content is a name+tag+source+page header; the actual stat block (AC, HP, attacks, traits, spellcasting, CR, immunities) is not in the drawer.** Comment at line 308: "the full stat block lives in the source JSON and is fetched by callers via source_filepath + name." |
| Fluff (any entity) | `<entity>Fluff` | ❌ | ❌ | ❌ | No `wing_lore`. The 91 fluff-bestiary-*.json files (479 KB of races art + 261 KB of recipes lore + ...) are never indexed. |
| Generated tables | `data/generated/gendata-tables.json` | ❌ | ❌ | ❌ | The 2,234-table corpus is invisible. The 13-entry `data/tables.json` would also be invisible (no `table` wrapper iteration). |
| Quick reference | `data/generated/bookref-*.json` | ❌ | ❌ | ❌ | Sliced rules from PHB/XPHB never ingested — the densest, highest-signal rules text. |
| Spell source lookup | `data/generated/gendata-spell-source-lookup.json` | ❌ | n/a | ❌ | Pre-built reverse index ("which classes grant spell X") never loaded as enrichment. |
| Tag redirects | `data/generated/gendata-tag-redirects.json` | ❌ | n/a | ❌ | Reprint canonicalization never applied. PHB Fireball and XPHB Fireball would index as separate drawers with no link. |

**Bottom line:** of ~30 distinct entity types in the 5etools schema, **only the adventure entries-tree is honored**, and even that loses (id, chapter, header) chunking. Every other entity type would either be invisible or — in the case of a hand-rolled mixed file — silently skipped because the wrapper key isn't recognized.

---

## 3. Severity-ranked gaps

### S1 — Schema-shape blindness (would render the corpus unusable)

**1.1 Wrapper-key wrappers are not iterated.** [`_iter_top_level_entries`](../fivetools_ingest.py) handles `data` / `adventureData` / `entries` / bare list, nothing else. Every catalog file in `~/src/5etools-kostadis/data/` is shaped `{spell: [...]}` or `{monster: [...]}` or similar — the contents are invisible to this iterator. **Fix:** add a wrapper-dispatch step that recognizes the ~30 wrapper keys from `JSON_FORMAT.md §1.1` and yields entities with their wrapper-type label so downstream routing knows *what* it's looking at.

**1.2 No `_copy` resolution.** The walker happily iterates `_copy` stubs as if they were complete entities. A `Goblin Boss` drawer would have no actions, no traits, no HP — just whatever `_mod` overrides happened to be inline. **Fix:** mirror `DataUtil.generic.copyApplier` from `~/src/5etools-kostadis/js/utils-dataloader.js`. Resolve `_copy` *before* walking. `_meta.internalCopies` declares which entity types in a file need this.

**1.3 Statblock content is empty.** Line 310: a statblock drawer's content is `# Aarakocra\ntag: creature\nsource: MM\npage: 12`. AC, HP, attacks, traits, spellcasting, CR, type, alignment, environment, immunities, languages — all dropped. The Chroma drawer has no facts to retrieve against; embedding-based search has nothing to embed. **Fix:** render the statblock per [JSON_FORMAT §6.1](~/src/5etools-kostadis/JSON_FORMAT.md) into a structured-but-readable text blob. Move CR / type / size / environment / sense / immunity facets into Chroma metadata so they become filterable.

### S2 — Routing too coarse for surgical retrieval

**2.1 Two-wing flatten.** Everything is `wing_rpglib` or `wing_bestiary`. A spell, an item, a class feature, a variant rule, an inset, a chapter — all the same wing. **Fix:** wire the typed-wing taxonomy from [`rlm_architecture.md` §8](rlm_architecture.md):

- `wing_bestiary` (already exists) — monsters
- `wing_spells` (new) — spells
- `wing_items` (new) — items + base items + magicvariants
- `wing_classes` (new) — class / subclass / classFeature / subclassFeature
- `wing_rules` (new) — variantrules + actions + conditions/diseases/statuses + bookref-quick + bookref-dmscreen
- `wing_rpglib` (already exists) — adventure + book long-form prose, chunked by (id, chapter, header)
- `wing_lore` (new) — all `fluff-*.json`

Routing dispatches on the wrapper key from §1.1, not on `entry.type`.

**2.2 Per-entity-type facet metadata is missing.** Even when an entity is correctly routed, the metadata dict has no type-specific fields. A `wing_spells` drawer should carry `{level, school, components_v, components_s, components_m, range_type, duration_type, classes, edition, source}` — these are the facets the user wants to filter on. **Fix:** per-wrapper-key extractors that pull the canonical filter facets ([`DATA_INVENTORY §2.1` for monsters, `§2.2` for spells, etc.](~/src/5etools-kostadis/DATA_INVENTORY.md)) into `metadata`.

**2.3 No `(id, chapter, header)` chunking for adventure/book prose.** Currently every nested entries dict produces its own drawer, so a single chapter can shed dozens of micro-drawers — many of which are headers with one sentence of prose. `DATA_INVENTORY §2.4` recommends "chunking by `id + header` (2-3 paragraphs per chunk) for retrieval." **Fix:** introduce a coarsening pass that merges sibling entries under the same `(adventure_id, chapter_ordinal, header_name)` until a token budget is reached.

### S3 — Missing retrieval enrichment

**3.1 `{@tag}` cross-references are not extracted.** Strings are stored verbatim; the `{@spell fireball|XPHB}`, `{@creature ancient red dragon|MM}`, `{@condition prone}`, `{@item +1 longsword}` mentions are not indexed as retrievable metadata. This is a major loss — queries like "what adventures reference the Cult of the Dragon" or "what spells does this monster cast" cannot be answered. **Fix:** at ingest, run a state-machine scan over each entry string (regex won't work; tags can nest with `|`), extract all `{@<page-tag> <name>|<source>}` references, and store them as parallel metadata arrays: `tag_creature: ["Goblin|MM", ...]`, `tag_spell: [...]`, `tag_item: [...]`, etc.

**3.2 Reprint canonicalization is missing.** PHB Fireball and XPHB Fireball get separate drawers with no link. **Fix:** load `gendata-tag-redirects.json` once at ingest start; for every entity, check whether its `(name, source)` is in a redirect and either skip (deduplicate) or attach `reprinted_as: <new_hash>` metadata. Surface `_meta.edition` (`classic` vs `one`) as a top-level facet so the user can scope queries to "2024 only" or "5e only."

**3.3 Pre-built lookups not consumed.** `gendata-spell-source-lookup.json` already answers "who can cast this spell" for every spell in the corpus — should be loaded once and merged into spell drawer metadata (`granted_by_classes: ["Sorcerer|PHB", ...]`). `bookref-quick.json` / `bookref-dmscreen.json` should be ingested into `wing_rules` as the highest-signal rules content. `gendata-tables.json` (2,234 tables) is the real table corpus and should populate a per-wing table-flagged metadata or its own room.

### S4 — Operational + correctness issues

**4.1 `--replace` flag is a no-op.** Re-ingesting a corrected JSON file leaves stale drawers in the palace — the new ingest succeeds and adds duplicates. **Fix:** depends on MemPalace MCP exposing a "delete drawers by metadata" call. Ticket against `mempalace-rlm` to add it; until then document the workaround (drop the room and re-mine the wing).

**4.2 `pdf-translators` default path is a fallback, not the canonical path.** Line 58: `_DEFAULT_PDF_TRANSLATORS = Path.home() / "src" / "5etools-kostadis" / "pdf-translators"`. Per `~/src/mytools/CLAUDE.md` the canonical path is `~/src/mytools/pdf-translators/`; the 5etools-kostadis path is a duplicate or stale checkout. **Fix:** change the default to the mytools path, and either drop the 5etools-kostadis fallback or make it a secondary search path.

**4.3 Per-source sharding requires explicit invocation.** `bestiary-<src>.json` × 106, `spells-<src>.json` × 17, `class-<name>.json` × 15. `python fivetools_ingest.py bestiary/` does not work — the script is one-file-at-a-time. **Fix:** add a `--data-root <dir>` mode that reads the loader manifests (`bestiary/index.json`, `spells/index.json`, `class/index.json`) and iterates the listed shards.

**4.4 No fluff loading.** The fluff files contain the *narrative* and *art* of every entity. Without them the bestiary is mechanics-only, the races have no flavor, and adventure entity references in dossiers are sterile. **Fix:** add a `wing_lore` route, key fluff drawers by `(parent_entity_name, parent_source)` so they can be joined to their parent at query time.

**4.5 Adventure validator is mismatched against catalog files.** `validate_adventure_json` runs `pdf-translators/adventure_model.parse_document` — that's the adventure schema. Pointing it at `bestiary-mm.json` will warn loudly and ingest anyway (line 449-454: "ingesting anyway"). **Fix:** dispatch the validator on the wrapper key. Adventure shape → `adventure_model`. Catalog shape → `5etools-utils` JSON Schema (per `~/src/5etools-kostadis/test/test-json.js`). Fluff shape → its parallel schema.

**4.6 Magic variant template expansion is missing.** `magicvariants.json` has 214 templates that expand against `items-base.json` to produce 200+ concrete items. **Fix:** at ingest, load `items-base.json` first, then walk `magicvariants.json::magicvariant`, expand each template per the `inherits` block, and emit the materialized items into `wing_items` with `expanded_from: "<template-name>|<source>"` metadata.

### S5 — Content-shape correctness inside adventure prose

**5.1 Container drawers carry only direct-child prose tokens.** Lines 330-341. A container with deeply-nested entries gets a header + the flat strings of its **direct** children. Grandchild entries are walked separately into their own drawers. This means a query that hits the container drawer sees only a thin slice of the chapter, and the natural unit "this whole scene" is never represented as one drawer. **Fix:** decide the chunking unit explicitly (recommended: by `(id, chapter, header)` with a 2-3 paragraph budget, per `DATA_INVENTORY §2.4`) and emit ONE drawer per chunk with the full prose in it. Skip emitting separate drawers for sub-headers below the chunking level.

**5.2 Tables are header-only.** Lines 345-350 emit the caption + colLabels row. The actual rows are dropped. A "Random Encounter, CR 5–10 Forest" table indexed by header alone is not retrievable by its content. **Fix:** render the full table (header + every row) into the drawer content. For very large tables, consider a per-row drawer with `table_name: <caption>` metadata so individual rows are retrievable.

**5.3 The `entries` block has many types beyond the 13 the script lists.** Line 73-76: `_PROSE_LEAF_TYPES = {"p", "paragraph", "quote"}`. `JSON_FORMAT §3.1` lists 30+ block types: `inset`, `insetReadaloud`, `quote`, `variant`, `variantInner`, `variantSub`, `list`, `image`, `gallery`, `link`, `dice`, `abilityDc`, `abilityAttackMod`, `bonus`, `attack`, `actions`, `item`, `itemSub`, `itemSpell`, `spellcasting`, `optfeature`, `patron`, `flowchart`, `flowBlock`, `statblockInline`, `refClassFeature`, `refSubclassFeature`, `refOptionalfeature`, `hr`, `code`, `homebrew`, `inline`. Most fall through to the "container" branch which renders only the header. **Fix:** explicit handlers for `list` (render items), `image` (render caption + alt), `spellcasting` (render the full block), `attack` (render structured attack), `flowchart` / `flowBlock` (render entries), refs (resolve and inline). Drop or comment-only the structural ones (`hr`, `wrappedHtml`, `inline`).

---

## 4. Remediation plan — current status

The audit findings split naturally into three work batches. **Batches A and B shipped in Step 1 of the serene-harbor plan** (commit `ceba57f` for wrapper-key dispatch + statblock render; commit `45f5c7d` and earlier for the supporting infrastructure). Batch C remains enrichment-only post-MVP work. Step 3 (`f84144f`) added the retrieval surface that consumes the now-ingestable corpus.

### Batch A — Make the ingest schema-aware (S1, S2.1, S4.5) ✅ shipped (Step 1)

The most important thing. Without it the ingest could not consume the canonical 5etools `data/` corpus at all, only adventure outputs from pdf-translators.

1. **Wrapper-key dispatcher.** ✅ `fivetools_ingest.detect_doc_kind()` reads `_meta` and dispatches; `iter_catalog_entities()` yields `(prop, entity)` over the wrapper-keyed shapes; `wing_for_wrapper_key()` maps each prop to the right wing.
2. **`_copy` resolver.** ✅ `fivetools_copy.py` (~500 LOC) ports `DataUtil.generic.copyApplier` — same-file + cross-file (`_meta.dependencies` + `<shard_dir>/index.json`) resolution, all `_mod` modes the canonical corpus exercises (append/prepend/replace/insert/remove/rename array ops, `replaceTxt`/`replaceName`, `setProp`, scalar ops, `addSenses`/`addSaves`/`addSkills`/`addSpells`/`maxSize`/`scalarMultXp`/`scalarAddHit`/`scalarAddDc`).
3. **Per-wrapper-key validator dispatch.** ✅ Adventure shapes use `adventure_model.parse_document`; catalog shapes use a kind-aware validator path that doesn't trigger the adventure-only warnings the audit complained about.

### Batch B — Surgical retrieval (S1.3, S2.2, S2.3, S3.1, S5) ✅ shipped (Step 1)

Once the ingest knew what kind of entity it was looking at, the typed wings + per-entity metadata + content rendering followed.

1. **Typed-wing routing** per [`rlm_architecture.md §8`](rlm_architecture.md). ✅ `fivetools_ingest._WRAPPER_KEY_WINGS` maps wrapper keys to `wing_bestiary` / `wing_spells` / `wing_items` / `wing_classes` / `wing_lore`. Adventure prose continues to land in `wing_rpglib`.
2. **Per-entity metadata extractors.** ✅ Each per-type renderer in `fivetools_render.py` pulls the canonical facets into the drawer's metadata (CR / type / size / environment / sense for monsters; level / school / classes / range / duration for spells; etc.). Per-type field coverage is best-effort and grows with new test fixtures rather than aiming for exhaustive coverage today.
3. **Statblock content renderer.** ✅ `fivetools_render.py` matches `JSON_FORMAT §6.1`: full statblock per drawer (AC, HP, speed, abilities, saves, skills, senses, languages, CR, traits, actions, bonus, reactions, legendary, mythic, spellcasting). End-to-end verified on Drow Priestess of Lolth (~2 KB drawer, full content).
4. **`{@tag}` flattening.** ✅ `strip_tags()` collapses `{@tag content|src}` to readable plaintext at render time so embedding-based search has real text to embed. Per-tag *metadata* extraction (parallel `tag_creature` / `tag_spell` / `tag_item` arrays for "what does this monster cast") is enrichment-only — see Batch C.
5. **Adventure/book chunking.** ⚠️ Step 3 added `--filter "chapter=N"` so the GM can ingest one chapter at a time; the per-`(id, chapter, header)` 2–3-paragraph chunking pass from the original audit is **not** the operative model. The current shape is "one drawer per top-level entries dict in the chapter," which `fivetools_catalog`'s ranking and the retriever's tier truncation absorb at retrieval time. Re-evaluate only if the cheap-path ingest produces drawer counts that degrade ranker quality in practice.
6. **Block-type handlers.** ✅ `fivetools_render.render_entries_block()` handles sections / lists / tables / quotes / refs / spellcasting. Structural-only types (`hr`, `wrappedHtml`, `inline`) drop through; see the renderer for the full list.

### Batch C — Enrichment + ergonomics (S3.2, S3.3, S4.1, S4.2, S4.3, S4.6) ⏳ post-MVP

Slots in cleanly on top of Batches A and B; intentionally deferred until the cheap-path on-demand model has demonstrated retrieval quality on real campaigns. **No timeline.** Estimated 1–2 days when picked up.

1. **Reprint canonicalization** via `gendata-tag-redirects.json`. Surface `_meta.edition` as a facet.
2. **Pre-built lookup ingestion.** Load `gendata-spell-source-lookup.json` and merge into spell drawers. Ingest `bookref-quick.json` / `bookref-dmscreen.json` into `wing_rules`. Ingest `gendata-tables.json` per-table.
3. **Magic variant expansion.** Load `items-base.json`, walk `magicvariants.json::magicvariant`, materialize.
4. **`--replace` actually replaces.** Coordinate with `mempalace-rlm` to add a "delete drawers by metadata" tool; until then, document the dropped-room workaround.
5. **`--data-root` batch mode.** Read loader manifests, iterate per-source shards. (Note: this overlaps with the rejected bulk-ingest design — see [`rlm_architecture.md §16.1`](rlm_architecture.md). If implemented, it should remain GM-driven, scoped per filter; not a "ingest the whole corpus" knob.)
6. **`{@tag}` *metadata* extraction (S3.1).** State-machine parser; emit `tag_*` parallel metadata arrays. The flattening for embedding-readability shipped in Batch B; the structured-cross-reference index is the deferred piece.
7. **Default `pdf-translators` path** → `~/src/mytools/pdf-translators/`. (Cosmetic; Step 3 handles the v2 path correctly via `suggest_conversion`.)

### Batch D — Tests and benchmarks (cross-cutting)

Each batch needs benchmark coverage in `tests/benchmarks/test_rlm_benchmark_rpg_gate2.py`. The current Gate 2 uses 15 RPG queries and passes. After Batches A+B and Step 3, the suite was extended to cover:
- ✅ Monster queries against canonical `bestiary-mm.json` (top-3 includes the right monster, with CR / type / environment metadata visible).
- ✅ Spell queries (level / school / classes routed through `wing_spells`).
- ✅ Adventure-prose queries (chapter ordinal retrievable; `--filter "chapter=N"` exercised).
- ⏳ Reprint-aware queries (PHB-rooted query returns XPHB result via redirect) — pending Batch C.

---

## 5. What works today, unchanged by this audit

To keep the audit balanced — these are not problems:

- **Idempotence via `(size, mtime)` sidecar.** Correct, atomic, simple.
- **rpglib metadata snapshot at ingest time.** Correct architectural choice — keeps retrieval single-DB. Per the comment at line 137-138, switching to MCP is a one-function rewrite.
- **Section-path metadata.** The `book → chapter → scene` chain is preserved as a delimited string per drawer. Useful for human-readable provenance in dossier proposals.
- **Statblock metadata fields.** `statblock_name`, `statblock_source`, `statblock_tag` are extracted correctly into metadata even though the drawer content is sparse.
- **Validation as warning, not block** (line 449-454). Ingest proceeds with warnings, which is the right call for a research-grade tool — the alternative is brittleness.
- **Stdio MCP write path via `mempalace_client`.** The split between "this script knows shape, the client knows protocol" is clean.
- **The retrieve/render isolation guard.** `fivetools_ingest.py` is a pure ingest script with no Claude API calls — passes the CI invariant.

---

## 6. Decision points — resolved

Both questions the audit closed with were resolved during the serene-harbor plan and are now fixed contracts. Recorded here for posterity; pull from the parent plan's "Step 3 design decisions (resolved)" section if a future change wants to revisit.

### 6.1 One reference palace, or one per source-game-system?

**Resolved per D1 (serene-harbor plan):** **per-campaign palace, no shared reference palace.** Both 5etools-derived drawers and campaign narrative drawers land in the active campaign's palace (`~/.mempalace/palaces/<campaign>/`). There is **no** shared `dnd5e` palace, no `--palace ad&d`, no `--palace pathfinder` — those would be pre-bulk-ingest designs and bulk-ingest is rejected ([`rlm_architecture.md §16.1`](rlm_architecture.md)).

The same Drow Priestess statblock gets re-ingested per campaign that asks for it. At cheap-path millisecond ingest cost this is the right trade. The "save the cost of re-ingest" argument is for PDF conversion (minutes + API spend), not JSON reads — so a shared palace would optimize the wrong axis. Co-mingling content across campaigns also breaks ranker scope and the GM-checkpoint discipline ([`rlm_architecture.md §16.2`](rlm_architecture.md) for the full reasoning).

**Mechanics shipped in Step 3:** the retriever resolves the active palace from `config.yaml` via `find_default_config(__file__)`. `rpg_search` accepts an optional `palace` arg as override. Wing taxonomy unchanged: `wing_bestiary` / `wing_spells` / `wing_rpglib` for 5etools-derived content alongside the existing per-campaign narrative wings.

### 6.2 Canonical 5etools corpus, or only converted-from-PDF content?

**Resolved per D2 + D6 (serene-harbor plan):** **both, with canonical as the cheap default and pdf-translators as the expensive fallback.** The retriever consults two awareness sources on every query:

- `fivetools_catalog.search()` over `~/src/5etools-kostadis/data/` — surfaces 5etools-canonical entities as **`candidate (cost: cheap)`**. Ingest one-liner: `fivetools_ingest.py <path> --palace <campaign> --filter "name=…"` (or `chapter=N` for adventure shape).
- rpg-library HTTP API — surfaces unconverted PDFs as **`candidate (cost: expensive)`**. Ingest pair: `pdf_to_5etools_v2.py convert ...` + `fivetools_ingest.py ...`. Carries the identifier triple `(book_id, relative_path, product_id)` (per D7) so persisted references survive a rpg-library re-index.

Bulk-ingest of the canonical corpus is rejected ([`rlm_architecture.md §16.1`](rlm_architecture.md)) — even though it's only 106 MB, cold content pollutes retrieval and bypasses the GM-as-checkpoint discipline. Per-entity on-demand cheap ingest is the only supported way 5etools-canonical content reaches the palace.

The first ingest target for any new campaign is whatever the GM's first query surfaces as a `candidate (cost: cheap)`. For an OotA campaign that is typically `~/src/5etools-kostadis/data/adventure/adventure-oota.json --filter "chapter=0"` (Velkynvelve) — see the walkthrough at [`rlm_architecture.md §4.3`](rlm_architecture.md). pdf-translators only fires when the canonical tree has no relevant content (third-party PDFs, AD&D modules, homebrew).
