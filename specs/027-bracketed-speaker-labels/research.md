# Phase 0 Research: bracketed speaker labels

**Feature**: `specs/027-bracketed-speaker-labels` | **Date**: 2026-09-08

Three unknowns entered this phase: where bracket handling should live, how a label is
tokenised without asserting an identity from its shape, and what the change costs the
existing unresolved-label report. All three are resolved below. No `NEEDS CLARIFICATION`
remains.

## The corpus, measured

Every distinct bracketed label form in
`experiments/20260907-phandalin-gm-gaps-confirm/inputs/` (33 distinct, 4 sessions):

| Class | Forms | Where |
|---|---|---|
| Character | `[Brewbarry]` `[Soma]` `[Valphine]` `[Vukradin]` | valphine, vukradin |
| Game master | `[GM]` | valphine, vukradin |
| Joint, GM + one PC | `[GM / Brewbarry]` `[Brewbarry / GM]` `[Vukradin / GM]` | valphine |
| Joint, two PCs | `[Brewbarry / Soma]` `[Vukradin / Brewbarry]` | valphine |
| Joint, three parties | `[GM / Brewbarry / Valphine]` | valphine |
| Beat marker | `[Awareness Rolls]` `[The Lead Established]` `[scene tag — The roll]` … (22 distinct) | all four |

Two corrections to what the spec was written against:

1. **Two-PC joint labels exist.** The spec's assumption said none did, and the GM's ruling on
   them was taken as hypothetical. `[Brewbarry / Soma]` and `[Vukradin / Brewbarry]` appear
   once each, and `[GM / Brewbarry / Valphine]` names three parties. The ruling (presence for
   every roster character named) now rests on data. Spec corrected.
