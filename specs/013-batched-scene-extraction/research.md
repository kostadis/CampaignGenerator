# Research: Batched Scene Extraction

**Feature**: 013-batched-scene-extraction | **Date**: 2026-08-22

Codebase survey and the measurements behind the plan's decisions. Extend this
rather than re-deriving it.

---

## D1 — Where the per-scene loop lives, and why it costs what it costs

`campaignlib/scenes.py:201` — `run_scene_extraction`. It assembles the system
prompt **once** (prefix + full VTT + NPC roster, lines 252–258) and then loops
scenes, calling `stream_api(client, system_prompt, user_prompt, model,
max_tokens=…, cache_system=cache_vtt)` once per scene (line 274).

The transcript is therefore identical on every call. What differs by backend is
whether that repetition costs anything:

| Backend | What happens to the repeated transcript |
|---|---|
| `anthropic` | `cache_system=True` sets a `cache_control` breakpoint; scenes 2..N read the prefix at cache-hit rates. `--batch` compounds it with the Message Batches discount. |
| `claude-code` (subscription) | `_blocks_to_text` (`campaignlib/api/backends.py:367`) flattens the cache blocks to plain text. Each call is a **fresh `claude -p` subprocess with a fresh session** (`_claude_code_generate`, line 409). Nothing is reused. |

Batch submission cannot rescue the subscription path either: the batch
capability map in `campaignlib/selection.py` requires the `anthropic` backend,
so `resolve_selection` refuses a batch selection on `claude-code` before any
subprocess is built. **The per-scene loop is the subscription's only mode.**

**Decision**: add a sibling engine function in the same module rather than
branching inside `run_scene_extraction`. Both share
`plan_scene_extraction`, `build_scene_extraction_system_prompt`,
`format_scene_output` and `snapshot_scene_for_rerun`, so the two modes cannot
drift on file layout, naming, or force semantics.

**Rationale**: Constitution V (one seam per boundary) — the Anthropic boundary
stays behind `stream_api`; Constitution VI (CLI is the engine) — the router
gains a flag, not logic. Branching inside the existing loop would put two
control flows in one function whose failure modes differ completely
(per-scene resumable vs. response-splitting).

**Alternatives rejected**: (a) a `batched: bool` parameter on
`run_scene_extraction` — the loop body and the response handling share almost
nothing; (b) doing it in `session_doc/scene_extract.py` — puts engine logic in a
CLI, and the batch path already demonstrates the engine/CLI split.

---

## D2 — Measured cost of the current behaviour

Phandalin corpus (`~/Phandalin/Phandalin/summaries/`):

| Quantity | Measured |
|---|---|
| Transcript size | 106–150 KB (≈ 15–20K tokens) |
| Scenes per session | 5–8 |
| Transcript transmitted per full re-extract (subscription) | **5–8×** ≈ 90–145K tokens |
| Same, if sent once | ≈ 18K tokens |

An 8-scene re-extract on the subscription therefore ships roughly **125K tokens
of pure repetition**. That is the whole of the saving this feature is after.

---

## D3 — What the model actually generates (corrects the spec's framing)

The spec's "≈ 29K tokens output" was measured over the **whole extraction file**.
That over-counts: `format_scene_output` (`campaignlib/scenes.py`) assembles the
front-matter, the `# {name}` heading and the `## Scene summary (from gm-assist,
verbatim)` block **locally**, from values already in hand. The model generates
only the `## Verbatim moments` body.

Measured over the moments section alone:

| Session | Scenes | Generated output |
|---|---|---|
| 20260729 | 7 | 67,225 ch ≈ **16.8K tokens** |
| 20260811 | 8 | 92,029 ch ≈ **23.0K tokens** |

**Consequence**: the 32,000-token ceiling the GM chose is better-sized than the
29K figure suggested — an 8-scene session lands at ~23K, leaving ~28% headroom.
No decision changes; the ruling stands and is now on firmer ground.

---

## D4 — How to project a scene's output before the response exists

