# Contract: Bundled Narration Wire Protocol

**Feature**: 022-bundle-narration | Governs FR-006–FR-011 and FR-015

## 1. Request structure

The system prompt contains shared narration rules and run-wide context exactly once. The user prompt then contains one scene packet per selected full-plan index, in reviewed plan order.

Each scene packet carries:

- exact full-plan index and scene name;
- narrator and focus;
- authoritative scene events and extracted moments;
- narrator-specific voice note and style examples;
- previous-narrator contrast sample when applicable;
- an instruction to render only this scene from this narrator's first-person perspective.

The prompt requires the model to finish each scene before beginning the next and to continue scene N from the final prose line of the emitted scene N−1. A trailing table-speech audit comment is not a prose handoff.

## 2. Response grammar

Every selected scene appears exactly once, in request order:

```text
response      = *outside scene-section *outside
scene-section = begin-line LF narration LF end-line
begin-line    = "<<<CG-SCENE " index " BEGIN: " scene-name ">>>"
end-line      = "<<<CG-SCENE " index " END>>>"
index         = two-or-more decimal digits representing the full-plan index
```

Example:

```text
<<<CG-SCENE 02 BEGIN: The Bargain>>>
I knew what the smile would cost before he finished offering it.
<<<CG-SCENE 02 END>>>
```

Markers must occupy a complete line at column zero. The marker index is identity; the echoed name is a checksum. Narration bodies contain prose only and may contain Markdown or HTML audit comments, but no protocol markers.

## 3. Deterministic reconciliation

Reconciliation has two ordered stages:

1. A narration-specific preflight scans marker lines in the raw response. It tracks the open section and encounter order and rejects unknown or duplicate BEGIN indices, nesting, END without an open BEGIN, an END index different from the open BEGIN, and any recognized section encountered outside the requested full-plan order.
2. Only a response that passes raw-marker preflight is passed to `campaignlib.scenes.split_batched_response` for its established name checks and complete/empty/incomplete/absent classification.

The raw preflight is mandatory. A wrapper that inspects only the shared splitter's returned sections is insufficient because that result is normalized into request order and the splitter treats a mismatched END as stray text.

Permitted normalization:

- surrounding whitespace on marker/name fields;
- runs of internal whitespace in the echoed scene name compare as one space.

Not permitted:

- case folding, punctuation removal, slug matching, edit distance, semantic similarity, or narrator-based reassignment;
- renumbering a filtered selection;
- sorting an out-of-order response after generation.

Duplicate scene names are safe because indices differ. A duplicate index, unknown index, mismatched echoed name, nested section, stray END, mismatched end index, or out-of-order section makes the exchange unreconcilable.

## 4. Section states

| State | Structural condition | Result |
|---|---|---|
| `complete` | Matching BEGIN and END in order; body non-empty. | Marker-free body may be written. |
| `empty` | Matching pair; body blank after trim. | No write; report missing. |
| `incomplete` | BEGIN present; matching END absent. | No write; report incomplete. |
| `absent` | No BEGIN for a requested index. | No write; report absent. |
| `unreconcilable` | Any identity, nesting, END-pairing, duplication, or ordering violation. | No scene from the response is written. |

Outside text before, between, or after valid sections is ignored and never written. A response with no recognized section is unreconcilable.

## 5. Truncation and continuation seams

The backend may return accumulated text after reaching an output ceiling. Closed sections before an unclosed tail remain complete. The unclosed section is incomplete and later requested indices are absent. This produces a partial run, exit `3`. A structurally valid response with no complete non-empty section is also partial with zero writes; it is unreconcilable only when the marker/identity rules fail or no requested marker is recognized at all.

Claude Code may concatenate continuation turns. A seam inside narration prose is ordinary body text. A seam that corrupts a marker can only yield incomplete or unreconcilable state; it must never trigger fuzzy repair.

## 6. Write boundary

Parsing and whole-response reconciliation finish before the first file write. For a valid complete or partial response, complete scene bodies are written one at a time through the shared narration formatter and atomic writer. For an unreconcilable response, nothing from the exchange is written.

The written file contains the existing YAML frontmatter followed by narration prose. BEGIN/END markers and outside text never reach disk.
