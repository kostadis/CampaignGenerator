# Research: GM Rulings and Authority Tiers

## R1 — Authority lives in source, with one audit ledger

**Decision**: Store the strict, versioned campaign authority ledger at `docs/authority.yaml`. `RULED` records are reviewed instructions and audit history. Historical truth changes only when their exact patch is applied to the maintained authoritative summary. Supporting proposals, snapshots, journals, receipts, and immutable before/after events for every ledger mutation live under `docs/authority/`; they are evidence for the ledger, not a second editable authority.

**Rationale**: This implements the user's choice that summaries remain authoritative, gives decisions stable identities, and keeps current truth distinct from the history explaining it. It also leaves the existing narrow stores intact.

**Alternatives considered**:

- Interpret the ledger as an overlay above summaries: rejected because it creates the shadow authority the user declined.
- Reuse `docs/summary_native/canon.yaml`: rejected because it is strictly limited to not-a-duplicate and link decisions and deliberately does not change corpus content.
- Reuse `docs/corrections.yaml`: rejected because its stale claim is provenance context, not an executable replacement matcher.
- Use `transcript_corrections.yaml`: rejected because it repairs transcript evidence and must not become campaign-fact authority.
- Add a database: rejected because files already provide discoverable, auditable state and a database would add a recurring operational boundary.

## R2 — Apply is digest-bound and recoverable

**Decision**: A proposal binds the campaign, ledger revision and digest, exact authoritative source, stable claim anchor, whole-file before digest, proposed after digest, reviewed before/after bytes, scope, projections, reviewer, and proposal digest. Apply acquires a campaign authority writer lock, revalidates every binding and resulting document, writes original/proposed snapshots plus a durable journal, uses `campaignlib.util.atomic_write_bytes` for each file, verifies final digests, then commits the receipt and ledger transition. Any unfinished journal makes dependent commands refuse until `recover` resolves it.

**Rationale**: Existing atomic writes protect one file; they do not make a sequence of source, ledger, and receipt writes filesystem-atomic. A journal makes that sequence fail closed and recoverable without claiming a guarantee the filesystem does not provide. The narration-wiki storage flow demonstrates the usable lock/journal/recovery pattern.

**Alternatives considered**:

- Call the multi-file operation atomic: rejected because separate replacements can be interrupted.
- Write the source and reconstruct history afterward: rejected because a crash could leave an untraceable source edit.
- Restore all backups during recovery: rejected because it can overwrite legitimate edits. Recovery classifies each target digest as before, after, or unexpected and refuses unexpected bytes.
- Let `--force` bypass a stale digest: rejected because `--force` means overwrite existing output, not bypass human approval or concurrency checks.

## R3 — Exact replacement is the first source adapter

**Decision**: V1 implements exact Markdown summary replacement only. The before span must match once at the reviewed whole-file digest, must not fall inside a declared verbatim span, and the after text must validate as a readable maintained summary. Preserve original bytes in proposal history. This fulfills the spec's correction-or-annotation choice with the safer correction path; source annotation syntax is deferred rather than ambiguous.

**Rationale**: Exact replacement has the fewest extraction ambiguities and directly implements source authority. Source-specific adapters also prevent a general patch engine from rewriting VTT evidence, registries, thread identity, generated drafts, or arbitrary external notes.

**Alternatives considered**:

- Generic patches against any selected file: rejected because selection grants read scope, not write authority.
- Append a “GM says otherwise” note while leaving the old claim eligible: rejected because that recreates an overlay and gives extraction two contradictory assertions.
- Rewrite raw VTT or claimed-verbatim passages: rejected by the precision and exactness rules.

## R4 — Planning selectors are explicit snapshots

**Decision**: Extend `config/planning.yaml` with typed exact-file and scoped-glob selectors. Resolve them against the campaign root unless explicitly absolute, resolve symlinks for deduplication, sort deterministically, disclose external paths, and record each selection reason. Preview materializes the exact members and a selection digest. Missing/unreadable or zero-match configured selectors refuse. A run uses the reviewed snapshot and refuses if glob membership changed.

**Rationale**: This uses the existing planning configuration owner and obeys explicit selection. A new file appearing under a glob after review must not silently expand a token-spending run.

**Alternatives considered**:

