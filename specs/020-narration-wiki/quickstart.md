# Quickstart and Acceptance Guide: Persistent Narration Wiki

This guide validates the planned CLI, shared HTTP process boundary, browser workflow, safety refusals, and success criteria. Run it after implementation from the feature worktree.

## 1. Install and build

```bash
python -m pip install -e .
python -m pytest tests/
cd frontend
npm install
npx playwright install chromium
npm run build
cd ..
```

The implementation pins `@playwright/test` in `frontend/package.json` and adds:

```json
{
  "scripts": {
    "test:e2e": "playwright test"
  }
}
```

## 2. Use an isolated fixture

Never run acceptance mutations against a live campaign. Copy the committed narration-wiki fixture to a temporary directory and use explicit variables:

```bash
NARRATION_WIKI_TMP="$(mktemp -d)"
cp -R tests/fixtures/narration_wiki/campaign "$NARRATION_WIKI_TMP/campaign"
CAMPAIGN_PATH="$NARRATION_WIKI_TMP/campaign"
SESSION_PATH="$CAMPAIGN_PATH/sessions/session-01"
ITERATION_ID="acceptance-001"
```

The fixture must contain:

- at least two narrator-attributed narration documents;
- critiques and source records spanning the supported historical layouts;
- campaign-local rulebook, voice, example, and checker configuration;
- at least one expected-but-missing optional role;
- one companion pattern draft and one seed-conflict draft;
- one proposal draft that changes exactly one authorized target;
- a portable deployment fixture with a valid capability manifest.

Capture exact hashes of all source artifacts, all configured guidance targets, and the portable deployment before the run.

## 3. Refuse ambiguous or unsafe scope

Each command below must fail nonzero before process work or artifact creation:

```bash
narration_wiki status +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "" +  --iteration-id "$ITERATION_ID" +  --json

narration_wiki collect +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$CAMPAIGN_PATH" +  --iteration-id "$ITERATION_ID" +  --json

narration_wiki collect +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$CAMPAIGN_PATH/../outside-session" +  --iteration-id "$ITERATION_ID" +  --json
```

Add fixture cases for an escaping intermediate symlink and an escaping final symlink. Both must fail without creating `narration_wiki/`, `wiki/`, or a server run log.

## 4. Verify read-only startup and dependency status

Before collection:

```bash
narration_wiki status +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --json

narration_wiki index-check +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --json
```

Expected:

- status is bounded JSON and reports a new or absent iteration;
- the campaign and session remain byte-for-byte unchanged;
- no missing directory is created;
- the companion manifest is read from `~/.claude/narration-wiki/capabilities.yaml`;
- source repository, revision, contract version, campaign-resolved guidance mode, maintainer, and proposer are reported.

Repeat with missing, malformed, incompatible-contract, and missing-capability manifests. Each case must report explicit dependency status and must not write the portable directory or borrow copied guidance.

## 5. Collect one immutable corpus

```bash
narration_wiki collect +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --json
```

Validate `trace-manifest.json` against `contracts/manifest.schema.json` and confirm:

- only the selected session's allowlisted files appear;
- all paths are relative and sorted;
- present files have exact SHA-256 and byte lengths;
- missing roles are explicit;
- the measurement corpus and corpus ID are stable.

Save the manifest bytes. Repeating collection with the same iteration must fail as a conflict and leave those bytes unchanged. Running an equivalent collection in a new isolated copy with the same iteration ID and inputs must produce byte-identical manifest output.

## 6. Persist the baseline before Gate 1

```bash
narration_wiki measure +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --phase before +  --json
```

Validate `measurement-before.json` against `contracts/measurement.schema.json`. Confirm that it:

- references the manifest corpus ID;
- binds the current campaign-guidance digest and `d4-v1` profile;
- contains every named D4 category;
- records skipped checks with reasons;
- lists cross-narrator repeated sequences of three or more words;
- contains no inferred Gate decision.

