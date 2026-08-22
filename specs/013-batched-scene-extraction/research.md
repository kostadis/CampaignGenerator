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

## Open items for `/speckit-tasks`

- The `chars_per_token` constant used by the projection (D4) is a single
  declared value; 4.0 fits the measured prose. It belongs next to the multiplier
  as a named constant, not inlined at the call site.
- The 4.2 multiplier is calibrated on 15 scenes from two sessions. That is
  enough to choose it over the alternatives and not enough to call it settled;
  the run report (FR-018) is what lets it be re-tuned from evidence later.