- Empty means all notes: rejected by the explicit-selection principle.
- Re-resolve globs silently at run time: rejected because it changes reviewed scope.
- Ban external files: rejected because the specification permits explicit readable external notes; they are disclosed and remain read-only.

## R5 — Classification and audience are record-level policy

**Decision**: Every usable note or summary-source record names one stable whole-file or stable section anchor, its exact content digest, one classification, its effective interval, and explicit audience grants. Supported grants are `gm`, `players`, `characters`, and `character:<stable-id>`. Player grants never imply character grants. Existing summaries are GM-only unless every section selected for a non-GM run has a digest-bound ledger record granting that target. Mixed files must be divided into independently anchored records; filenames and model inference never classify or split them.

**Rationale**: Authority, future/planning status, and visibility are separate dimensions. Record-level metadata is the smallest reliable boundary that can be validated before rendering.

**Alternatives considered**:

- One audience for a mixed file: rejected because adjacent GM-only material can leak.
- Infer audience from prose or filename: rejected because it delegates a precision decision.
- Treat all selected notes as GM-only and redact final output: rejected because final redaction is too late and does not support character-specific inputs safely.

## R6 — Filter before extraction, caching, and rendering

**Decision**: Build an audience-filtered evidence collection before prompt jobs, extraction, sibling-cache lookup, deterministic references, fallbacks, previews, exports, or diagnostics. Cache identity includes the filtered payload digest, target audience, authority schema/policy revision, and relevant record revisions. A cached item is reusable only when all these match. Non-GM diagnostics omit forbidden text, identities, paths, and source pointers.

**Rationale**: Filtering only the final Markdown leaves restricted facts in model prompts, cached extracts, reports, and error messages. The current notes cache key covers prompt/model/chunk inputs, and the sibling range cache reuses by content key; both need the policy boundary in their admission key.

**Alternatives considered**:

- Generate a full GM result and redact afterward: rejected because restricted content has already crossed the model and cache boundary.
- Keep policy outside cache identity: rejected because a previously broad cached extraction could be reused for a narrower audience.
- Add a separate cache store: rejected because policy-aware keys and manifests extend the existing extraction lifecycle without a parallel checkpoint system.

## R7 — Existing inputs remain safe by projection contract

**Decision**: Existing grounding drafts and unclassified summaries remain GM-only. This feature adds no new player publishing product. A non-GM input is assembled only from complete anchored source sections whose current content digests match ledger records granting the target; unclassified sections are excluded, and a required incompletely covered source refuses. When a correction changes an anchored section, the transaction updates its ledger content digest and preserves its grants unless changed grants are explicitly reviewed. The ledger governs visibility only; it never overrides claim truth.

**Rationale**: A GM-only correction applied to a summary can leak through ordinary extraction unless source granularity and audience policy travel together. Declaring old text public by default would weaken the boundary.

**Alternatives considered**:

- Treat every historical summary as player-visible: rejected because the repository has GM planning material and no evidence for that grant.
- Add inline audience syntax to summaries: rejected for V1 because digest-bound anchored ledger grants filter source bytes before extraction without another summary grammar. The ledger controls visibility, not truth.

## R8 — Precedence is partial and scoped

**Decision**: `CANON` and `TABLE` are established evidence with no intrinsic winner. An explicit reviewed supersession of the same structured claim and overlapping interval wins; otherwise incompatible values require a GM ruling. For future planning, a scoped `OVERLAY` directs the current plan ahead of conflicting `PREP`; incompatible equal-scope overlays block. `OPEN` never settles a fact. Disjoint effective intervals represent evolution, not contradiction.

**Rationale**: One total order would conflate historical truth, table observation, planning intent, uncertainty, and audience. Scope and time are required to distinguish a changed world from conflicting claims.

**Alternatives considered**:

- Latest file or record wins: rejected because recency alone is not authority.
- `TABLE` always wins over `CANON`: rejected because either can contain the maintained or stale statement.
- Treat every later state as a contradiction: rejected because campaigns legitimately change over time.

## R9 — Conflict detection is deterministic only for structured claims

**Decision**: Automatic conflicts require comparable human-authored claim keys: stable subject/thread ID, property or decision key, normalized value, overlapping effective interval, and projection scope. Exact overlapping source anchors also conflict deterministically. A human may explicitly record a prose contradiction. Prose similarity may only produce an unresolved candidate; this feature adds no model verdict.