Grouping needs an estimate of output size, made before any response exists.
Measured over 15 scenes across the two modern-format sessions:

| Predictor | Result |
|---|---|
| Pearson r (gm-assist body chars → output chars) | **0.784** |
| Output chars per body char | min 2.4, **median 4.2**, max 6.5, stdev 1.2 |
| Constant per scene | mean 10,616 ch, stdev 3,891 ch (CV ≈ 37%) |

Body-scaled beats a flat constant (CV ≈ 29% vs 37%), and it degrades sensibly:
a scene with more bullets really does produce more moments.

Validated at session level against the 32K ceiling:

| Session | Actual | median ×4.2 | conservative ×6.5 | constant |
|---|---|---|---|---|
| 20260729 (7 scenes) | 16.8K → 1 group | 16.5K → 1 ✓ | 25.5K → 1 ✓ | 18.6K → 1 ✓ |
| 20260811 (8 scenes) | 23.0K → 1 group | 23.1K → 1 ✓ | 35.7K → **2 ✗** | 21.2K → 1 ✓ |

**Decision**: project as `body_chars × 4.2 ÷ chars_per_token`, using the
**median** multiplier — explicitly *not* a conservative one.

**Rationale** — the two error directions cost the same thing:

- **Over-estimate** → an unnecessary split → one extra transcript transmission.
- **Under-estimate** → a short response → the tail scenes are re-requested on
  the next run → one extra transcript transmission.

Because the costs are symmetric, the expected cost is minimised by the central
estimate, not by a safety margin. A conservative multiplier does not buy safety
here; it just pays the same penalty more often (and the table above shows it
mis-splitting a session that fitted comfortably).

**Consequence for the design**: the projection is inherently imprecise and the
design must not depend on it. It decides *how many groups to try*, nothing more.
Correctness comes from the response-splitting and short-response handling
(D5, D6), which never consult it.

### In-situ validation (2026-08-22, after T004–T007 landed)

Running the implemented `project_scene_output` + `group_scenes` over the real corpus:

| Session | Scenes | Projected | Actual | Error | Groups @32K |
|---|---|---|---|---|---|
| 20260811 | 8 | 23,336 tok | 23,007 tok | **1.4%** | 1 ✓ |
| 20260729 | 7 | 21,862 tok | 16,806 tok | **30.1%** | 1 ✓ |

**The 30% miss is an artifact, not a bad multiplier.** D4's ratios were computed
with the **stored** scene bodies (the `## Scene summary` block inside each
extraction file) as the denominator, but the code necessarily projects from the
**live parse** of `session-summary.md` — that is the only body available before
extraction runs. Measured difference between the two sources:

| Session | Live-parsed body | Stored body | Δ |
|---|---|---|---|
| 20260811 | 22,225 ch | 21,964 ch | +1% |
| 20260729 | 20,821 ch | 15,716 ch | **+32%** |

20260729's summary was **edited after its extraction ran**, so its stored bodies
are an older, shorter revision. Pairing the new body with the old output
over-states the ratio. The only clean pair in the corpus is 20260811, which gives
4.14 — essentially the 4.2 median.

Two consequences worth carrying forward:

1. **The grouping outcome is unaffected**: both sessions still produce exactly
   one group at the 32K default, which is the decision the projection exists to
   make. A 30% over-estimate is well inside what DM-5/DM-6 tolerate.
2. **Recalibrate against live-parsed bodies, not stored ones.** Anyone re-tuning
   `OUTPUT_CHARS_PER_BODY_CHAR` from the extraction files will silently inherit
   this artifact wherever a summary was revised post-extraction. The stored body
   is a snapshot of what the summary said *then*; the multiplier is applied to
   what it says *now*.

**Alternatives rejected**: (a) conservative multiplier — mis-splits, see table;
(b) flat constant per scene — ignores the 2.4–6.5 spread; (c) asking a model to
estimate — a model call to decide how many model calls to make, and a scope
decision taken by an LLM, which Constitution II forbids.

---

## D5 — Splitting one response back into per-scene content