2. **Two beat markers contain a roster character's name**: `[scene tag — Soma's Arcana check]`
   and `[scene tag — Vukradin demands a meeting]`. This is what makes Decision 3 below
   necessary.

## Decision 1 — Where bracket handling lives

**Decision**: `session_doc/io.py` becomes a pure label *reader*, returning every bold label at
the start of a line exactly as written, in order. All classification — bracket stripping,
joint splitting, resolution against the roster, and game-master recognition — moves to
`session_doc/plan_eligibility.py`, which already holds the roster and already performs the
`canonical.get(norm_name(label))` lookup that decides who a label names.

**Rationale**:

- The authority is already there. `compute_eligibility` takes `roster` and builds `_canonical`
  from it. Bracket handling needs exactly that authority, and no other caller has it.
- It keeps `io.py` free of identity knowledge. Today `io.py` has a *partial* and wrong copy of
  the identity rule — `label.startswith("[")` and `label == GM_LABEL` — sitting in a module
  that cannot see the roster. That split is the defect. One authority, one place.
- `io.py:416`'s own docstring gives the governing rule: presence and turn counts come from one
  parse, so a reviewer is never shown a turn count for a character the filter excluded. A
  single raw-label reader honours it more directly than two filtered ones (FR-009).
- It sets up #456 without doing its work. The block editor needs GM turns *enumerated*, not
  merely excluded; a reader that stops discarding them makes that a later addition rather than
  a later re-parse.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| Strip brackets in `io.py`, keep the rest as-is | The `label == GM_LABEL` check stays behind and still cannot see `[GM, as the banker]`. Splits the identity rule across two modules instead of one — the shape of the current bug. |
| Pass a resolver callable into `io.py` | Keeps `io.py` roster-free on paper while making it the orchestrator of a decision it cannot audit. Adds a parameter to a function whose two callers are one module and its tests. |
| Heuristic in `io.py` (a bracketed label is a speaker if it has no spaces, is short, is title-case…) | Shape-based identity assertion. Forbidden by FR-003, by `tests/test_no_prefix_identity.py`'s rule, and it misclassifies `[GM, as the banker]` and `[The Lead Established]` in opposite directions. |

**Blast radius**: `scene_speakers` / `scene_speaker_counts` have exactly one production
consumer (`plan_eligibility.py:154`) and appear in two test files. Nothing else in the repo
reads them.

## Decision 2 — Tokenise by shape, resolve by declaration

**Decision**: A label is split into candidate *parts* using the separators the corpus uses —
the surrounding `[…]`, and `/` and `,` inside them — and each part is then resolved
independently by exact comparison after folding case and whitespace (`norm_name`). A label's
class is decided by what resolved, never by how it looked.

- Part folds to a roster character → that character is present, one turn of evidence.
- Part folds to the declared game-master label → game-master turn; establishes presence for
  nobody.
- Part resolves to neither → contributes nothing.
- A label contributes at most one turn of evidence per distinct character, so
  `[Brewbarry / Brewbarry]` counts once.
- **Tokenisation applies only inside brackets.** A bare label is passed through whole, exactly
  as today, which makes FR-007 (bare-convention sessions unchanged) structural rather than
  something to test for.

**Rationale**: There is a real line between *tokenising* a label into candidates and
*asserting* who a candidate is. Splitting `[GM / Brewbarry]` on `/` claims only that the label
names more than one party — visible in the text. Deciding that `Brewbarry` is the roster's
Brewbarry is the identity step, and it is done the way this repo does every other one: exact
comparison against a declared name, folding case and whitespace and nothing else. FR-003 is
satisfied because no part is admitted or rejected for its shape.

**Why exact comparison and not containment** — the corpus settles it. `[scene tag — Vukradin
demands a meeting]` *contains* a roster name. Under containment it would make Vukradin present
in a scene on the strength of a beat marker: a fabricated attribution, the failure class this
whole feature tree exists to prevent. Under folded equality it resolves to nobody and is
correctly inert. `norm_name`'s own docstring already draws this line: *"Folding is not
approximate matching."*

**Alternatives considered**: splitting on `/` only (leaves `[GM, as the banker]` unresolved and
noisy); stripping any parenthetical or comma-qualified tail before resolution (a shape rule,
and it would rewrite `Vukradin (David)` into a resolution the GM is currently told about).

## Decision 3 — Beat markers must not dilute the unresolved-label report

**Decision**: A **bracketed** label from which no part resolved is reported in the quiet
bucket — counted, not listed — rather than in the "looks like a roster character but did not
resolve" bucket, regardless of whether it contains a roster name as a substring. Bare labels
keep today's containment heuristic unchanged.

**Rationale**: `_stranger_buckets` (`plan_eligibility.py:190`) splits unresolved labels in two,
and the split is load-bearing. Labels *containing* a roster name are printed individually
under a notice that says *"each one costs that character a scene"* — it exists for the
mis-normalised bare label `Vukradin (David)`, and the covering-player workflow depends on the
GM reading it. Everything else is counted, because there are dozens of NPC labels per session
and listing them buried the line that matters.

Reading bracketed labels puts 22 distinct beat markers into that report, two of which contain
a pool name and would land in the must-read bucket as false alarms. Diluting the one channel
`#385` built to be read is a real regression, which is why SC-008 asks for the count not to
grow.

The rule needs no prefix matching and no list of known markers: *bracketed and nothing
resolved* is a good enough proxy, because the bare form is where mis-normalisation actually
happens.

**Trade-off, recorded**: a genuinely mis-normalised **bracketed** character label —
`[Vukradin (David)]` — would go to the quiet bucket instead of the loud one. No such label
exists in the corpus, and the cost of the alternative (two false alarms per session in the
channel that must stay readable) is paid every run. Reversible in one line if a session
produces one. This is a *reporting* decision, not an attribution decision, so it is recorded
here rather than taken to the GM — the label is inert either way; only its verbosity changes.

## Decision 4 — No new flags, no new state, no migration

**Decision**: The feature adds no CLI flag, no config key, and no file on disk. It changes how
existing files are interpreted.

**Rationale**: Principle XIII's migration requirement is triggered by a change to the *shape*
of state on disk. Scene extractions are unchanged; the reader gets better. Principle XII is
untouched because no option is introduced. Principle XI needs no new UI surface because no new
capability or flag exists to reach — the UI already invokes `sd_plan`, and the improvement
arrives through it.

Eligibility *output* does change, and that is the point of the feature.
