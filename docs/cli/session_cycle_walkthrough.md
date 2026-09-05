# Session cycle: what to do, and where

Use this walkthrough for a workflow-managed session in **Session → Production review** (`/workflow/cycle`). The pilot keeps its own copies of campaign inputs. Your normal campaign workspace is separate.

**The working loop is: ask the agent to prepare a stage → review its evidence in the editor → record your decisions → ask the agent to continue.** Your decisions are saved on disk and survive refreshes or a switch between Claude and Codex.

## Who does what

| Work | Where | Who acts |
| --- | --- | --- |
| Choose the campaign, session, source transcript, and intended scope | Chat, then verify the selection in the editor | You |
| Start the next stage, resolve its inputs, run specialist checks, and prepare a draft | Claude/Codex chat, using the shared workflow engine | Agent |
| Read outputs, inspect findings, approve/reject proposals, and sign off on a draft | Production review editor; equivalent CLI/chat decisions are available | You |
| Explain a disputed name, speaker, event, or proposed correction | Chat; use **Discuss** on the finding and **Save note** to persist your question | You and agent |
| Apply explicitly approved changes and prepare the resulting draft for another review | Agent, or **Apply selected approved changes** | Agent/tool under your recorded decisions |
| Advance to the next production stage | Ask the agent in chat after approving the current draft | Agent |

For the Phandalin pilot after Events approval, ask in chat: **“Continue the Phandalin pilot through recap removal and stop at human review.”** This starts the next production stage from the saved record. Recap removal needs native agent work; the editor’s Execute button alone does not perform it.

**Current pilot limitation:** approving a draft does not automatically start the next stage. **Resume status** reports the current work; it does not launch an agent. Native skills such as speaker attribution run in chat. The editor cannot run an arbitrary skill on its own.

## 1. Open the right pilot

From the integration checkout, start one server per campaign. The server selects the campaign; the **Session directory** field selects a session within it.

```bash
cd ~/src/CampaignGenerator-worktrees/cycle-integration
rtk proxy .venv/bin/python -m server.main \
  --campaign-dir ~/src/campaign-cycle-worktrees/Phandalin/Phandalin \
  --session-dir ~/src/campaign-cycle-worktrees/Phandalin/Phandalin/cycle-pilot \
  --port 8131
```