Before any Gate 1 ruling, modify a fixture corpus byte and verify that remeasurement is allowed and creates a new baseline binding. Restore the fixture, start a fresh iteration for later tests, and remeasure.

Attempt `pattern-rule` without a baseline. It must fail. After any conflict or pattern ruling, change corpus or guidance bytes and verify that remeasurement and further Gate 1 rulings refuse with a requirement to start a new iteration.

## 7. Rule seed conflicts before affected patterns

Place the companion-produced conflict draft at:

```text
<session>/narration_wiki/<iteration-id>/conflict-drafts/seed-voice.json
```

It must contain two source statements with distinct references and digests and identify the affected rule and pattern slug.

First attempt to accept the affected pattern:

```bash
narration_wiki pattern-rule +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --pattern-slug distinct-narrator-bookkeeping +  --decision accept +  --tier campaign +  --json
```

Expected: refusal naming `seed-voice`, with no page or index mutation.

Now record the GM decision:

```bash
narration_wiki conflict-rule +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --conflict-id seed-voice +  --resolution "Use the selected campaign's narrator-specific bookkeeping convention." +  --rationale "The campaign rulebook is authoritative for campaign-local narration." +  --json
```

Validate the durable file under `<campaign>/wiki/conflicts/` against `contracts/conflict-ruling.schema.json`. Confirm its sources exactly match the draft and its baseline hash, corpus ID, guidance digest, and profile match the persisted baseline.

## 8. Complete Gate 1

Accept the affected campaign-tier draft by repeating `pattern-rule`. Confirm one confirmed page, one index entry, one log entry, and one ruling are written atomically.

Also test:

- rejecting another draft records only its ruling;
- duplicate slug or broken index link refuses unchanged;
- named campaign content proposed for portable placement defaults to campaign;
- portable placement without explicit override and rationale refuses;
- valid portable approval creates only a promotion handoff and `pending_portable_sync`;
- no command writes `~/.claude/narration-wiki/`.

Run:

```bash
narration_wiki index-check +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --json
```

Expected: campaign pages and index agree, every confirmed page has the required four sections, and portable compatibility is explicit.

## 9. Stage one atomic proposal

Have the companion proposer write its draft inside the iteration. Exclude companion-model response time from active operator timing, but record it separately.

```bash
narration_wiki proposal-stage +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --proposal-id proposal-001 +  --draft "$SESSION_PATH/narration_wiki/$ITERATION_ID/proposals/incoming/proposal-001.yaml" +  --json
```

Confirm:

- exactly one configured campaign target is named;
- no symlink component is accepted;
- the target is unchanged;
- before and after snapshots, hashes, proposal fingerprint, and complete diff agree;
- only confirmed compatible patterns are inputs.

Try drafts that target two files, a non-allowlisted file, another campaign, or a stale before hash. Each must fail without partial state.

## 10. Apply for comparison, measure, and reject

```bash
narration_wiki proposal-apply +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --proposal-id proposal-001 +  --json

narration_wiki measure +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --phase after +  --proposal-id proposal-001 +  --json

narration_wiki proposal-rule +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --iteration-id "$ITERATION_ID" +  --proposal-id proposal-001 +  --decision reject +  --json
```

Expected:

- comparison applies only when the live target matches the before hash;
- after measurement uses the same corpus ID and the comparison target hash;
- rejection restores exact before-snapshot bytes;
- one Rejected impact entry contains the complete diff and both measurement references;
- repeating the same completed ruling is idempotent;
- a conflicting repeated ruling refuses.

Repeat in an isolated iteration with `--decision accept` and confirm that exact comparison bytes are retained and one Accepted impact entry is appended.

## 11. Enforce rejected-proposal reconsideration

Attempt to stage an equivalent form of the rejected proposal. It must be blocked before any new bundle is created.

Then verify these cases:

