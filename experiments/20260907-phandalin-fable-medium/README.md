# Same prompts, different renderer — claude-fable-5-1 / medium

**Evidence only. These drafts are not campaign canon, not a chapter revision,
and not a proposal to change the production pipeline.**

Replays the three generation calls archived in
[campaigns#237](https://github.com/kostadis/campaigns/pull/237) — the September 7
narration-adaptation experiments — with one thing changed:

| | archived runs | this experiment |
|---|---|---|
| backend | `codex-cli` | `claude-code` |
| model | `gpt-6-astra` | `claude-fable-5-1` |
| effort | `medium` | `medium` |
| system + user messages | — | **byte-identical** |

Every message is copied out of the sibling experiment directories and checked
against *their* recorded SHA-256 before a single call is made. `prepare` refuses
to run if any of them has moved. That is the whole design: if a prompt were
touched here, the result would answer a different question.

## The three arms

| Arm | Replays | Prompt |
|---|---|---|
| `chapter` | [20260907-phandalin-adaptation](../20260907-phandalin-adaptation/) | the five-scene adaptation brief |
| `control` | that experiment's **B** arm | the general adaptation brief — the one the GM preferred |
| `composition` | that experiment's **A** arm | the same brief with the scene-specific composition block |

`control` and `composition` differ by exactly one paragraph; see
[`prompt.diff`](../20260907-phandalin-scene-composition/prompt.diff) in the source
experiment. On Astra, `composition` is where the self-correcting interior
narration the GM disliked appeared:

> Nothing has happened to him. I have found a symbol, not a knife at his back.
> I make myself keep that distinction too.

Whether that came from the prompt or from the renderer is exactly what a second
renderer on the same prompt can speak to — with one sample per arm, suggestively
rather than conclusively.

## Reading the results

```sh
python3 -B run.py reader
```

Builds `metrics.json` and two blind readers. **Read them before opening
`assignment.json`.**

- `scene_blind.html` — four single-scene drafts labelled W/X/Y/Z: two renderers ×
  two prompt arms, randomly assigned. Same source extraction, same POV plan, same
  examples. Neither the model nor the arm is legible from the label.
- `chapter_blind.html` — the two generated chapters labelled P/Q, beside the
  edited chapter that actually shipped. The historical chapter is openly labelled;
  its length and quote density identify it anyway.

`assignment.json` is the key, sealed by hash in `case.json` at prepare time.

## What this can and cannot settle

It can show whether the disliked structure is prompt-borne or renderer-borne, and
whether fable at medium keeps the consequential facts the smoothed extractions
carry.

It cannot establish that one model writes better than the other. One sample per
arm, stochastic decoding, no seed, no repetition — a difference between two
drafts is as consistent with run-to-run variance as with the model. Treat every
comparison here as something to look at, not something measured.

Two differences are not controlled and are not claimed to be:

- **Output ceiling.** `max_tokens=32000` is forwarded as
  `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, which the CLI enforces. The Codex adapter
  accepted the same argument and ignored it.
- **Thinking.** The Fable family runs adaptive thinking unconditionally, so the
  adapter's `MAX_THINKING_TOKENS=0` is a no-op here. What Astra did under
  `codex-cli` at medium is not equated with it.

## Provenance

- Source campaign commit `bbf4e3c064b4e13b47ed523606a62936638a0cc6`, inherited
  from the archived case, not re-resolved.
- Generator checkout `d9c5de87a0ec4831c1cdc999b26491851b1f7c01` — the same commit
  the archived runs used.
- Attestation is what the adapter *sent* (`--model claude-fable-5-1`,
  `--effort medium`), recorded per call in each arm's `run.json`. It is not a
  provider echo of what served the request; the archived Codex records have the
  same limit.
- The GM's `~/.claude/settings.json` pins `effortLevel: xhigh`, so the explicit
  `--effort medium` is load-bearing. A run whose identity records
  `"claude_code_effort_source": "inherited"` is **not** this experiment.
- One attempt was killed before it returned; see [`aborted/`](aborted/README.md)
  for why, and for the adapter banner bug that caused it. No output was lost.

Nothing outside this directory is written. The sibling experiments are read
only, and the campaign workspace is not touched at all.