**Constraint**: the split must be deterministic, with no model call and no
similarity matching (FR-004). It must survive:

- arbitrary human-authored scene names, including duplicates and names
  containing markdown;
- the model's own output vocabulary — `**[Speaker]** — *context*`,
  `> "quote"`, `**[scene tag]**`, `- beat` (see `config/agents/scene_extract.md`);
- a continuation seam, since `_claude_code_generate` concatenates auto-continued
  turns and warns that a seam may exist.

**Decision**: paired sentinel lines carrying the **request index**, with the
scene name echoed for verification only:

```
<<<CG-SCENE 03 BEGIN: The Margaster Hypothesis>>>
…moments…
<<<CG-SCENE 03 END>>>
```

- **Attribution is by index**, not by name — so duplicate scene names and names
  the model re-words are both harmless. The echoed name is compared and a
  mismatch is a hard failure (FR-005), never a re-assignment.
- **Completeness is structural**: a scene is complete iff its BEGIN and END
  markers are both present, in order. A response that stops mid-scene leaves an
  unmatched BEGIN, which is exactly the "incomplete, do not write" signal
  FR-011 needs.
- The `<<<CG-` prefix appears nowhere in the extraction vocabulary, and a scene
  name cannot forge one because names appear only *after* `BEGIN:` on a line
  that already began with the sentinel.

**Alternatives rejected**: (a) markdown headings (`## {name}`) — collide with the
model's own `**[scene tag]**` conventions and cannot express "incomplete";
(b) JSON — the extraction output is prose containing quotes and newlines, so
every quote becomes an escaping hazard, and a truncated JSON document yields
nothing at all rather than the complete-scenes-so-far that FR-010 requires;
(c) name-only delimiters — breaks on duplicate names, and matching a re-worded
name back to a request is exactly the similarity-based identity assertion this
repo forbids.

---

## D6 — Force / skip-if-exists under batching

`plan_scene_extraction` (`campaignlib/scenes.py:334`) already returns one entry
per scene with `exists` set, and both existing callers filter on it:
`_build_pending_requests` (`session_doc/scene_extract.py:105`) does
`pending = plan if args.force else [p for p in plan if not p["exists"]]`.

**Decision**: the batched engine filters with the same expression, **before**
building the request — the filtered set is what gets sent, what gets projected,
and what gets grouped (FR-008a).

**Why this needs saying**: the naive batched shape is to send every scene and
discard the already-extracted ones on the way out. It produces correct files, so
it passes a casual test, while spending the full projection on a session that is
5/8 done — the exact cost the feature exists to remove. FR-008a/SC-005a exist to
catch precisely that.

`snapshot_scene_for_rerun` already implements the force semantics (snapshot to
`.prev` only when content differs, clear the `.reviewed` marker) and is called
per file, so it carries over unchanged. An empty request set means **no call at
all** (FR-008b) — today's free no-op must not become a paid one.

---

## D7 — The output ceiling: two defaults, not one

`ExtractKnobs.tokens` (`server/session_editor_config_shared.py:195`) defaults to
`8192`, and `tests/test_session_editor_config_service.py::test_extract_tokens_defaults_to_scene_extract_cli_default`
pins it to `scene_extract.py`'s own `--max-tokens` default. FR-017b requires the
per-scene default to stay put while the batched default is 32,000.

**Decision**: a second, separate knob — `ExtractKnobs.batch_tokens: int = 32000`
alongside `tokens: int = 8192`, with a matching `--batch-max-tokens` on the CLI.

**Rationale**: two modes with genuinely different right answers get two declared
fields. The existing pin stays green and keeps meaning what it says; a campaign
that never touches either sees per-scene behaviour unchanged. This is the
repo's established pattern — declare the default once in the shared config model
and let the route resolve it (cf. `EnsemblePaths`/`EnsembleTuning`).

**Alternatives rejected**: (a) one field whose default depends on the mode —
argparse cannot distinguish "unset" from "set to the default" without
`default=None`, which would break the pinning test and make the CLI's own
default invisible; (b) reusing `tokens` and multiplying by scene count —
silently changes the per-scene meaning of a field the GM already tunes.