**Rationale**: Code can compare structured values and scopes but cannot reliably decide entailment or narrative contradiction. Broader cross-document review belongs to issue group C.

**Alternatives considered**:

- Model decides contradiction: rejected because the model proposes candidates and the GM decides, and it would broaden this feature.
- Ignore prose conflicts entirely: rejected because a human-identified contradiction needs a durable review record.

## R10 — Run records and freshness use one authority manifest

**Decision**: One shared authority-input manifest contains selected record IDs/revisions, metadata digests, selected paths and section digests, external flags, selection reasons, selector expressions and materialized membership digest, relevant applied decisions/proposals/receipts, target audience, horizon, source digests, and policy/schema version. Extraction, synthesis records, and freshness comparison use the same builder. An unfinished transaction or mismatch makes affected artifacts stale/refused.

**Rationale**: Current synthesis already records inputs and notes-manifest digests. Extending one canonical manifest prevents freshness and run provenance from disagreeing.

**Alternatives considered**:

- Hash only note text: rejected because classification, audience, status, selection membership, and supersession change meaning without changing prose.
- Let source-byte freshness cover rulings: rejected because proposal/status/audience changes can matter independently.

## R11 — Withdrawal is a new reviewed source change

**Decision**: Withdrawal records a request and generates a reversal proposal against the current source digest. It automatically proposes the inverse only when the exact applied passage is still identifiable and unrelated edits are preserved. Otherwise it refuses automatic inversion and requires an authored replacement proposal. The prior ruling and applied receipt remain immutable history.

**Rationale**: Blindly restoring a before snapshot can destroy later legitimate world-state evolution or editorial fixes.

**Alternatives considered**:

- Deleting a ledger row reverts behavior: rejected because the source, correctly, remains authoritative.
- Always restore original bytes: rejected because later edits may be legitimate.

## R12 — CLI engine and UI face ship together

**Decision**: Add an `authority` command family under `summary_native`: `list`, `show`, `validate`, `notes preview`, `propose`, `apply`, `withdraw`, `conflicts`, `history`, and `recover`, with `--json` where machine-readable output is needed. Approval and apply may be one explicit action only when it binds the exact proposal displayed. FastAPI routes invoke these commands through the existing subprocess runner. `SummaryNative.vue` exposes the same inputs, previews, status, operations, and artifacts.

**Rationale**: The CLI owns behavior and the UI mechanizes it. This yields parity without moving judgment into the browser or building issue #547's general review queue.

**Alternatives considered**:

- Service methods implement authority logic directly: rejected because it creates split behavior.
- Defer UI: rejected by bidirectional parity.
- Build a new review application: rejected as out of scope and duplicative.

## R13 — The new shape is additive; retired shapes still require migration

**Decision**: No existing narrow correction store is converted, and existing planning files without the note-selection feature remain valid summary-only configurations. Initialize the new ledger deliberately. There is no identified old authority-ledger schema, so V1 invents no migration command. Authority-aware runs refuse legacy checked-note caches and run records that lack the new policy/manifest version and instruct regeneration; outputs are never upgraded in place. `migration.md` documents affected workspaces and verification. A future retired authored schema must ship its own defined one-shot migrator and refusal before retirement.

**Rationale**: There is no valid legacy general-authority model to mass-convert. Inventing migration data would create false human decisions, while omitting the required retirement behavior would permit schema drift later.

**Alternatives considered**:

- Convert all three existing stores: rejected because their semantics are distinct and still active.
- Lazy write-on-read upgrade or fallback reads: rejected because it creates hidden mutation or two sources of truth.

## R14 — Recovery and policy checks spend no model tokens

**Decision**: Ledger validation, selection resolution, audience filtering, source proposal/apply/recovery, structured conflicts, and freshness are deterministic. Tests use fake model clients to inspect full prompt payloads. No new model call is introduced.

**Rationale**: These are structure and authority decisions owned by code and the GM. A model adds cost and cannot grant approval or visibility.

**Alternatives considered**:

- Use a model to classify notes or audiences: rejected as an unauthorized precision decision.
- Use a model to reconcile source conflicts automatically: rejected because it crosses the human checkpoint.