Open [Phandalin production review](http://localhost:8131/workflow/cycle?session=cycle-pilot).

For obelisk, use `--campaign-dir ~/src/campaign-cycle-worktrees/obelisk/obelisk`, `--session-dir ~/src/campaign-cycle-worktrees/obelisk/obelisk/cycle-pilot`, and `--port 8132`. Open [obelisk production review](http://localhost:8132/workflow/cycle?session=cycle-pilot).

Both pilot session folders are named `cycle-pilot`. **Check the campaign and transcript, not just that folder name.**

| Pilot | Captured session | Transcript |
| --- | --- | --- |
| Phandalin, port 8131 | August 25, 2026 (August 26 UTC filename) | `GMT20260826-035950_Recording.transcript.vtt` |
| obelisk, port 8132 | August 21, 2026 (August 22 UTC filename) | `GMT20260822-010308_Recording.transcript.vtt` |

The existing pilots already have workflow records. Click **Load / refresh**; do not initialize them again. **Campaign config (initialization)** is for creating a new record, not switching the server to another campaign.

## 2. Read a stage before deciding

1. Select a stage/run in the left-hand list. Multiple runs of the same stage can exist; the short ID distinguishes them.
2. Check **Selected input scope**. Expand **Resolved task, inputs, selection and generation metadata** if you need the complete source paths or generation settings.
3. Click the **Read …** buttons for its outputs. The evidence preview appears below the review workspace; scroll down if necessary.
4. Read **Checks needed**, the unresolved-finding count, and any stale-source messages.

An original transcript is evidence. A corrected transcript or smoothed dialogue is a **derived** draft, not a new verbatim source. A matching roster name identifies a player; it does not establish which character is speaking in every line.

## 3. Decide the findings

Each finding has its own **Approve**, **Reject**, and **Discuss** buttons. The current draft and proposed replacement appear separately, with each decision’s consequences beside the controls.

1. Click **Approve** to authorize the card’s proposed change, or **Reject** to retain its stated rejection outcome. The decision saves immediately; no name or rationale is needed.
2. Click **Discuss** to save an unresolved discussion flag. Add an optional question or intended wording and click **Save note** if useful.
3. You can change any saved decision using the same buttons, including after reloading the page.
4. When ready to return to the agent, click **Copy handoff for agent** and paste it into your Claude/Codex chat. The handoff identifies the campaign/session/run and includes saved decisions and discussion notes. The agent should reload the record from disk before acting. The editor does not automatically launch or message an agent.

The checkbox on a card is labeled **Select … for bulk actions**. Checking it makes no decision. For a batch, select the desired cards and expand **Bulk actions** above them. Every selected card receives its own decision record. Bulk notes and discussion groups are optional.

Approving a finding authorizes its displayed consequence; it does not apply changes or sign off on the whole draft. Ask the agent to apply approved replacements and check the new version, or use **Apply selected approved changes** under Bulk actions. The resulting draft needs separate sign-off.

## 4. Approve the exact draft

Once the required checks are complete, every finding is resolved, and you have read all outputs:

1. Click **I have reviewed this draft — approve**, in **Whole-draft sign-off**, below the findings.
2. Confirm that the stage in the left-hand list shows **approved**.

A clean check with zero findings still requires this approval. The approval covers this version and its source hashes. Editing an input or rerendering can invalidate it. If there are multiple approved versions, **Select approved version for downstream work** records which one subsequent work should use.

## 5. Continue in chat

After approving capture, for example, tell the agent:

> Continue the Phandalin pilot at `~/src/campaign-cycle-worktrees/Phandalin/Phandalin/cycle-pilot`. Read its saved workflow state, run the Identify stage using the captured transcript, and prepare the next editor review. Preserve originals and stop at the next human decision.

You do not need to translate this into JSON or manually run a skill script. The agent starts or resumes the correct task through `session_workflow`, submits outputs and findings, and tells you when to click **Load / refresh**.

For an existing open discussion:

> In the Phandalin pilot, explain finding [ID] using its recorded evidence. My intended wording is [wording]. Record only that ruling and show me the resulting draft for review.

Name the campaign and session every time you switch agents. The agent should read the saved decisions; there is no need to recreate a review page or repeat already-recorded rulings.

## Stage map

| Stage shown in the editor | Agent/tool work | Your review decision |
| --- | --- | --- |
| `prepare` | Assemble selected campaign context and prep | Is this the right context and prep scope? |
| `capture` | Preserve the selected transcript or recording-derived input | Is this the correct session and source? |
| `identify` | Match speaker labels to players; check transcription names | Are the identities and proposed transcript corrections right? |
| `events` | Establish event order and scene structure | Do these events and scenes reflect what happened? |
| `remove-recap` | Propose cuts to prior-session recap; rescue new information | Are these cuts safe, with new facts retained? |
| `extract` | Extract dialogue and check quotations/attribution | Are the quotations grounded in the selected sources? |
| `voice-smooth` | Produce explicitly derived, in-voice dialogue | Does it preserve meaning without inventing dialogue? |
| `no-mech` | Propose mechanics cleanup | Are discoveries, level changes, magic, and real outcomes preserved? |
| `plan` | Plan scene order and narrator assignment | Is this the plan and narrator selection you want? |
| `narrate` | Render, then check consistency, voice, register, and transitions | Do you approve this exact narration? |
| `release` | Assemble the selected approved version | Is the local session document and chapter identity correct? |
| `memory` | Prepare explicitly selected chapter/entity/event/thread updates | Which changes should become campaign state? |
| `prepare-next` | Assemble refreshed context for the next session | Is the next-prep context fresh and appropriately scoped? |

The pilots started at capture. New stages appear when the agent creates their runs; the left-hand list is a history of actual runs, not a clickable list of every future stage.

## What the status means

| What you see | What to do |
| --- | --- |
| `pending_agent` | Ask the agent in chat to work on that run. **Execute / show native task** exposes its task but does not launch Claude/Codex. |
| `running` | An existing CLI stage is executing. Inspect its output/log before retrying. |
| `generated` | There is a draft. Inspect missing checks and unresolved findings; generation is not approval. |
| `approved` | This draft passed its human gate. Ask the agent to continue to the next stage. |
| Stale-source reasons | Ask the agent to refresh the affected work. An old approval cannot authorize changed evidence. |
| `failed` or recovery warning | Ask the agent to inspect the saved failure/journal. Preserve the previous output; do not manually remove the record. |

**Execute / show native task** starts the existing command for a CLI stage, or returns a task description for an agent stage. It does not create the next run. Its results, and those of **Resume status**, appear in **CLI / agent interchange commands** below the review workspace. That panel is an advanced interface; normal pilot review does not require editing its JSON.

**Export review JSON** and **Import reviewed JSON** are optional handoff tools. Imports validate finding identities and source hashes. Reloading the editor already restores saved decisions without an export.

## If the screen seems stuck

- **Approval did not create a new stage:** this is the current manual chat handoff. Use the continuation request above.
- **No outputs on an Identify run:** the agent has not submitted its draft yet. Its presence alone does not mean the check has finished.
- **Approval is refused:** check missing audits, unresolved/Discuss findings, and stale-source reasons. The response should name what is still needed.
- **You cannot see newly submitted findings:** click **Load / refresh** and select the new run.
- **API 400: campaign configuration is unavailable:** use the updated integration checkout, stop the old server with Ctrl+C, rerun its launch command, and refresh. The production-configuration binding fix requires a server restart.

For command contracts and advanced operations, see [Session workflow CLI reference](session_workflow.md). For existing-session imports, see [Migration instructions](../../specs/campaign-cycle/migration.md). Pilot verification and remaining rollout gates are recorded in [Acceptance evidence](../../specs/campaign-cycle/acceptance.md).
