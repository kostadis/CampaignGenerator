# Campaign cycle acceptance record

Status: implementation integrated locally; **production rollout is not yet accepted**.
The first local session release and refreshed prep require the pilot's remaining
human reviews. No campaign or skill primary checkout was modified by this work.
No campaign artifact has been published externally.

## Exact acceptance revisions

| Repository | Verified commit |
|---|---|
| CampaignGenerator | `36041d9b0bb81fca01bf5fe8bfc2c3270ed7e543` |
| mytools | `8801387bb00edecc6b3d08ae8d18df01cd132dc3` |
| Phandalin | `466603a7937b5a3a70bc104a1e12e29547b5d270` |
| obelisk | `6992c0a0d59cd6377510a556e3636d37aa6f453d` |

CampaignGenerator's implementation commit is followed only by acceptance documentation.
The pilot commits are local, on `feat/cycle-pilot`, in the requested isolated
campaign worktrees. Skill adapters are on `feat/cycle-skills`; live skill links
were not changed. Component branches/worktrees and the integration worktree are
retained for review.

## Verification

- Records milestone: 198 checks passed.
- Review milestone: 214 checks passed and frontend build passed.
- Orchestration milestone: 275 checks passed and frontend build passed.
- Memory milestone: 253 checks passed and frontend build passed.
- Assembled regression pass: **4,729 passed, 199 skipped, 29 known baseline failures deselected**.
- Final affected checks after settings/import/partial-scene fixes: 358 passed.
- Chromium: real CLI-backed draft read, approval, browser reload, CLI handoff and stale-source display passed.
- FastAPI: real subprocess init/status and campaign-path refusal passed.
- Vue type check and production build passed. `git diff --check` passed.
- All 20 Claude/Codex adapter entrypoints validated; shared contract links resolve.
- Tests asserted `campaignlib` resolves inside each tested worktree.

The unfiltered suite is not green. Its 29 remaining baseline failures were
reproduced against unchanged implementations in the records checkout using the
same dependencies. They concern existing selection/effort schema assertions,
backend mocks, cached DGX setup, an ensemble default literal and this machine's
unrelated `/tmp/.git`. See [baseline-failures.json](baseline-failures.json).
One old assertion forbidding `sd_plan --party-config` was deliberately updated
for this feature and passes in the final affected checks. No guardrail was
silently disabled; the regression run's explicit exclusions are recorded here.

Fresh test environment: `uv venv .venv --python python3`; install editably with
`uv pip install --python .venv/bin/python -e '.[test]'`, and install the existing
DGX library with `uv pip install --python .venv/bin/python ~/src/dgx` for its
backend tests. The supported MCP v1 seam is bounded in pyproject.toml. Run
`npm ci` and `npm run build` inside that checkout's frontend. Browser validation
used the pinned Playwright Chromium revision in `/tmp/cycle-browsers`.

## Pilot handoffs

| Campaign | Source session | Capture review | Remaining prerequisite |
|---|---|---|---|
| Phandalin | 20260825 | `Phandalin/cycle-pilot/capture-review.md` | Human capture approval; then identity and subsequent production gates |
| obelisk | 010-20260821 | `obelisk/cycle-pilot/capture-review.md` | Human capture approval; shared/sidekick attribution; genre rulebook before render |

Both pilots ran explicit migration inventory and import, preserving raw VTT and
historical review evidence. Dry runs made no changes. Import inferred no
approvals. Duplicate cue and invalid narrator checks were exercised; unknown
speakers remain unresolved. The zero-finding capture audit did not approve its
draft, and attempting the identity stage was refused. Editor/CLI inspection
can resume from each pilot's YAML and review-export.json.

No semantic recap/mechanics editing or backend comparison was run on campaign
content yet: crossing that gate would require inventing the human's signature.
Preservation behavior and fixed CLI interfaces have deterministic test coverage;
production quality and token/time savings remain unmeasured until those reviews.

Measurements per pilot: one pending human handoff, zero model calls, zero
rendered scenes, zero review-page regenerations, and zero repeated questions.
Model token usage is not applicable. `acceptance.json` records inputs, exact
hashes, revisions and timestamps. Git working-tree and diff hashes of both live
campaigns matched before and after the pilots.

## Operator resumption

Use the integration checkout's `.venv/bin/session_workflow status` or `resume`
with the isolated campaign root and `--session-dir cycle-pilot`. Read the capture
review and preserved source before supplying a named human approval with the
current binding. The engine then exposes the next required native task.

For editor use, run the integration server with the isolated campaign root and
`--session-dir <isolated-campaign>/cycle-pilot`, using port **8131** for Phandalin
or **8132** for obelisk. Open `/workflow/cycle?session=cycle-pilot`. These are
reserved operator examples; no persistent pilot server was left running.

The scope/binding rules and exact commands are in
[the operator guide](../../docs/cli/session_workflow.md) and
[the migration guide](migration.md). Keep narration-wiki guidance changes at
its existing separate gates.

## Backlog disposition

The user-approved 59-issue allocation governs follow-up; this integration does
not assert closure of all allocated issues. Records/review/gating/persistence,
identity handoffs, selected memory and existing batch/resolver integration are
implemented. Native specialist judgments and ensemble/dossier/thread/projection
work remain existing tools receiving explicit tasks. No new duplicate retrieval
client, model client or arbitrary skill runner was introduced. Export-ID
extensions, catalog migration and enhancement redesign remain deferred as
planned; sibling registry/retrieval work remains separately owned. The five
TODO workstreams map to the persistent stage/review workspace, shared gates,
persisted configuration references, selected incremental memory and existing
batch execution rather than a new parallel pipeline.


## Published draft PRs

The user explicitly authorized code publication. These draft PRs preserve the component stack; no default branch was merged. Campaign pilot artifacts remain local, and publication permission does not approve pilot drafts.

| Component | Draft PR | Base | Head |
| --- | --- | --- | --- |
| Records | [CampaignGenerator#378](https://github.com/kostadis/CampaignGenerator/pull/378) | `main` | `feat/cycle-records` |
| Review | [CampaignGenerator#379](https://github.com/kostadis/CampaignGenerator/pull/379) | `feat/cycle-records` | `feat/cycle-review` |
| Orchestration | [CampaignGenerator#380](https://github.com/kostadis/CampaignGenerator/pull/380) | `feat/cycle-review` | `feat/cycle-orchestration` |
| Memory | [CampaignGenerator#381](https://github.com/kostadis/CampaignGenerator/pull/381) | `feat/cycle-orchestration` | `feat/cycle-memory` |
| Integration | [CampaignGenerator#382](https://github.com/kostadis/CampaignGenerator/pull/382) | `main` | `feat/cycle-integration` |
| Skills | [mytools#151](https://github.com/kostadis/mytools/pull/151) | `main` | `feat/cycle-skills` |
