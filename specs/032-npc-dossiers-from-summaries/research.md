# Research: Summary-Native NPC Dossiers (032)

Each decision gives what was chosen, why, and what else was considered. Codebase references are as of `main` @ `9fcc3ae`.

## R1 — What makes an NPC "global"

- **Decision:** An NPC is global when it is a registry entity with `type: npc` **and** `scope: persistent`, **and** it is not a player character. A player character is one named in `<config>/players.yaml` `plays` (the campaign's one declaration of who plays whom), resolved to a registry entity by exact name or exact alias (`Thorin Giantfriend` → `Thorin`); its exclusion reason is `player character (players.yaml)` (GM ruling 2026-10-06: the registry has no PC type, so OOTA's PCs are filed `npc`, and Thorin has `## NPCs` headings). A `plays` name that resolves to no registry entity is reported in the link report, never guessed. A campaign without `players.yaml` has no declared PCs. A registry NPC whose `scope` is `chapter-N` or `scene` is excluded from publishing with the reason `registry scope <value>: local (deferred to the local-NPC feature)`.
- **Rationale:** `campaignlib/registry.py:69` already has `scope: persistent|chapter-N|scene` (validated at `:270`). Every one of OOTA's 1,012 entities is `persistent` today, so this changes nothing now. Without the rule, the next feature's first local NPC would be published as global by default. Spec FR-012 says "registry lists with type NPC"; reading non-persistent scope as "not global" follows the GM's split (global now, local next). **Confirmed by the GM** (2026-10-06): local scopes stay out until this feature is finished.
- **Alternatives:** Type only, ignoring scope. Rejected because it pre-empts the local-NPC feature's semantics.

## R2 — Name forms, matching and ambiguity

- **Decision:**
  - **Forms for one NPC:**
    - every heading in the NPC's corpus dossier (frontmatter `headings`);
    - the registry entity's `name` and `aliases`, exact strings, when the entity's type is `npc`.
    - Inferred first-token aliases are never used (that is `alias_to_canonical`). `explicit_aliases_by_type` is not used either, because it casefolds and lets the first entity win on a collision.
  - **Matching:** `(?<![\w])` + `re.escape(form)` + `(?![\w])`, case-sensitive. Apostrophes are non-word characters, so `Jimjar's` matches `Jimjar`. Overlapping forms of the *same* entity (`Ilvara`, `Ilvara Mizzrym`) report one mention per position, keeping the longest.
  - **Ambiguity index:** built once per run over **every** registry entity of every type, plus every corpus heading in every category. A form is ambiguous when its exact string belongs to more than one distinct `(type, canonical)`. That covers an NPC and a location sharing a name, two NPCs sharing an alias, and an NPC heading that equals a faction name.
  - The registry's `distinct` and `rejected_aliases` lists are honoured as *anti-merge* only. They never make a form linkable.
- **Rationale:** FR-002/FR-003 need exactness and no silent first-wins. The `explicit_aliases_by_type` docstring (`registry.py:92`) says outright that collisions resolve to the first entity, which is exactly the silent decision FR-003 forbids.
- **Alternatives:** Reusing the 031 grouper table. Rejected because it is casefolded and first-wins.

## R3 — What is scanned and what counts as an item

