# CLI Contract: `sd_verify_quotes`

Deterministic quote verification against a session transcript. **Calls no
model.** Modifies no quote text.

## Synopsis

```bash
sd_verify_quotes --vtt FILE (--summary FILE | --scene-extractions DIR)... \
                 --out FILE [--threshold F] [--min-tokens N] [--report-only]
```

## Arguments

| Flag | Default | Required | Description |
|---|---|---|---|
| `--vtt FILE` | — | **yes** | Session transcript. Must be the **same VTT the artifact was generated from** (D9); the report records which was used |
| `--summary FILE` | — | one of | Stage 1 `session-summary.md`. Checks `> "…"` blockquotes only (D5) |
| `--scene-extractions DIR` | — | one of | Stage 2 dir. Checks every `NN_*.md`, `## Verbatim moments` section only (D4). Skips `.prev`, `.reviewed`, `.scaffold.md` — mirroring `api_pipeline_status` |
| `--out FILE` | `quote_report.md` in the artifact's dir | no | Where the report is written |
| `--threshold F` | `0.85` | no | `near`/`unverified` boundary (D8) |
| `--min-tokens N` | `4` | no | Below this a quote is `unscored` (D7) |
| `--report-only` | off | no | Suppress in-place annotation (FR-008) |
| `--verbose` | off | no | Per-quote classification to stdout |

At least one of `--summary` / `--scene-extractions` is required; both may be
given. There is **no** `--backend`/`--model`/`--fast`/`--batch` flag — the tool
calls no model, and offering the flags would imply otherwise.

## Behaviour

1. Read and parse the VTT (`session_doc.io.parse_vtt`), strip speaker prefixes (D6).
2. Parse quotes from each artifact.
3. Classify each into `verified` / `near` / `unverified` / `unscored` / `exempt`.
4. Write the report.
5. Unless `--report-only`, append `<!-- cg:unverified -->` to `unverified`
   quote lines — idempotently.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Ran; **no `unverified` quotes**. `near`/`unscored` may exist |
| `1` | Ran; **one or more `unverified` quotes**. Not an error — a finding |
| `2` | Could not run: VTT missing/unreadable/empty (FR-011), no artifact given, artifact unreadable |

Distinguishing `1` from `2` is what lets `sd_agent` continue on findings while
stopping on breakage (FR-019).

## stdout

```
[sd_verify_quotes | transcript: GMT20260624-…transcript.vtt | threshold 0.85]
============================================================
  scene_extractions_new/  12 files, 522 quotes
    verified    336   (64%)
    near        148   (28%)   — not verbatim, but traceable to a transcript line
    unverified    8   (2%)    ← review these
    unscored     22   (4%)    — under 4 tokens, no reliable signal
    exempt        8   (2%)    — [inaudible] / (paraphrase) / (truncated)
============================================================
  8 unverified quote(s). Wrote narration/quote_report.md
```

Percentages always shown: a bare count of 8 does not tell the GM whether the run
was healthy.

## Report format

```markdown
# Quote Verification Report

**Generated**: 2026-08-03T14:22:10
**Transcript**: `GMT20260624-035836_Recording.transcript.vtt`
**Threshold**: 0.85 (near/unverified boundary)

| verdict | count |
|---|---|
| verified | 336 |
| near | 148 |
| **unverified** | **8** |
| unscored | 22 |
| exempt | 8 |

## Not checked
- Inline `"…"` spans in prose — not reliably dialogue (e.g. `the "liberators of
  the Ordning"` is a label, not speech). Only `> "…"` blockquotes are verified.
- Speaker attribution. This report answers *were these words said*, not *did
  this person say them*.
- `## Scene summary` sections — human-authored gm-assist content.

## Unverified — review these

### `03_the_universal_basic_treasure_proclamation.md:47`
- **Quote**: "The Privy Council had heard this proposal, and we were waiting…"
- **Score**: 0.21
- **Nearest transcript line** (Kostadis Roussos): "the privy council has not
  heard this proposal, and we would be waiting…"

## Near — traceable, not verbatim (informational)

### `01_return_to_phandalin.md:31`
- **Quote**: "I do cross promotions."
- **Score**: 0.93
- **Nearest transcript line** (David Mendenhall): "I do, like, cross promotions."
```

`near` entries are collapsed/last deliberately — they are the majority (D1) and
burying the 8 real findings under 148 benign ones would defeat the report.

## Guarantees

- No quote text is altered (FR-006, SC-007).
- Re-running on an already-annotated artifact leaves it byte-identical
  (FR-007, SC-006).
- No network call, no API key read, no token spent (FR-003).
