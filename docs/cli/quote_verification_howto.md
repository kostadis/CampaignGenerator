# Quote verification — how to actually use it

> Task-oriented walkthrough for the GM. What to run, in what order, what the
> report means, and what every error says. The *reference* lives in
> [`docs/cli/session_doc_pipeline.md`](session_doc_pipeline.md) (flags, where it
> sits in the pipeline) and [`docs/config/session-editor-isolation.md`](../config/session-editor-isolation.md)
> (the `verify:` config group). This page is the operator's manual.

## The three things that confuse everyone first

**1. It calls no model, and it is free.** A quote is a span of the VTT or it is
not. There is no `--backend`, no `--model`, no `--endpoint` — the whole tool has
eight flags and none of them is about an LLM. Run it as often as you like; it
costs nothing and needs no network. **You do not need the DGX** (or any
endpoint) to use it.

**2. It is entirely optional.** Nothing in the existing pipeline calls it. Keep
running `enhance_summary` and `scene_extract` exactly as before and nothing
changes. Verification happens only when you type the command or click the
button.

**3. It never fixes anything.** The only writes are additive
`<!-- cg:unverified -->` / `<!-- cg:refused:R1 -->` markers on flagged lines,
applied idempotently — quote text is never altered, and `--report-only`
suppresses even that. You apply the repairs yourself in Claude. That is
deliberate: the autonomous-repair alternative is what silently stripped spells
out of narration in issue #151.