---

## D8 — Activation: pre-selected on the subscription

The editor already knows its backend server-side: `_editor_service_selection`
(`server/routers/scene_editor.py:626` region) reads `cfg.backends.active`, one of
`anthropic` / `claude-code` / `dgx` / `openrouter`.

**Decision**: the effective default is computed server-side as
`cfg.backends.active == "claude-code"` and exposed on the resolved-config
payload; the UI renders a checkbox initialised from it, and the GM's explicit
choice for the run overrides it. The run forwards the flag explicitly, so the
subprocess command stays fully explicit and copyable.

**Precedent**: `forceReextract` (`SessionDocEditor.vue:205`, shipped for #323 /
spec 012) is the same shape — a `ref(false)` bound to a checkbox, appended to
the SSE URL as a query param. This one differs only in that its initial value
comes from the resolved config instead of a literal.

**Rationale**: satisfies FR-007a's "visible and overridable, never invisible".
Constitution X is about the *scene set* being explicitly chosen, and that is
still governed by Force / skip-if-exists (FR-008) — not by this toggle.

---

## D9 — Prompt changes

`config/agents/scene_extract.md` opens with *"The user will name one scene at a
time"*, and `scene_extract_user.md` renders exactly one `{name}`/`{body}` pair.

**Decision**: leave both files untouched and add a **second pair** for the
batched mode (`scene_extract_batched.md`, `scene_extract_batched_user.md`),
loaded through the existing `load_agent_prompt`.

**Rationale**: the per-scene prompt must keep working verbatim (FR-009), and the
two prompts differ in more than a sentence — the batched user prompt renders N
scene blocks and must specify the sentinel protocol, while the batched system
prompt must state that the per-scene ground rules apply *within each scene*
(FR-016) and that scenes must be emitted in the order given, exactly once each.

**Critical**: every verbatim rule in the existing system prompt — no merged
utterances, no editorial insertions inside quotes, no repairing transcript
garbles, transcript-owns-its-own-mistakes — must be carried over intact.
Constitution IV is the thing most at risk when one response has to ration a
budget across N scenes, and US3/SC-003/SC-004 are the gate on it.

---

## D10 — Fidelity measurement

`session_doc/sd_verify_quotes.py` + `session_doc/verify_quotes.py` already parse
`## Verbatim moments` (`parse_scene_quotes`, `verify_quotes.py:636`) and classify
each quote against the VTT deterministically, with no model call, in three
buckets (`verified` / `near` / `unverified` — spec 007, research D1).

**Decision**: SC-003 and SC-004 are measured with this tool, run over a
per-scene extraction and a batched extraction of the same session.

**Caution carried forward from spec 007 and from prior work**: `near` is *not*
"safe" — a 0.92 similarity can be a meaning-changing misquote while 0.94 is a
harmless disfluency edit, and no threshold separates them. So SC-003 must be
read on the **`verified` (exact) rate**, and a batched run that converts
`verified` quotes into `near` ones is a regression even if the total count holds.

---

## D11 — What must not change

- **The metered path.** Per-scene + `cache_system` already achieves the reuse
  this feature chases. `run_scene_extraction`, `_build_pending_requests`, the
  `--batch` submission path and the 8,192 default all stay exactly as they are
  (FR-009, SC-008).
- **The transcript.** `_build_pending_requests` carries a comment recording why
  there is no `input_normalizer` on this path: extraction emits verbatim quotes,
  so the VTT must reach the model exactly as transcribed, and aliases arrive as
  roster knowledge via `format_npc_roster`. PR #231 fixed this once; the batched
  path must not reintroduce it (FR-015).
- **The Stage 1 → Stage 2 gate.** Scene structure comes from the human-reviewed
  summary via `parse_gmassist_scenes`. Nothing here lets a model propose or
  revise a scene boundary (FR-019).

---

## D12 — Incidental defect found during the survey

