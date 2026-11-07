# CLI Contract: `summary_native delta`

The engine. Every operation exists here first (Principle VI). Routes in `contracts/http.md` build argv that matches these commands exactly (Principle XI).

**Family conventions (Principle XII)**: `--campaign-dir DIR` (default: cwd), `--config PATH`, `--json` (machine output on stdout), `--force` (overwrite only what is already there). Model selection uses `--backend` and `--model` as elsewhere. Source selection is `--source PATH`, repeatable, never defaulted. An empty source set is an error with exit code 2. A source must lie inside the campaign root (exit 2 otherwise); a plan stores and derives its id from campaign-root-relative paths and resolves them against the root on load.

**Exit codes**: 0 success; 1 refusal (a gate said no, with the reason in the output); 2 usage or empty selection; 3 stale or conflict (a bound input changed); 4 partial (some members held or failed); 5 recovery required.

## Commands

| Command | Purpose | Key arguments | Writes |
|---|---|---|---|
| `delta plan` | Create a delta plan from explicit sources | `--source…`, `--product grounding|npc` (required, repeatable; none is exit 2), `--stop plan|prepare|propose|verify|review|preview|apply` (default `plan`), `--backend`, `--model` | plan record (new revision) |
| `delta sources` | Ingest the selection; report parsed versus integrity reads | `--plan ID` | source selection record |
| `delta baseline status` | Show bound grounding and NPC baselines and any repair requirements | `--plan ID` | none |
| `delta baseline adopt` | Explicit adoption of a valid or live-edited baseline; lists drift | `--resolve HUNK=accept|reject`… | adoption record (never rewrites history) |
| `delta census` | NPC disposition census for the selected sources | `--plan ID` | census record |
| `delta associate propose` | Propose scoped contextual associations | `--plan ID`, `--backend`, `--model` | proposals (drafts) |
| `delta associate decide` | Record a decision: approve, reject, discuss | `ID --plan ID --decision … --reviewer NAME` (reviewer required, no default; exit 2 without it), `--reason` | decision (revisioned, reviewer recorded) |
| `delta npc draft` | Draft changed and new NPCs from selected evidence (reuses `npc_draft`) | `--plan ID`, `--backend`, `--model` | drafts, run records |
| `delta npc verify` | Real native verification with sparse evidence | `--plan ID` | verify reports |
| `delta npc attest` | Record an unchanged attestation with a reason, bound to the exact published bytes | `SUBJECT --reason TEXT --publication SHA` (both required), `--plan ID` (optional; attaches the plan's sources as campaign-relative paths) | attestation |
| `delta npc publish` | Selected publication, per member, with receipts. **Without `--preview-sha` it only previews**: writes nothing and prints (`--json`: returns) the digest `preview_sha256` and per-member digests; with `--preview-sha SHA` it publishes. Requires a recorded `publication` review binding (`delta review handoff`) | `--plan ID --member SUBJECT…` (explicit; no "all"), `--preview-sha SHA` | dossier files, publish log, member receipts |
| `delta grounding propose` | Host-validated edit proposals from a model over numbered baseline lines | `--plan ID`, `--backend`, `--model` | proposals (drafts) |
| `delta grounding decide` | Approve, reject or discuss each proposal | `PROPOSAL_ID --decision … --reviewer NAME` (reviewer required, no default; exit 2 without it), `--plan ID`, `--reason` | decision (reviewer recorded in `decisions-rN.json`) |
| `delta grounding check` | Bounded consistency and preservation checks on the composed candidates | `--plan ID`, `--backend`, `--model` | check report (never an approval) |
| `delta grounding preview` | Stages the checked candidates into the promotion path (refuses, exit 1, to write into a range directory a delta did not stage) and returns a digest-bound preview. The digest covers candidates, lineage, request **and the staged promotion tree** (drafts, copied `reference/**`, manifest) | `--plan ID`, `--review ID`, `--claims-report REF`, `--request-id ID` | staged range, preview record |
| `delta grounding apply` | Whole-generation activation through the existing promotion path. Requires a recorded `publication` review binding (exit 1 without one; exit 3 if a bound hash changed) | `--plan ID --preview-sha SHA` (required; exit 2 without it) | generation, receipts |
| `delta run status` | Discoverable state: stages, statuses, member outcomes, next action | `--plan ID` | none |
| `delta run resume` | Continue from the last durable stage; reuses compatible work by digest | `--plan ID` | per stage |
| `delta receipt` | Completion receipt | `--plan ID` | receipt file |
| `delta review show` | Render the one review document (delta against the published text) and the bindings | `--plan ID` | `review/review.md` |
| `delta review handoff` | Prepare the review each product publishes against and record its `publication`-scope binding; approves nothing | `--plan ID` | combined NPC review, bindings |
| `delta transfer verify` | Prove a worktree/copy came from the canonical campaign; changes nothing | `--canonical DIR` (required), `--plan ID` | none |
| `delta transfer bind` | Verify, then write a transfer binding in the copy | `--canonical DIR` (required) | `transfer/binding-N.json` |

## Behavior rules

- A command reads the plan's pinned inputs. If a bound input changed, it exits 3 and does not proceed.
- Every command that writes a decision requires an explicit decision value and an explicit `--reviewer`. There is no default approval and no default reviewer.
- `delta npc publish` and `delta grounding apply` require a fresh preview hash. A mismatch exits 3. Both also require a recorded review binding for the `publication` scope; none recorded exits 1, a bound hash that moved exits 3.
- `delta run resume` makes zero model calls for compatible completed work. It reports the count.
- Output under `--json` includes `read_counts` (parsed new, parsed historical, integrity-only, model input), `call_counts`, and any `repair_required` entries.

## Refusals (examples, each with its reason in the message)

- Empty `--source` list: exit 2, "no sources selected; the delta does not default to all chapters."
- Sparse evidence presented as full: refused before verification.
- Draft sign-off requested without a passing native verification: refused.
- Association `discuss` or `rejected` used as drafting evidence: refused.
- Published target hand-edited: refused with the repair command.