**4. It reports two different things.** A **verdict** answers *is this in the
tape*. A **refusal** answers *may the pipeline choose this*, and the answer is
routinely "no" for a quote that is perfectly verbatim. See
[The refusals](#the-refusals-contract-250) below.

---

## Step 0 — one-time setup (this is probably your actual blocker)

The two CLIs are `[project.scripts]` console scripts. The web UI resolves them
through `console_script()` against **the server's venv**, not `$PATH`, so they
must be installed there:

```bash
# which venv is the server on?
cat /proc/$(pgrep -f 'server.main' | head -1)/environ | tr '\0' '\n' | grep VIRTUAL_ENV

cd ~/src/CampaignGenerator
uv pip install -e . --python ~/.venvs/main/bin/python

# verify both exist
ls ~/.venvs/main/bin/sd_verify_quotes ~/.venvs/main/bin/sd_agent
```

**No server restart is needed** — `console_script()` resolves per request.

**Symptom when skipped:** the Verify button fails with
`Stream error — check terminal.`, because the subprocess tried to spawn a
`<venv>/bin/sd_verify_quotes` that does not exist.

---

## Step 1 — run a stage

Run **from the campaign root**, not the session directory. `scene_extract`
auto-discovers `docs/entity_registry.yaml` from the CWD, and that registry is
what tells the model which names denote the same NPC.

```bash
cd ~/Phandalin/Phandalin
SESS=summaries/20260810

sd_agent --stage summary --session-dir "$SESS" \
    --vtt "$SESS"/*.cleaned.vtt \
    --context docs/campaign_state.md docs/world_state.md docs/party.md
```

That runs `enhance_summary`, then verification, then the consistency check, and
**stops**. Add `--backend dgx --model <id>` to generate on the Spark; with no
backend flag it uses Claude exactly as before.

Every resolved command is printed before it runs, so you can see the hop.

### Then you review. This is the point.

Read `session-summary.md` and fix it. `sd_agent` deliberately has **no
`--stage all`** — the Stage 1 → Stage 2 boundary is a human checkpoint, and an
orchestrator that ran through it would delete the thing that makes the pipeline
trustworthy.

---

## Step 2 — read the report

`<session-dir>/narration/quote_report.md`. Go straight to **`## Unverified`** —
that is the actionable list, typically ~12 per session.

Each entry gives you the quote, the **nearest real transcript line**, and the
score, so a reflow is distinguishable from a fabrication at a glance:

```
### `session-summary.md:33` (§ Memorable Moments)

- **Quote**: "That treasure came from you. That is your treasure. It was
  stolen from you... I want to give it back to you."
- **Likely stitched**: contains `...` — two separate utterances joined into one.
- **Score**: 0.82
- **Nearest transcript line** (David Mendenhall): "That treasure came from you.
  That is your treasure. It was stolen from you."
```

### What you will actually find

Measured on real sessions: **about 9 of every 12 flagged quotes are stitches** —
two real utterances welded into one — and 0–1 are genuine inventions. **The fix
for a stitch is splitting it into two quotes, not rewording it.**

### The trap: `near` means *an edit*, not *a safe edit*

Skim the `## Near` list for **changed words, not for low scores.** Similarity
cannot separate a harmless edit from a damaging one, because both are edits of
the same size:

| score | quote | transcript | |
|---|---|---|---|
| 0.92 | "**My kind** has been spreading violence…" | "**Mankind** has been spreading violence…" | meaning changed |
| 0.94 | "No, I have my soul is for rent." | "No, I, I have, my soul is for rent." | harmless |

The corrupting edit scored *lower* than the harmless one. No threshold splits
them — so do not go looking for a better number, look at the words.

---

## Step 3 — fix it, then re-check for free

Apply repairs in Claude. Then:

```bash
sd_agent --stage summary --session-dir "$SESS" \
    --vtt "$SESS"/*.cleaned.vtt --skip-generate
```

`--skip-generate` re-runs the checks against the artifact already on disk. No
tokens, no regeneration — use it to confirm you fixed what you meant to.

---

## Step 4 — Stage 2, once the summary is right

```bash
sd_agent --stage scenes --session-dir "$SESS" \
    --vtt "$SESS"/*.cleaned.vtt \
    --gm-player Kostadis
```

Writes `scene_extractions_new/` and `narration/quote_report_scenes.md`, then
stops before narration. Same review loop.

`--dossier-dir` is only needed when **no** entity registry is discoverable from
the CWD; a registry supersedes a dossier scan outright. The run tells you which
case you are in.

---

## Choosing the `.vtt` — this is not a tie-break

**Always pass `--vtt` explicitly.** A session usually carries both
`*.transcript.vtt` (raw ASR) and `*.transcript.cleaned.vtt` (the
`/vtt-spell-pass` output). On session 20260623 they differ on **72 cue lines** —
every difference a proper noun (`Blueberry`→`Brewbarry`, `Cryovane`→`Cryovain`) —
and the *same* 522 quotes score:

| VTT | verified | near | unverified |
|---|---|---|---|
| raw ASR | 339 (65%) | 139 (27%) | **39** |
| `.cleaned` | 374 (72%) | 113 (22%) | **31** |

**A 26% swing in the finding count from the transcript choice alone.** Any
"unverified" number is meaningless without naming the VTT behind it.

Verify against **the same VTT the artifact was generated from**. Left to itself,
`sd_agent` takes the first alphabetically — which is `…cleaned.vtt`, chosen by
the letter "c" rather than by anything reasoned — and prints which one it used.

---

## The five verdicts

| verdict | meaning | act on it? |
|---|---|---|
| `verified` | exact, or differing only by whitespace/reflow | no |
| `near` | traceable to a real line, but edited | **skim for changed words** |
| `unverified` | no plausible source line | **yes — this is the list** |
| `unscored` | under 4 tokens; matches anything, so no score means anything | no |
| `exempt` | `(paraphrase)`, `(truncated)`, `[inaudible]` — the sanctioned markers | no |

Exit codes: `0` nothing unverified and nothing refused, `1` findings, `2` could
not run. **A finding is not an error.**

---

## The refusals (contract #250)

A second, independent axis, from the ratified
[extraction contract](../design/ExtractionContract_proposal.md). It appears as a
`## Refused` section at the top of the report, before `## Unverified`, because a
refusal is the stronger claim: an unverified quote is a thing to look at, a
refused span is a thing the pipeline has **declined to decide for you**.

| rule | fires when | what to do |
|---|---|---|
| **R1** | the `## Scene summary` and `## Verbatim moments` copies of one span disagree and **neither** is verbatim in the tape | read the cue. Usually the tape is the thing that is wrong. |
| **R3** | a span marked verbatim carries an editorial insertion — `"that's our next [stop]."` | rewrite the span as what was said and move the clarification outside the quote |

Three things worth knowing before you read your first one:

- **A refusal is not an accusation.** It is not saying the text is wrong. It is
  saying that choosing between two readings is a scope decision, and this
  pipeline is not the thing that should make it.
- **A refused span can be `verified`.** `> "…the strength of [Lathander]"`
  matches the tape once the bracket is stripped, and is still an editorial hand
  inside something labelled verbatim. Verdict and refusal are computed
  separately and a line can carry both markers.
- **The usual fix is R2 — correct the tape, not the quote.** On the session
  that produced this contract, *every* refusal traced back to Zoom mishearing a
  word and the extraction quietly repairing it: cue 224's *"the strength of the
  pandemic"* became "Lathander", cue 324's *"our next system"* became "our next
  [stop]", cue 1211's *"much respect for the thunder"* became "[Lathander]".
  Sixteen in one session. When that is what you are looking at, edit the
  `.cleaned.vtt` cue and re-run — the check is free.

**Bare `[inaudible]` is preserved, not refused.** It states a fact about the
tape; deleting it fabricates certainty. The same marker carrying a guess —
`[inaudible — probable "I'll fill you in"]` — *is* refused, because it is the
guess that would render.

**What R1 will not do:** wake you up over two things that were both actually
said. A span verbatim in both copies is never a conflict, however similar the
two copies look. On the evidence corpus that exclusion suppressed nine
would-be interruptions and left four.

**"Refuse" means detect, mark and report — nothing is blocked.** `sd_narrate`
still renders whatever is in `smoothed/`, and that is the settled end state
rather than a gap.

**Rename the heading in your voice-smoothed layer.** A section called
`## Voiced moments` declares that its quotes are tidied, and R1 and R3 then
have nothing to say to it — R3 objects to an editorial hand inside a span
*marked verbatim*, R1 asks which of two copies is *faithful*, and neither
question survives the declaration. Measured on ch46: refusals **18 → 0**, and
the verdict counts do not move at all. Every splice and fabrication in the
layer is still reported, because `unverified` means untraceable whatever the
heading claims.

So a smoothed layer that renames its heading stops being nagged about edits it
exists to make, and keeps being checked for the ones it should not.

---

## What it does not check

Stated in every report, because silent non-coverage reads exactly like a pass:

- **Inline `"…"` in prose.** Only `> "…"` blockquotes are verified — an inline
  span is not reliably dialogue (`the "liberators of the Ordning"` is a label).
  **Know the cost**: a local model that writes dialogue inline rather than as
  blockquotes can have as little as **3%** of its quoted material checked at
  Stage 1. If your summary has few `> "…"` lines, this tool is barely looking at
  it.
- **Speaker attribution.** It answers *were these words said*, not *did this
  person say them*.
- **`## Scene summary` sections** — human-authored gm-assist content, not model
  output. It is never accused of anything. R1 does read it, but only as the
  *other copy* of a span, so the worst a mis-parse there can do is fail to
  notice a conflict.
- **Multi-line blockquotes.** None exist in the measured corpus; if any appear
  the report counts them rather than skipping silently.

---

## The web UI

Session Doc Editor gains a **Verify Quotes** button and a ✓ pipeline dot showing
`verified / near / unverified` plus staleness (the dot goes `warn` when the
report is older than the artifact it checked). It shells out to the same CLI and
writes the same report to disk — there is nothing the UI can do that the command
line cannot.

The dot goes `warn` on **either** axis — unverified quotes or contract
refusals. A run with nothing unverified and a dozen refused spans is not a
clean run, so it does not show green. The strip does not yet say *which* axis
tripped it; open the report for that.

Knobs live in `<config>/session_doc.yaml`:

```yaml
verify:
  threshold: 0.85     # near/unverified boundary
  min_tokens: 4       # below this a quote is `unscored`
  report_only: false  # true = never write the marker
```

**Leave `threshold` alone.** Sweeping it across its whole plausible range moved
2 quotes out of 390 on real data. It is not the lever.

---

## Troubleshooting

| message | what it means |
|---|---|
| `no .vtt found in <dir> — pass --vtt explicitly` | No transcript in the session dir. It refuses to guess. |
| `transcript parsed to no dialogue: <path> — wrong file, or not a WebVTT?` | The file parsed to zero cues. **It raises instead of reporting every quote unverified** — that would read as a catastrophic fabrication rate when it is operator error. |
| `transcript not readable: <path> (…)` | Permissions or a bad path. |
| `Error: give --summary and/or --scene-extractions` | Nothing was named to check. |
| `Error: no NN_*.md scene extractions in <dir>` | Wrong directory, or Stage 2 has not run. |
| `No quotes found. Nothing was checked — this is NOT the same as everything passing.` | The parser found no `> "…"` blockquotes. Usually an older extraction format, or a summary that quotes inline. **Do not read this as a pass.** |
| `gm-assist not found` / `session-summary not found: … run --stage summary first` | Stage ordering — the input for this stage does not exist yet. |
| `generation failed (exit N). Stopping — there is nothing to check.` | Generation broke, so verification was skipped deliberately. Checking an artifact that was never produced reports nonsense. |
| `warning: verify could not run (exit N) — continuing, but this run did NOT verify that.` | A check that could not run is not a check that passed. |
| `consistency check SKIPPED — no --context given` | Pass grounding docs with `--context`, or accept that step did not happen. |
| `--backend dgx: no endpoint … Refusing to fall back to the Anthropic API` | You asked for the local box and nothing named one. Pass `--endpoint`, set `DGX_ENDPOINT`, or render `dgx_endpoint` into `config/wiring.yaml`. It will not quietly bill the metered API instead. |
| UI: `Stream error — check terminal.` | Console scripts missing from the server's venv — see Step 0. |

---

## A first run, end to end

```bash
cd ~/Phandalin/Phandalin
SESS=summaries/20260810

# see what would run; nothing executes, nothing is spent
sd_agent --stage summary --session-dir "$SESS" \
    --vtt "$SESS"/*.cleaned.vtt --dry-run

# check an artifact you already have, without regenerating it
sd_agent --stage summary --session-dir "$SESS" \
    --vtt "$SESS"/*.cleaned.vtt --skip-generate

# or bypass the orchestrator entirely and check both stages at once
sd_verify_quotes --vtt "$SESS"/*.cleaned.vtt \
    --summary           "$SESS/session-summary.md" \
    --scene-extractions "$SESS/scene_extractions_new" \
    --out               "$SESS/narration/quote_report.md" \
    --report-only
```

The last one is the cheapest way to audit any session you already have on disk —
including old ones. It costs nothing and touches nothing.