`frontend/src/components/scene-editor/KnobDrawer.vue:229` still tells the GM
*"The Re-Extract button always forwards `--force` so prior per-scene files are
snapshotted to `.prev` and rewritten."* That stopped being true with #323 /
spec 012, which made Force an explicit unchecked control. The help text now
describes the opposite of the behaviour, on the very drawer where the batched
toggle and its token knob will be added.

**Decision**: correct the text as part of this feature's UI task. It is one
sentence, it sits in the section being edited, and leaving a stale claim about
force semantics next to a new force-sensitive control is how the next reader
gets it wrong.

---

## D13 — Pre-existing test failures (baseline, recorded 2026-08-22)

`python -m pytest tests/ -q` on this branch **before any implementation**:

```
4 failed, 3719 passed, 189 skipped in 127.22s
```

The four failures are inherited from `main` — this branch's only commits at the
time of measurement were spec documents (`specs/`, `CLAUDE.md`,
`.specify/feature.json`), touching no code:

| Test | |
|---|---|
| `tests/test_extract_facts.py::test_cli_parallel_fully_cached` | |
| `tests/test_mempalace_client.py::TestLiveRoundTrip::test_search_hierarchical_on_fresh_palace_falls_back` | live-service dependent |
| `tests/test_provenance_mcp.py::test_the_server_builds_when_mcp_is_installed` | |
| `tests/test_session_doc_prompts.py::test_prompt_matrix_matches_golden` | golden-file drift |

**This is the regression baseline.** "No regression" for T059 means these four
and no others. Recorded because a green-suite assumption is how a pre-existing
failure gets attributed to whoever touched the tree last — and because
`test_session_doc_prompts.py::test_prompt_matrix_matches_golden` is a *prompt
golden-file* test, which this feature adds prompts to (T013/T014). If that test's
failure mode changes, it is this feature's doing; if it merely keeps failing the
same way, it is not.

---

## Open items for `/speckit-tasks`

- The `chars_per_token` constant used by the projection (D4) is a single
  declared value; 4.0 fits the measured prose. It belongs next to the multiplier
  as a named constant, not inlined at the call site.
- The 4.2 multiplier is calibrated on 15 scenes from two sessions. That is
  enough to choose it over the alternatives and not enough to call it settled;
  the run report (FR-018) is what lets it be re-tuned from evidence later.

---

## D14 — Fidelity gate, measurement 1: FAILED (recorded 2026-08-22)

**Note on numbering**: tasks.md T046 says "record as a new D13". D13 was already
taken by the pre-existing-test-failure baseline that T059 depends on, so this is
D14. Do not renumber D13.