1. a new path containing a previously seen digest does not qualify;
2. a genuinely new manifest digest bound to an unrelated rule does not qualify;
3. a genuinely new manifest digest bound to the proposal's affected rule qualifies;
4. a binding not present in the current manifest fails;
5. a non-empty GM override rationale qualifies without evidence bindings;
6. evidence bindings and override rationale together fail;
7. Gate 2 cannot add or replace the staged reconsideration basis.

An example qualifying staging option is:

```bash
--evidence-binding-json '{"source_ref":"narration/new-scene.md","source_sha256":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","applies_to_kind":"rule","applies_to_key":"bookkeeping-per-narrator"}'
```

## 12. Exercise crash recovery

Inject failures after each journaled mutation boundary for:

- conflict ruling;
- campaign Gate 1 publication;
- portable promotion handoff;
- Gate 2 acceptance;
- Gate 2 rejection and restoration.

After restart, `status` must report the transaction and next safe action. Recovery must be idempotent and hash checked. If live bytes match neither expected state, it must enter `needs_attention` and must not guess.

## 13. Verify HTTP and cancellation parity

Start the existing server against the isolated fixture:

```bash
python server/main.py +  --campaign-dir "$CAMPAIGN_PATH" +  --session-dir "$SESSION_PATH" +  --host 127.0.0.1 +  --port 5000
```

Contract tests must show:

- status uses the bounded central JSON helper;
- every workflow action, including index check, uses the shared SSE runner;
- the router contains no direct process-launch call;
- narration-wiki passes `save_run_log=False`;
- CLI and HTTP executions create identical feature artifacts;
- disconnect and AbortController cancellation terminate the child process group;
- success, nonzero exit, refusal, and cancellation all trigger a fresh status read;
- SSE command, output, and done event grammar remains compatible with existing clients.

## 14. Verify the UI at 1280x720

Run:

```bash
cd frontend
npm run test:e2e
cd ..
```

Playwright must use exactly `1280x720`. Verify workflow step 7 and sidebar `③ Narration Wiki`, the full CLI-equivalent flow, and reuse of existing application colors, controls, cards, typography, badges, and focus styles.

For each resizable region—manifest/evidence, measurement, diff/prior rulings, and history/output:

1. set its border-box dimensions to exactly `320x160`;
2. inject or load content overflowing both axes;
3. assert `scrollWidth > clientWidth` and `scrollHeight > clientHeight`;
4. scroll to the maximum horizontal and vertical positions;
5. assert both positions changed;
6. keyboard-focus the applicable Gate controls and confirm they remain reachable.

The page itself must scroll when its content exceeds the app shell. Diff whitespace and table intrinsic widths must not be collapsed merely to hide horizontal overflow.

## 15. Persist the timed operator result

Run one complete UI exercise from explicit session selection through a persisted Gate 2 ruling.

Record:

- exact start and end instants;
- total elapsed wall time;
- separately observed companion-model response seconds;
- active operator seconds calculated as total minus the excluded model seconds;
- exact viewport and minimum panel dimensions;
- Gate 1 and Gate 2 artifact path/hash references;
- durable impact or ruling path.

Write `specs/020-narration-wiki/validation/usability-result.json` and validate it against `contracts/usability-result.schema.json`. `passed` may be true only when active operator time is less than 900 seconds and both human checkpoints and the durable ruling are proven.

## 16. Final immutability audit

Compare the saved hashes:

- raw critiques, narration, source records, and scrub manifests are unchanged;
- all non-target campaign guidance is unchanged;
- a rejected target is byte-identical to its before snapshot;
- portable deployment files are unchanged;
- no read-only command created an artifact or run log;
- no narration renderer code imported or read wiki state.

The only expected writes are the documented iteration artifacts, confirmed campaign wiki state, transaction journals, impact entries, and post-implementation usability result.

The executable CLI reference is [`docs/cli/narration-wiki.md`](../../docs/cli/narration-wiki.md), and the browser path exercised above is `/workflow/wiki`. The general constitution update for established colors and resize scrollbars remains deferred to issue #360; this acceptance run verifies the feature contract only.