- **Decision:**
  - **Scanned:** every `### NNN.SS` entry under `## Scenes`, as its full body including the H4 synopsis line, and every item under `## Memorable Moments`.
  - **Moment item** (GM ruling 2026-10-06; the `## Memorable Moments` section is free-form in the 031 format, and OOTA uses three shapes: 896 `>` quote blocks, 309 `**bold**` paragraphs, 20 `- ` list items): a moment starts at a paragraph (a non-blank line after a blank line, or the section's first line) that opens with `>`, `**` or `- `. Every following paragraph that opens with anything else (the italic `*context*` line, an attribution, loose prose) attaches to the moment before it. A paragraph of that kind before the first moment start is its own item. Each `- ` list item starts its own moment. A moment carries `scene: none` (moments are chapter-level in the format). Its line is its first line. The whole item is matched, so a moment links when its quote, attribution or context names the NPC.
  - **Not scanned:** `## Session-End State`, and other entities' `## NPCs` / `## Locations` entries. The spec scopes linking to scenes and moments.
  - **Mention lines:** each linked item records the 1-based file lines where a form matched. The evidence pack marks them (R6) to satisfy FR-004's "identifiable within it".
- **Rationale:** This matches the format confirmed on OOTA ch021 (H3 `021.04 …`, H4 synopsis, moments as quote/attribution/context blocks). Scene identity comes from `parse.Scene.source_scene_id` (031 FR-009).
- **Alternatives:** One moment per blockquote line. Rejected because it splits the quote from its context, which breaks FR-007.

## R4 — The "generic" word list

- **Decision:** Vendor a fixed list at `pipelines/summary_native/data/english_words.txt`: SCOWL size-35 American English, lowercase-only entries (capitalised proper nouns removed), sorted and deduplicated. A form is *generic* when it is a single token (no whitespace) whose casefold is in the list. Each link run records the list's sha256 in `link_manifest.json`.
- **Rationale:** FR-003b requires a pinned list that ships with the tool. `/usr/share/dict/words` (104k entries, which includes proper nouns) is a host dependency and differs by machine, which would break SC-003's byte-identity. No word-list package is in `pyproject.toml` or the venv. Size 35 is the "common words" tier. The larger tiers flag rare words (for example `Ront`) that are almost always names. SCOWL's licence is permissive (MIT-like); a `LICENSE` note sits beside the file.
- **Alternatives:**
  - `wordfreq`, a new dependency that changes with its version;
  - a hand-maintained list (option A, which the GM rejected);
  - flagging all single tokens (option D, rejected).

## R5 — Link rulings in `canon.yaml`

- **Decision:** Add one key to 031's `canon.yaml`: `link_rulings: [{form: <str>, ruling: safe | never}]`.
  - `duplicates.load_rulings` grows to accept it. `RULINGS_MESSAGE` is updated to say the file holds not-a-duplicate pairs and link rulings for generic forms only.
  - Validation happens in the link stage, not at load:
    - A ruling on a form that is **ambiguous** in this run refuses the run (exit 2), naming the form and the entities it collides with (FR-003a).
    - A ruling on a form that is not generic and not ambiguous is reported as `link-ruling-unneeded`, non-blocking.
    - A ruling whose form occurs nowhere in range is reported as `stale-link-ruling`.
  - A ruling can never carry an entity, so it cannot express an alias.
- **Rationale:** FR-003a says "the existing summary-native rulings file". The change is additive: every existing `canon.yaml` stays valid. It changes no state shape, so Constitution XIII does not apply.
- **Alternatives:** A separate `link_rulings.yaml`. Rejected as a second GM rulings file for one pipeline.

## R6 — On-disk layout under `docs/npcs/`

- **Decision:** (full schemas in `data-model.md`; GM rulings 2026-10-06)

  ```
  docs/npcs/
    <slug>.md                          ← PUBLISHED NPC dossiers only (npc-publish); what gm-assistant skills read
    authored/                          ← everything a person creates; no tool overwrites anything here
      <slug>.authored.yaml             ← Manual edits + Secrets (this feature)
      <slug>.md                        ← hand-built dossiers (gm-npc-build output, migrated hand-built files)
    distilled/                         ← migrated distilled dossiers + their sidecars/state (FR-022b)
    summary_native/                    ← generated and tool data only
      ch<since>-<until>/
        link_manifest.json             ← digests: corpus manifest, registry, canon, word list
        link_report.md / .json         ← withheld forms, stale/unneeded rulings, heading-less mentions
        evidence/<stem>.md             ← linked evidence dossier (deterministic)
        draft/<stem>.md                ← draft dossier: model synthesis of evidence + Manual edits; + <stem>.incomplete.md
        draft/<stem>.verify.md         ← verification report for the current draft
        draft/index.json               ← per-NPC draft key of the last successful draft (R8)
        runs/<UTC stamp>/              ← selection.json, record.json, <stem>.system.md/.user.md/.out.md, verify.json
        gm/<stem>.md                   ← draft dossier + Secrets (composed, deterministic)
      publish_log.json                 ← per slug: source (summary_native|hand-built), range, run, sha256 of what was published
  ```

  - **Two names per NPC.** `<stem>` is the 031 corpus dossier stem (`npc_<slug>`, hash suffix on collision), used inside generated range folders. `<slug>` is the lowercase hyphenated canonical name (`jimjar`, `ilvara-mizzrym`), the gm-assistant convention, used for everything in `docs/npcs/` and `authored/`. The mapping is computed from the registry canonical name. A slug collision between two NPCs refuses drafting and publishing for both and names them; it is never resolved silently. Drafting resolves each evidence `<stem>` to its `<slug>` through `npc_slug` (from the registry canonical name) to find `docs/npcs/authored/<slug>.authored.yaml`. Drafting checks collisions up front because two NPCs sharing a slug would also share one authored file.
  - Authored files sit outside the range folders because what the GM writes about an NPC does not depend on which chapters a run covered.
- **Rationale:** The published location is exactly the flat `docs/npcs/<slug>.md` the five gm-assistant skills already read, so they need no change. Generated material stays range-isolated (031 FR-005e). Human-created material can never be lost by clearing a generated folder.
- **Alternatives:** Authored files under `summary_native/` (rejected: generated folder); published files under `summary_native/current/` (rejected: the skills would need changing, and the GM ruled published NPCs belong directly in `docs/npcs/`).

## R7 — Authored files

- **Decision:**
  - **`docs/npcs/authored/<slug>.authored.yaml`:** YAML, strict (`extra` keys refused): `subject: <registry canonical>`, `manual:` (a list of Markdown strings, numbered `[manual N]` by position), `secrets: |` (Markdown). `manual` and `secrets` are optional; absent or empty means none. `manual` is a list so each edit has a number that can be cited and checked (FR-018c).
  - **`docs/npcs/authored/<slug>.md`:** a hand-built dossier in whatever shape its author used (for example `gm-npc-build`'s canonical structure). This feature never parses it beyond reading it whole for publishing (R16).
  - Draft, compose and publish refuse an `.authored.yaml` whose `subject` does not match the slug's NPC. That catches a renamed or copied file.
  - `npc-compose --init NAME` creates an empty `.authored.yaml` and refuses if one exists. It is the only tool write in `authored/`, and it only creates new files.
- **Rationale:** Follows the precedent in `session_doc/blocks.py` (`.authored.yaml`). A Markdown file split on its own `##` headings would break as soon as the GM writes a `##` inside a manual edit.
- **Note:** Tasks must test that `--init` refuses when the file exists, and that no stage writes, renames or deletes anything in `authored/`.

## R8 — Incremental re-draft

- **Decision:**
  - **Draft key** per NPC: `sha256(json.dumps({system_sha, user_sha, backend, model, max_tokens}, sort_keys=True))`. The user prompt contains the evidence pack, the numbered Manual edits and the template. A change to any of them, or to backend, model or budget, changes the key (FR-027). Secrets are not in the prompt, so a Secrets-only edit leaves the key unchanged. `npc-draft` still re-composes the GM dossier for every selected NPC, skipped or not, so a Secrets edit reaches the GM dossier with no model call.
  - `draft/index.json` stores `{stem: {draft_key, run_id}}` for the last **successful** draft only.
  - Re-draft when the key differs or `--force` is given. Otherwise skip, with the reason `unchanged`. An incomplete output never updates the index.
- **Alternatives:** Digesting the evidence only. Rejected because FR-027 also lists Manual edits, prompt, template, backend and model.

## R9 — Draft prompt and output check (drafting is the only model step)

- **Decision:**
  - **Prompt files:** `prompts/npc_dossier.system.md` and `prompts/npc_dossier.outline.yaml`. The outline headings are Identity, Personality and Motivations, History with the Party, Last Observed State, Relationships, Notable Quotes, Arc-Score Candidates.
  - **The user prompt contains:**
    - the computed header, shown as read-only context;
    - the evidence pack verbatim;
    - a `GM MANUAL EDITS` block listing each `manual` item as `[manual N] <text>`, or `(none)`;
    - the rules from FR-016, FR-017 and FR-018: mention ≠ presence; no status inferred from silence; unsupported claims labelled `UNSUPPORTED:`; quotes verbatim from anywhere in the evidence (entry, scene or moment), about the NPC and spoken by anyone, each attributed to its speaker as the evidence gives it, never a placeholder like `Speaker`, and cited to the item it comes from (GM rulings 2026-10-06); arc candidates as quoted triggers only; **a manual edit takes precedence over conflicting evidence, and the contradicted claim is not repeated as fact**; every claim from a manual edit cites `[manual N]`; every manual edit is used at least once; no secrets section.
  - Output is checked with 031's `synth.check_outline`. A missing section produces `draft/<stem>.incomplete.md` and exit 3, as in 031.
  - The written draft dossier is `<!-- provenance comment -->` + computed header (inserted by code, FR-015) + model body. If the model writes its own header, it is stripped and reported.
  - **Secrets are kept out structurally (FR-018a).** Drafting reads the authored file only through `npc_authored.load_manual(path, subject) -> list[str]`, which returns the `manual` list and never exposes `secrets`. A guard test asserts that `npc_draft.py` never reads the authored YAML directly; only `npc_authored.py` opens files under `docs/npcs/authored/`. A fixture test seeds a unique secret string and asserts it appears in no `runs/*/*.user.md`, no `*.system.md` and no draft dossier.
- **Alternatives:**
  - The earlier design: evidence-only render with Manual edits shown as a separate section on top. The GM ruled to synthesise Manual edits into the single model step instead (2026-10-06).
  - Feeding Secrets with a "do not reveal" instruction. Rejected because it relies on the model to keep a secret.

## R10 — Citation grammar and verification

- **Decision:**
  - **Citation forms:** `[ch NNN / NNN.SS]` for a scene, `[ch NNN / entry]` for the NPC's `## NPCs` entry, `[ch NNN / moment]` for a moment. A bullet may carry several, separated by `;`.
  - **Verification checks each citation at two levels:**
    1. **`invalid`:** the chapter or scene id does not exist in the in-range corpus.
    2. **`outside-evidence`:** it exists, but is not in this NPC's evidence pack. Reported, and it fails the "all valid" verdict.
  - **Quotes:** every `> ` blockquote line in Notable Quotes, and every double-quoted span (`"…"` or `“…”`) anywhere in the draft dossier, is checked with `campaignlib.textproc.locate_quote` (exact, then whitespace-tolerant) against the concatenated in-range summary text. No case folding is applied. Curly and straight quote marks and apostrophes (`“ ” " ‘ ’ '`) are compared as equal, as are single versus double quote marks nested inside a quote, and a comma or period moved just inside the closing quote mark; a quote that passes only because of that is listed as `typography-normalised` (advisory, GM ruling 2026-10-06; source fix tracked in kostadis/campaigns#371). Any other changed character fails (spec US3 scenario 2). A quote may come from any item of the NPC's evidence (GM ruling 2026-10-06: not only moments). Attribution lines (`— Speaker [ch NNN / moment]`), whether inside the blockquote, on the next line or on the same line, are split off before matching.
  - History bullets with no citation (chapter or manual) are counted as `uncited` (SC-006). A bullet with nested bullets under it is a label and needs no citation of its own when every nested bullet is cited (GM ruling 2026-10-06). `invalid`, `outside-evidence`, `not-found` and `uncited` all fail the verdict (spec FR-024).
  - **Advisory status check (SC-008, non-blocking):** a fixed list of status words (`alive`, `dead`, `died`, `killed`, `slain`, `missing`, `departed`, `captured`, `freed`) is matched case-insensitively in Last Observed State and History. A hit whose word appears nowhere in the NPC's evidence is reported as `status-claim-unsupported`, an advisory that never changes the verdict. It cannot prove absence of inference, so the GM review stays the real check.
  - **Manual-edit check (FR-018c):** reads `[manual N]` citations. Every N from 1 to len(manual) must appear at least once, and an uncited N is `dropped` (reported with its text). An N outside the range is `invalid`. Both fail the verdict. The report carries a fixed note that the check proves each edit was *used*, not that its meaning survived, and lists each cited passage beside its edit so the GM can compare them quickly.
  - Output is `draft/<stem>.verify.md` plus a per-run `verify.json`. Deterministic, no model, never edits the draft. `npc-verify` re-runs it standalone, which also covers hand-edited drafts.
- **Rationale:** `locate_quote` is the shared, parity-tested matcher (`tests/test_locate_quote_parity.py`). `verify_quotes.classify` scores similarity, but a near verdict is not "verbatim" (see the repo's `near ≠ safe` rule), and it is VTT-shaped.
- **Alternatives:** `citations.verify_citations`. Rejected because it casefolds and folds quote style, which is too lenient for "verbatim".

## R11 — Freshness chain

- **Decision:**
  - **`npc-link`** requires a complete 031 corpus for the range, and refuses when summaries or the registry changed since the build. It reuses `synth._check_fresh`, factored into a shared helper. It writes `link_manifest.json` containing the corpus `manifest.json` sha256 plus the registry, canon and word-list sha256s.
  - **`npc-draft`** refuses when the `link_manifest` corpus sha differs from the current corpus manifest, or when `_check_fresh` fails. Either way it directs the GM to rebuild or re-link (FR-021).
  - **`npc-compose`** needs no freshness check, because it only combines the draft dossier with Secrets. Each GM dossier's provenance comment carries the draft dossier's sha256 and the authored file's sha256.

## R12 — The `docs/npcs/` migration (two steps, git-assisted)

- **Decision:** `server/migrate_npc_dossiers.py --campaign-dir DIR`, modelled on `migrate_wiring.py` and `migrate_session_doc.py`, in two steps (GM ruling, 2026-10-06):
  1. **`--propose`** (writes nothing else). Writes `<campaign>/docs/npcs/migration_classification.yaml`, listing every entry directly in `docs/npcs/` except `distilled/`, `summary_native/` and `authored/`.
     - Each entry has a `disposition` (`distilled` / `authored` / `unknown`) and an `evidence` block. The evidence is: `source_extracts_marker: bool`; `git.added` (sha, date, subject); `git.later_commits` (list); `git.changed_since_added: bool`; and `size`.
     - **Git evidence** comes from `git log --follow --format=… -- <file>` and `git diff --quiet <added-sha> -- <file>`, run read-only in the file's repository. Outside a repository it is `unavailable`.
     - **Proposal rules:**
       - marker present → `distilled`;
       - `.new_notes.*` sidecars, `.dedup_state.json`, `.sidecar_merge_state.json` and `merged_sidecars/` → `distilled` (they belong to the distilled pipeline);
       - everything else → `unknown`.
       - Commit-message wording never sets a disposition. It is shown as evidence only, because commits like "session outputs…, dossier cleanup" bundle generated and hand-made files.
     - A `distilled` file with `changed_since_added: true` gets `flags: [hand-edited]`.
     - The file is sorted and deterministic for a given repository state.
  2. **`--apply`** reads the GM-edited classification file.
     - It refuses while any entry is `unknown`, when an entry no longer matches the disk (a file added, removed or changed since the proposal), or when a target exists in `distilled/` or `authored/` (unless `--force`).
     - It moves `distilled` entries to `distilled/` and `authored` entries to `authored/` with `os.replace`, unchanged. It stops at the first failure and lists what moved.
     - **Config rewrites** are line-level, comment-preserving and exact-value only: `grounding.yaml planning.dossiers.dossier_dir` changes from `docs/npcs/` to `docs/npcs/distilled/`, and `planning.yaml npcs[].dossier` values move to `distilled/` or `authored/`, following each file's disposition. Values pointing elsewhere are reported, not changed.
     - The classification file is kept as a record. Idempotent: on a migrated campaign, `--propose` reports "nothing to classify".
     - **Reports, never edits:** `~/src/campaigns/provenance.yaml` globs over `docs/npcs/*`, and external skills that write or read `docs/npcs/` directly (`gm-npc-build` writes there; `/dossier-merge`, `vtt-spell-pass` and `consistency-check` read the distilled dossiers).
  - **After apply:** `docs/npcs/` holds no loose dossiers, so the skills see nothing until `npc-publish --authored-all` (R16) republishes the hand-built NPCs. The migration's closing message says so.
- **Repointed consumers (FR-022c)**, found by the codebase survey:

  | Consumer | Today | Change |
  |---|---|---|
  | `campaignlib/npc.py:169` `load_alias_map` | flat `glob("*.md")` of the passed dir | add the guard below |
  | `pipelines/grounding/planning.py:912` | default `cwd/npcs` | default from `DossierBuild.dossier_dir` |
  | `server/grounding_config_shared.py:135` | `DossierBuild.dossier_dir = "docs/npcs/"` | `"docs/npcs/distilled/"` |
  | `entity_registry/resolve.py:70` | `DOSSIER_REL = docs/npcs` | `docs/npcs/distilled` + guard |
  | `entity_registry/registry.py:1004,1071` (`check`) | hard-coded `docs/npcs` | `docs/npcs/distilled` + guard |
  | `server/platform_config_service.py:1148` | `docs/npcs` glob | `docs/npcs/distilled` + guard |
  | `frontend/.../PlanningDocument.vue:64` and `ConnectionGraph.vue:341` | `'docs/npcs/'` fallbacks | `'docs/npcs/distilled/'` |
  | `server/routers/connections.py` `/extract` and `/context` (missed by the first survey) | `find_registry(Path(dossier_dir).parent.parent)`, so a deeper dossier dir silently lost the registry | `campaignlib.registry.find_registry_above(dossier_dir)` (walks up, independent of depth) + `load_alias_map`'s guard; a refusal is HTTP 409 |
  | `pipelines/grounding/planning.py` default `extract_dir` | `dossier_dir.parent / planning_extractions` (would land in `docs/npcs/`) | `schema.PLANNING_EXTRACTIONS_DIR = docs/planning_extractions`, the old location, declared once |
  | `PlanningDocument.vue` `dossierExtractDir` watcher | parent of the dossier dir | `<campaign_dir>/docs/planning_extractions` |
  | CLI entry points that load the alias map (`distill`, `party`, `campaign_state`, `scene_extract`, `sd_narrate`, `registry import-frontmatter`) | traceback on a refusal | `Error: <message>`, exit 1 (`campaignlib.load_alias_map_or_exit`) |

  - **The guard:** `campaignlib/npc.py:refuse_unmigrated_dossier_dir(path)`, called by every reader above. It refuses in two cases:
    - **Unmigrated:** `…/docs/npcs/` directly holds any `*.md` whose first line does not start with `campaignlib.npc.PUBLISH_HEADER_PREFIX` (re-exported by `schema.py`), meaning unpublished, unclassified material. The message gives `--propose`/`--apply`. Published files never trigger it, so a campaign with no distilled history (OOTA) keeps working after its first `npc-publish`. A missing `distilled/` with nothing unmigrated means "no distilled dossiers": readers return empty, as `load_alias_map` does today for a missing directory.
    - **Wrong directory:** the path is `…/docs/npcs` itself. That directory now holds published dossiers, and reading them as distilled dossiers would feed generated output back into identity (FR-022d).
  - **Recursive scanners** (`connections /list-docs`, `/context` grep, the rlm MCP `grep_campaign` and `list_files`) are search tools, not identity sources, so FR-022d does not apply to them. They will find GM and published dossiers, including Secrets, which is acceptable for GM-only tools. Noted in the migration document.
- **Rationale:** Constitution XIII and the no-back-compat rule. The proposal is evidence and the GM decides, so the identity call stays with the GM (Principle II). The survey confirmed every in-repo dossier reader globs flat, so `summary_native/` and `authored/` are invisible to them (FR-022d holds by construction, and a test locks it in).
- **Campaigns affected today:**
  - `toee`: 101 files from 8 bundled commits, so expect many `unknown` entries.
  - `stormgiants`: 266 files, all with the marker, so all `distilled`; plus `merged_sidecars/` and `.dedup_state.json`.
  - `Phandalin`, `out-of-the-abyss` and `obelisk`: config references only.
  - The OOTA summaries workspace has no `docs/npcs/`.

## R13 — CLI surface

- **Decision:** Five new subcommands on the existing `summary_native` console script (FR-029). All share 031's `--summaries-dir --since --until --out-root --registry --canon --config`, plus `--npc-root` (default `docs/npcs/summary_native`).

  | Subcommand | Model | Writes |
  |---|---|---|
  | `npc-link` | no | `link_manifest.json`, `link_report.*`, `evidence/` |
  | `npc-draft` | yes (the only model step) | `draft/`, `runs/`, then verification and the GM dossier for each selected NPC |
  | `npc-verify` | no | `draft/*.verify.md` |
  | `npc-compose` | no | `gm/` (draft dossier + Secrets), or `docs/npcs/authored/<slug>.authored.yaml` with `--init` (new files only) |
  | `npc-publish` | no | `docs/npcs/<slug>.md` (the only stage that writes there) and `summary_native/publish_log.json` |

  - `npc-draft` selection flags:
    - `--name …` narrows to named NPCs;
    - `--recent-chapters N` and `--recurring-min N` narrow using 031's `select.py` reasons;
    - `--all` is the explicit "every global NPC" choice.
    - With none of these, it drafts every global NPC with evidence in range at the CLI (FR-012). The UI requires an explicit choice (Constitution X).
  - Backend flags come from `add_backend_args`, plus `--model`, `--max-tokens`, `--dump-only` and `--force`.
  - Exit codes are 031's: 0 ok, 1 blocking validation, 2 refusal, 3 incomplete, 4 model failure. One addition: `npc-verify` returns **5** when any check fails, so scripts can gate on it without confusing it with a refusal.
- **Rationale:** One tool and one vocabulary (Principle XII). Exit codes are already in 031's contract.

## R14 — Web UI page and configuration

- **Decision:**
  - **Router:** `server/routers/npc_dossiers.py` at `/api/npc-dossiers`. It provides:
    - `/run/link`, `/run/draft`, `/run/verify`, `/run/compose`, `/run/publish` (SSE through `stream_subprocess`, argv built by `_build_*_cmd`, model flags from `selection_cli_args` under service name `npc_dossiers`);
    - read-only `/chapters` (reused from summary_native), `/state` (per-NPC rows: evidence counts, draft status, verify verdict including dropped manual edits, authored present) and `/report/{kind}`.
  - **Config:** a new strict `<config>/npc_dossiers.yaml` (`extra="forbid"`), with `GET`/`PUT /api/npc-dossiers/config`. It holds only this service's knobs (`npc_root`, `recent_chapters`, `recurring_min`, `max_tokens`). `summaries_dir`, `out_root`, `registry` and `canon_file` are read from `grounding.yaml summary_native` and **not re-declared** (Principle XII). It is a new file, so nothing needs migrating.
  - **Frontend:**
    - view `frontend/src/views/npcs/NpcDossiers.vue`, route `/npcs/dossiers`;
    - a new top-level sidebar path "NPCs" in `AppSidebar.vue`, separate from Grounding (GM ruling);
    - it reuses `RunPanel`, `PathField` and `useGroundingRun` (a widened `doc` union, or a sibling composable).
  - The page shows files and reports. It never edits authored files, drafts or rulings. Its Publish button invokes `npc-publish` for an explicit selection with the CLI's refusals (GM ruling: publish exists in both places). The review judgment stays outside the UI (Principle IX).
- **Alternatives:**
  - An `npc_dossiers` group in `grounding.yaml`. Rejected because the GM split NPCs from grounding, and CLAUDE.md gives each service its own file.
  - A tab on `SummaryNative.vue`. Rejected by the GM's ruling.

## R16 — Publishing to `docs/npcs/`

- **Decision:** `summary_native npc-publish` is deterministic, makes no model call, and is the only writer of `docs/npcs/<slug>.md` (FR-031).
  - **Selection** must be explicit: `--name NAME…`, `--all` (every NPC with a GM dossier in range), or `--authored-all` (every hand-built `authored/<slug>.md`). With none of these it refuses (Constitution X).
  - **Summary-native source:** it takes `gm/<stem>.md` for the range, rewrites each `[manual N]` to `[GM]` (regex `\[manual \d+\]`), keeps chapter citations, and prepends the header `<!-- published by summary_native npc-publish | source: summary_native | npc: … | range: … | draft run: … | draft sha256: … | authored sha256: … | verify: pass|fail(forced) | published sha256: … -->`.
  - **Hand-built source (FR-031c):** for a named NPC with `authored/<slug>.md` and no GM dossier in range, it copies the file verbatim below `<!-- published by summary_native npc-publish | source: hand-built | path: docs/npcs/authored/<slug>.md | sha256: … | verification: not applicable -->`. If both sources exist it refuses, naming both paths, until `--source summary_native|hand-built` is given.
  - **Refusals without `--force` (FR-031a):**
    - verification failed;
    - the target `docs/npcs/<slug>.md` exists with no `published by summary_native` header (a foreign file);
    - the target's current sha256 differs from the `published sha256` in `publish_log.json` (hand-edited since publishing; the message says to move the correction into `authored/`);
    - a slug collision.
  - `publish_log.json` records, per slug, the source, range, run, published sha256 and time. The publish header carries the same facts, so the log can be rebuilt from `docs/npcs/`.
  - Publishing never deletes. An NPC that drops out of a later selection keeps its published file until the GM removes it.
- **Rationale:** Publishing is the human checkpoint before model-driven consumers (the gm-assistant skills) read a dossier (FR-023). Hand-built NPCs flow through the same gate, so the skills read one place.
- **Alternatives:** Symlinks from `docs/npcs/` into `gm/`. Rejected: an unreviewed re-draft would silently change what the skills read.

## R17 — Chunked drafting and the default backend (GM rulings 2026-10-06)

- **Decision:**
  - `npc-draft --mode chunked|one-shot`, default from `npc_dossiers.yaml draft.mode` = `chunked`.
  - **Chunking (code):** whole `## Chapter` sections of the evidence dossier, in order, packed until adding the next would exceed `draft.chunk_chars` (default 60000). A chapter larger than the limit is its own chunk. Never split a chapter.
  - **Map call per chunk:** prompt = NPC name + the chunk's evidence verbatim + the GM MANUAL EDITS block + the R9 rules, asking only for `## History with the Party`, `## Notable Quotes`, `## Arc-Score Candidates`. Prompt files `prompts/npc_dossier.map.system.md` and `prompts/npc_dossier.reduce.system.md`, sharing the R9 rules.
  - **Map check (code, the checkpoint between model calls):** the R10 citation and quote checks, scoped to the chunk: drop a History bullet or Arc candidate with no citation or a citation outside the chunk; drop a quote not verbatim anywhere in the chunk's evidence (typography-normalised passes); **also drop a History bullet or Arc candidate containing any `"…"`/`“…”` span that is not verbatim in the chunk's evidence** (GM ruling 2026-10-06; the first pipeline run showed the Spark wrapping paraphrases in quote marks, especially arc triggers). Every drop is logged with its text and reason in `runs/<stamp>/<stem>.drops.md`.
  - **Stitch (code):** survivors joined in chapter order; exact-duplicate lines removed.
  - **Reduce call:** NPC name + computed header facts + the stitched verified notes + the last chunk's raw evidence + the manual edits, asking only for Identity, Personality and Motivations, Last Observed State, Relationships.
  - **Assembly (code):** outline order; the draft dossier then goes through the normal outline check, verification and compose.
  - **Manual edits:** every map call and the reduce call see the full numbered list. The manual-edit check (FR-018c) runs on the assembled dossier.
  - **Draft key** adds `mode` and `chunk_chars` and every prompt sha.
  - **Default backend:** `npc_dossiers.yaml draft.backend: dgx`, `draft.model: qwen3.8-flash-next`; the endpoint is not configured here — it resolves through campaignlib's existing chain (`--endpoint`, `DGX_ENDPOINT`, wiring `dgx_endpoint`). Flags override config.
- **Rationale:** measured on Jimjar, Ilvara Mizzrym and Eldeth Feldrun (prototype in the session scratchpad): chunked Spark gave 253 / 100 / 121 citations against one-shot Spark's 42 / 65 / 50, all valid, with every quote verbatim after the map check. (The prototype filtered quotes to moments only and dropped 27 scene-dialogue quotes in one Jimjar chunk; the GM later ruled scene quotes acceptable, so the pipeline keeps them.)
- **Alternatives:** one-shot only (weaker on Spark); chunked only (Sonnet and Opus untested chunked); a model merging per-chunk History (rejected: an LLM structuring another LLM's output, the global rule's bad pattern).

## R15 — Scale

- OOTA has 378 registry NPCs and 222 NPC corpus dossiers. The global NPCs with evidence in range are at most 222.
- The largest evidence pack is 81 entries plus linked whole scenes. 94 scenes at roughly 25 lines each is under 60k tokens, which fits one call without chunking (spec assumption).
- The first run with no narrowing makes about 200 calls. `--dump-only` and `--recurring-min` exist to keep that deliberate. After that, re-drafts are incremental.
- Linking is pure text scanning: 67 files × about 2,700 forms, using one combined regex per run (alternation sorted longest-first). Target: under 30 s.