**Corpus**: `~/Phandalin/Phandalin/summaries/20260811` — 8 scenes, 146,772-char
cleaned VTT, 1,441 cues. Both runs `--backend claude-code --model claude-opus-5`,
`MAX_THINKING_TOKENS=0` (the backend's default), no `--party`/`--party-config`,
so no deterministic speaker normalisation ran in either.

Baseline frozen read-only at `/tmp/sx_perscene_baseline` (T003). It was produced
by **main's** per-scene code — see the shadowing note at the end. That is valid,
and the check is stronger than "the diff looks additive":

- `campaignlib/scenes.py` removes zero lines vs `main`, and
  `run_scene_extraction`'s function body is **byte-identical** (4,334 chars)
- `config/agents/scene_extract.md` is untouched
- `session_doc/scene_extract.py` removes exactly 2 lines, and **both are
  comments** that were reworded and expanded — no executable line was removed,
  and the new batched code sits behind `if args.batch_scenes:`

(An earlier revision of this entry called those 2 lines a diff-renderer
artifact. They are real removals; they are simply comments. The conclusion was
right for the wrong reason, which is worth correcting because the whole gate
rests on this baseline being comparable.)

The per-scene path main ran IS the per-scene path this branch ships.

### What the feature buys (SC-001) — confirmed

**What is measured**: transcript transmissions, 8 → 1. The run report prints
this count, and the payload is identical across them — the system prompt is
built once, outside the group loop.

Transmitted input tokens therefore fall by exactly **1 − 1/8 = 87.5%**. That
ratio is a property of the transmission count, not of any tokenizer, so it
holds whatever the true chars-per-token is.

**What is estimated**: the absolute token counts. The `claude-code` path
reports no usage at all (`campaignlib/api/backends.py` has no `usage` /
`input_tokens` handling on that branch), so these are character counts divided
by a constant:

| | transmitted input tokens (est.) | transcript sent |
|---|---|---|
| per-scene | ~158,700 | 8× |
| batched | ~19,800 | 1× |
| | **−87.5%** (measured ratio) | |

The transcript-bearing system prompt is 146,804 chars ≈ 19,838 tokens at the
transcript's **~7.4 ch/tok**.

> ⚠️ An earlier revision of this entry published 293,608 → 36,701, using
> `CHARS_PER_TOKEN = 4.0`. That constant is wrong for this purpose and this
> file said so two sections up: 4.0 is the **generated-prose** estimate, and
> the transcript is precisely the text that runs ~7.4. The old figures
> overstate the absolute volume by ~1.85×. The 87.5% was never affected — it
> is a ratio of transmissions of the same payload — but it was presented
> alongside numbers described as measured when they were derived.

Wall-clock, recorded as **observation only** (there is no time threshold — GM
ruling): per-scene 415.0s, batched 356.6s. Tokens are the committed measure.

### Projection accuracy — good

`group_scenes` projected 23,336 output tokens; the per-scene run actually
produced 23,684. **−1.5%.** This validates `OUTPUT_CHARS_PER_BODY_CHAR = 4.2`
against real generation, and supersedes the D4 addendum's 30%-high probe on
20260729 — that discrepancy was the calibration artifact (stored bodies vs the
live parse of an edited summary), not a bad constant.

### SC-003 exact rate — PASSED

`sd_verify_quotes --threshold 0.85`, both runs:

| | verified (exact) | near | unverified |
|---|---|---|---|
| per-scene | 937 (100%) | 0 | 0 |
| batched | 702 (100%) | 0 | 0 |

Zero-point drop. Every quote batching produced is a real span of the tape. This
is the criterion D10 said to read, and it holds.

### SC-004 per-scene moments — FAILED

| scene (request order) | base m/q | batch m/q | moment Δ |
|---|---|---|---|
| 01 Arrival at the Counting House | 53/90 | 40/69 | −25% |
| 02 Securing the Loan | 112/164 | 59/114 | −47% |
| 03 Auditing the Moral Economy | 86/139 | 46/75 | −47% |
| 04 The Margaster Hypothesis | 87/105 | 49/79 | −44% |
| 05 The Heir of Alagondar | 108/131 | 78/123 | −28% |
| 06 The Notary of House Margaster | 54/87 | 42/67 | −22% |
| 07 The Shut Down Shipping Hub | 36/47 | 19/34 | −47% |
| 08 Confrontation at Margaster Logistics | 118/174 | 81/141 | −31% |
| **TOTAL** | **654** | **414** | **−37%** |

Every scene exceeds the 20% loss bound.

**It is NOT tail thinning** — head mean −35%, tail mean −39%. And the run used
21,426 of its 32,000-token ceiling, so the model never rationed for room. The
enumerated T047 triggers (exact-rate drop >5pts, tail thinning) therefore both
failed to fire on a run that plainly regressed. **T047's trigger list is
narrower than SC-004; SC-004 is the gate.** Do not pass a run because the two
named shapes are absent.

Quote-set diff: 199 lost, 35 new, 665 shared. Lost quotes skew short (median 21
chars — `"Yeah."`, `"Why?"`, `"Nope."`) against a kept-median of 54, but the
tail of the lost set includes substantive GM narration, so this is not purely
table noise being tidied away.

### The finding the success criteria did not anticipate: attribution drift

The VTT's speaker labels are **only** Zoom participant names — `Kostadis
Roussos` (533), `Stéphane Bourdeaud` (330), `David Mendenhall` (312), `Wade
Brown` (170), `Gary Young` (96). No character name appears as a label anywhere.

| | headers | bracketed | character-name labels absent from the tape |
|---|---|---|---|
| per-scene | 654 | 11% | ~5% |
| batched | 414 | 100% | **66%** — `[Vukradin]` 104, `[Brewbarry]` 101, `[Soma]` 40, `[Valphine]` 29 |

The batched model inferred the player→character mapping and wrote it into the
speaker label as fact. Quotes stayed verbatim-exact; **who said them was
silently re-decided.** That is `alias = identity, never substitution` (PR #231,
Constitution IV) reappearing at a different layer — not as a text transform this
time, but as a model inference promoted to record.

**The root cause is not prompt drift.** The two prompts were identical on
speaker rules — same `**[Speaker]**` template, same normalisation block. The
per-scene run ignored the brackets; the batched run read them as literal syntax.
The difference is context: reading eight scenes at once supplies enough evidence
to work out who plays whom, and the model acted on it.

> **Batching increases the model's confidence in cross-scene identity inference,
> and it acts on that confidence.** More context makes it *more* likely to make
> the one precision decision it must not make. Any future change that widens a
> model's view across scene boundaries inherits this risk.

Being right most of the time does not help: nothing downstream can separate a
correct inference from a wrong one, because both look identical.

### T047 response

`config/agents/scene_extract_batched.md` tightened on three points:

1. **The label comes from the tape** — a new section stating the rule, why it
   lives in the batched prompt and not the per-scene one, and that a character
   the model is confident about belongs in the context clause after the em-dash
   (where it reads as inference) rather than in the label (where it reads as
   record).
2. **Brackets are not syntax** — `**[Speaker]**` is a placeholder; scene tags
   and `[inaudible]` markers own the brackets.
3. **Granularity** — keep short beats; one moment per speaker turn; do not
   consolidate a run of turns into one block.

### Operational note: the worktree shadowing trap (cost one run)

The first batched attempt died instantly with `unrecognized arguments:
--batch-scenes`. `python -m session_doc.scene_extract` puts the CWD on
`sys.path[0]`, so running it from the campaign directory resolved the module
through the editable-install `.pth` — which hardcodes the **main** checkout.

The loud failure was luck. `--batch-scenes` does not exist on `main`, so it
errored. Any flag that exists in both trees (`--force`, `--max-tokens`) would
have run main's implementation silently and looked like a successful run. Either
install into the venv and use the console script, or run `python -m` from the
worktree with absolute paths. Recorded in quickstart.md's prerequisites.

---

## D14 (cont.) — Fidelity gate, measurements 2 and 3: PASSED

Tool: `specs/013-batched-scene-extraction/fidelity_compare.py` (kept with the
spec so the gate is reproducible). Invoke as
`fidelity_compare.py <baseline-dir> <new-dir> <baseline-report> <new-report>`.

### Measurement 2 — after the T047 prompt tightening

| criterion | m1 | m2 | bound | verdict |
|---|---|---|---|---|
| exact (`verified`) rate | 100%→100% | 100%→100% | ≤5pt drop | pass |
| worst per-scene moment Δ | −47% | −14% | ≥−20% | pass |
| total moments vs baseline | −37% | **+15%** | — | pass |
| tail thinning | none | none | none | pass |
| speaker labels taken from tape | 32% | **100%** | — | pass |

The attribution fix worked outright: inferred character labels went 283 → **0**,
and bracketed headers 414 → 8 (those 8 being legitimate context-beat tags).

**But it introduced a new defect.** Stating "brackets belong to scene tags" made
the model copy the placeholder's own words: 8 headers came out as
`**[scene tag — Rehearsed to an Empty Room]**`, against 0 in both the baseline
and m1. The template said `**[scene tag — e.g. The Drow Spy Spotted]**`, which
names the *slot*; the model wrote the slot name into the content.

### Measurement 3 — after replacing the placeholder with a concrete example

Template changed to `**[The Drow Spy Spotted]**`, with prose saying the bracket
holds the model's own short title, never the words "scene tag".

| | per-scene baseline | batched m3 | Δ |
|---|---|---|---|
| quotes, all `verified` | 937 | **948** | +1.2% |
| moments | 654 | **835** | +28% |
| worst per-scene moment Δ | — | −17% (scene 07) | within −20% |
| PC-name substitutions | 92 (**15%**) | **0 (0%)** | **eliminated** |
| `scene tag` placeholder leak | 0 | **0** | fixed |
| wall-clock | 415.0s | 457.4s | +10% |

Per-scene moment deltas in request order: +75, +21, +1, +17, +37, +41, −17, +38.
No monotonic decay; the two low scenes are 03 and 07, neither at the end.

**GATE: PASSED.** Batched output beats the per-scene baseline on every fidelity
axis measured, at 1 transcript transmission instead of 8.

### A false positive from the gate's own tooling — corrected

`fidelity_compare.py` first reported **TAIL THINNING** on m3 (head +32%, tail
+11%). Both figures are *gains*; the heuristic fired on `tail < head - 0.15`
without checking the sign, so a run where every scene improved read as a gate
failure. Corrected to require `tail < -0.05` as well. Recorded because a
measurement tool that cries failure on a good run trains the reader to
disbelieve it on a bad one.

### Residual: a PRE-EXISTING defect in the per-scene path (not this feature's)

Of the baseline's 603 speaker headers, **92 (15%) substitute a player character's
name for the participant who spoke** — `Vukradin` 30, `Brewbarry` 23, `Soma` 22,
`Valphine` 9, plus 8 composites. None appears as a speaker label anywhere in the
tape, which carries only `Kostadis Roussos`, `Stéphane Bourdeaud`,
`David Mendenhall`, `Wade Brown`, `Gary Young`.

**NPC labels are NOT part of this defect.** `Boney` (7) and `Perrin` (4) are the
GM voicing an NPC, which the prompt explicitly permits ("Unnamed NPCs → keep as-is").
An earlier count in this file conflated the two and reported 30%; 15% is the
PC-substitution rate and is the number that matters. Batched m3 has **0**.

`config/agents/scene_extract.md` has no equivalent of the "THE LABEL COMES FROM
THE TAPE" rule that `scene_extract_batched.md` now carries. Batching did not
create this; it magnified it to 68% where it became visible, and fixing the
batched prompt drove it to **zero** — against 15% on the path that ships today.

**This is out of scope for 013 and is deliberately NOT fixed here** (changing
`scene_extract.md` would invalidate the frozen baseline mid-gate). Filed as
**#330** — the per-scene prompt needs the same rule, and the fix wants its own
before/after measurement against this same corpus.

---

## D15 — SC-002 wall-clock, recorded as an OBSERVATION (T061)

There is no time threshold on this feature. The GM ruled that tokens matter and
time does not: *"how much time I save is less important than how many tokens. in
fact, if it takes as much time I am okay."* SC-002's original ≥50% wall-clock
target was withdrawn during the analyze remediation. This entry exists so the
numbers are on record, not so they can be graded.

| run | wall-clock | moments produced |
|---|---|---|
| per-scene baseline | 415.0s | 654 |
| batched, prompt v1 | 356.6s | 414 |
| batched, prompt v2 | 436.4s | 750 |
| batched, prompt v3 (shipped) | 457.4s | 835 |

**Batching is not reliably faster, and the shipped configuration is ~10%
slower.** That is the honest reading and it is fine.

The reason is visible in the second column: wall-clock tracks output volume, not
call count. Batching removes 7 of 8 *prefills* — 256,907 input tokens that no
longer cross the wire — but decode is unchanged, and prompt v3 decodes 28% more
content than the baseline because it stopped dropping short beats. A faster run
that extracted less would be the worse outcome.

**Do not reintroduce a time target without first measuring the prefill/decode
split.** On a subscription backend the prefill is not separately billed or
timed, so "batching should be faster" is an inference from call count, and call
count is the wrong denominator. The committed measure is SC-001's transmitted-
token reduction (87.5%, D14), which is what the feature was asked for.
