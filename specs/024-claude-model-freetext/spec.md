# Feature Specification: Hand-Entered Claude Model Ids

**Feature Branch**: `024-claude-model-freetext`

**Created**: 2026-09-06

**Status**: Draft

**Input**: User description: "on the home page when I select the backends, I can't enter a claude model by hand, and that means when anthropic releases a new model, I can't use it. Anthropici si the only model that behaves this way"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Adopt a newly released Claude model the day it ships (Priority: P1)

Anthropic announces a new model. The GM opens the app, picks the metered Anthropic
backend in the app-wide selector, types the new model's id into the MODEL field,
and runs a narration pass with it. Nothing is edited, rebuilt, reinstalled, or
released; the choice sticks across page loads and app restarts the same way a
listed model does.

**Why this priority**: This is the whole complaint. Today the MODEL control on the
metered Anthropic backend offers a fixed set of choices and nothing else, so a
model that shipped after the last release is unreachable from the app at any
price. The GM's only recourse is a code change — a release cycle standing between
them and a model they are already entitled to run. Every other part of the system
already accepts the id; only this control refuses to carry it.

**Independent Test**: Choose the metered Anthropic backend, type a Claude model id
that is not among the offered choices, save, reload the app, confirm the typed id
is still selected, and run any single-model pass. Delivers the entire value of the
feature on its own.

**Acceptance Scenarios**:

1. **Given** the app-wide backend is the metered Anthropic API and the MODEL
   control offers a curated set of ids, **When** the GM enters a Claude model id
   that is not in that set, **Then** the entry is accepted and becomes the active
   app-wide model.
2. **Given** a hand-entered Claude model id is active, **When** the GM reloads the
   app, **Then** the same id is still shown and still active.
3. **Given** a hand-entered Claude model id is active, **When** the GM starts any
   run that uses the app-wide model, **Then** the run is dispatched with exactly
   the id the GM typed, with no substitution and no silent fallback to a listed id.
4. **Given** a hand-entered Claude model id is active, **When** the GM opens a page
   that shows which model a run will use, **Then** that page reports the typed id
   as the resolved model with the same origin labelling any listed model gets.

---

### User Story 2 - Same freedom on the subscription Claude backend (Priority: P2)

The GM is running on the Claude subscription backend rather than the metered API,
for cost reasons. They want the new model there too, and expect the MODEL control
to behave identically to the metered one.

**Why this priority**: Both Claude backends are closed in exactly the same way and
for the same reason, so fixing one and not the other leaves the GM guessing which
of the two lets them type. It is the same defect wearing a second label; splitting
it across releases manufactures a dialect. It sits below P1 only because the
metered backend is where a brand-new model becomes available first.

**Independent Test**: Switch the app-wide backend to the Claude subscription path,
type an unlisted Claude model id, save, and confirm it persists and dispatches —
without touching the metered backend's setting.

**Acceptance Scenarios**:

1. **Given** the app-wide backend is the Claude subscription path, **When** the GM
   enters a Claude model id that is not among the offered choices, **Then** the
   entry is accepted and becomes the active app-wide model.
2. **Given** the GM has a different model remembered for each backend, **When**
   they switch from one Claude backend to the other and back, **Then** each
   backend's remembered model — hand-entered or listed — is restored unchanged.
3. **Given** every supported backend in turn, **When** the GM looks at the MODEL
   control, **Then** the way a model id is entered is the same on all of them.

---

### User Story 3 - A new model is not mistaken for a weak one (Priority: P2)

The GM sets a just-released Claude model as the ensemble synthesis model — the
most capable thing they have — and the page tells them it may be too weak for the
job, because the only thing it knows is that the id is unfamiliar. They want the
warning to be about capability, not about familiarity.

**Why this priority**: Being able to type the id and then being told the choice is
a bad one is a half-fix. The warning is derived from the same curated set the
selector was gated on, so it goes stale on exactly the same schedule and misfires
on exactly the model this feature exists to enable. Left alone, it trains the GM
to ignore a warning that is sometimes right.

**Independent Test**: Set the ensemble synthesis stage to an unlisted Claude model
id, confirm no weakness warning appears; set it to a genuinely sub-tier model,
confirm the warning still appears.

**Acceptance Scenarios**:

1. **Given** a hand-entered Claude model id is chosen for a stage that grades model
   capability, **When** the page evaluates that choice, **Then** no "may be too
   weak" warning is raised on the grounds that the id is unlisted.
2. **Given** a model the GM has judged to be below the stage's capability bar,
   **When** the page evaluates that choice, **Then** the warning is raised exactly
   as it is today.

---

### User Story 4 - Keep one-click access to the models already known (Priority: P3)

The GM overwhelmingly picks from a handful of familiar models. They should not
have to remember and retype `claude-opus-5` to do the thing they do every day.

**Why this priority**: This is a no-regression requirement rather than new value.
It is last because the feature is still a net win without it, but shipping free
text *instead of* the shortlist would trade one friction for another and make the
common case worse.

**Independent Test**: With the metered Anthropic backend active, select a listed
model in a single interaction, without typing, and confirm it is applied — exactly
as before this feature.

**Acceptance Scenarios**:

1. **Given** the app-wide backend is a Claude backend, **When** the GM opens the
   MODEL control, **Then** the curated ids are still offered as selectable choices.
2. **Given** the curated ids are offered, **When** the GM picks one, **Then** it is
   applied in a single interaction with no typing.

---

### Edge Cases

- **Empty entry.** Clearing the MODEL field means "let this backend choose its own
  default" — the same meaning it already carries on the backends that accept typed
  ids today. It must not be stored as a literal empty model that a run then tries
  to dispatch.
- **Surrounding whitespace.** A pasted id arriving with leading or trailing spaces
  is stored trimmed, so it does not become a second, near-identical entry that
  fails at the provider.
- **An id that cannot belong to the chosen backend.** A vendor-namespaced or local
  id typed while a Claude backend is active is an incompatible pair. The existing
  pair-compatibility rule applies unchanged, and the mismatch is reported *before*
  a token-spending run starts — not discovered mid-run.
- **A plausible id that does not exist.** A typo in an otherwise well-formed Claude
  id cannot be caught locally without a model registry, and inventing one would
  re-create the staleness this feature removes. The provider's own error is the
  answer, surfaced verbatim; the app must not imply it validated the id.
- **A retired id still on the shortlist.** The curated set is a snapshot and will
  drift. A listed id that the provider has since retired fails at the provider like
  any other bad id; the shortlist confers no guarantee.
- **A hand-entered id on a page that grades model capability.** The ensemble page
  warns when the chosen model looks too weak for its stage, and that judgement is
  derived from the same curated set — so a newly released, *more* capable model
  earns a spurious warning. In scope (FR-012). The genuine weak-model warning must
  survive (FR-013): the exclusion the set encodes is a human judgement about tier,
  and only the "unknown means weak" inference is wrong.
- **Per-page overrides.** A page-level model override already accepts a typed id.
  A hand-entered app-wide model must be overridable there and inheritable from
  there exactly as a listed one is.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The app-wide MODEL control MUST accept a model id typed by the GM on
  every supported backend, including both Claude backends.
- **FR-002**: The app-wide MODEL control MUST continue to offer the curated set of
  known Claude ids as selectable choices on the Claude backends, so a familiar
  model is still reachable in one interaction without typing.
- **FR-003**: A hand-entered model id MUST persist across page loads and app
  restarts, stored the same way and in the same place as a selected one.
- **FR-004**: A hand-entered model id MUST be remembered per backend, so switching
  backends and returning restores what the GM last chose for each.
- **FR-005**: The system MUST dispatch runs with exactly the id the GM supplied —
  no substitution, no normalisation beyond trimming surrounding whitespace, and no
  fallback to a curated id.
- **FR-006**: An empty MODEL entry MUST be stored as "no model chosen" (defer to
  the backend's own default), not as an empty model id.
- **FR-007**: The system MUST NOT reject a model id on the grounds that it is
  absent from the curated set. Absence from that set carries no meaning about
  whether the id is valid.
- **FR-008**: The existing model/backend pair-compatibility rule MUST continue to
  apply to hand-entered ids, and an incompatible pair MUST be reported before any
  run that would spend tokens.
- **FR-009**: Where a page reports which model a run resolved to and where that
  choice came from, a hand-entered id MUST be reported with the same fidelity and
  the same origin labelling as a curated one.
- **FR-010**: Adopting a newly released Claude model MUST require no change to any
  file in the repository and no new release, install, or server restart.
- **FR-011**: The model-entry affordance MUST be uniform across backends: a GM who
  has learned to set a model on one backend MUST find the same mechanism on every
  other.
- **FR-012**: Where a page warns that the chosen model may be too weak for its
  stage, that warning MUST NOT fire on a hand-entered Claude id merely because the
  curated set does not list it. Absence from the set is not evidence of weakness —
  a newly released model is the case most likely to be both absent and the
  strongest thing available.
- **FR-013**: The capability judgement behind that warning MUST remain expressible:
  a model the GM genuinely should be warned about MUST still produce the warning
  after this change. Opening the gate to unknown ids must not silence it for known
  weak ones.

### Key Entities

- **Model selection**: The GM's app-wide choice of which model to run. Holds a
  backend, a model id that may now be either curated or hand-entered, and the
  remembered per-backend model ids. Already persisted; this feature widens what
  values the id may take, not where it lives.
- **Curated model shortlist**: A hand-maintained snapshot of known Claude model
  ids, offered as convenience choices. After this feature it is advisory only — a
  starting point, never a gate. Its authority is what changes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A GM can start a run on a Claude model that the app has never heard
  of, within 30 seconds of opening the app, with no code change, no release, no
  reinstall, and no restart.
- **SC-002**: The number of repository files that must be edited to adopt a newly
  released Anthropic model drops from at least one to zero.
- **SC-003**: All five supported backends present the same model-entry mechanism —
  zero backends behave differently from the rest.
- **SC-004**: Choosing one of the curated models still takes a single interaction
  and zero keystrokes; the common case is measurably no slower than before.
- **SC-005**: 100% of incompatible model/backend pairs are reported before a
  token-spending run begins, whether the model was typed or selected.
- **SC-006**: A hand-entered model survives 100% of app reloads and backend
  round-trips without reverting to a curated default.
- **SC-007**: Zero spurious "may be too weak" warnings are raised for a
  hand-entered Claude model, while a genuinely sub-tier model still raises one —
  measured against the same set of models before and after the change.

## Assumptions

- **The engine already accepts arbitrary Claude ids; only this control refuses
  them.** Model/backend compatibility is decided by an id-shape rule, deliberately
  not by membership of the curated set, precisely so a legitimate id that has not
  been added yet is never refused. This feature makes the app-wide control agree
  with a rule the rest of the system already follows. If that turns out to be
  false anywhere, that place is in scope as a defect.
- **Augment, don't replace.** The curated choices stay and typing is added
  alongside them, rather than the shortlist being removed in favour of a bare text
  field. The GM asked to be *able* to type, not to be required to.
- **No accumulation in v1.** A typed id becomes the current selection and is
  remembered for its backend, but is not added to the offered choices for later
  reuse. A "recently used" list is a separate feature; the per-backend memory
  already covers the realistic case of one new model at a time.
- **The curated set stays a hardcoded snapshot.** Relocating its *source* so the
  set itself can be extended without a release is a known, separately deferred
  piece of work. Free-text entry solves the GM's problem without it, and doing
  both at once would couple this fix to a change in another repository.
- **No state-shape change, so no migration.** The stored model is already a free
  string; this feature widens which strings can reach it. No config schema
  changes, no workspace layout changes, and therefore no migration CLI or
  migration document is required.
- **A typed id cannot be validated locally.** There is no authoritative list of
  live model ids available to the app, so the provider's error is the only honest
  validation. The app reports that error rather than pre-judging the id.
- **Per-page model overrides are already free text** and are not changed by this
  feature, beyond inheriting and overriding a hand-entered app-wide value
  correctly.
- **Scope is the app-wide model selector plus the ensemble capability warning**
  (GM's ruling, 2026-09-06). Those are the two places the curated set is treated as
  authoritative. Auditing every other model-facing surface for the same pattern was
  considered and declined as unbounded; if a third such place is found while
  planning, it is a defect to file, not silent scope growth.
- **Ensemble per-stage model fields already accept typed ids** and are not
  otherwise touched — only the warning computed from their value changes.
- **The capability warning's exclusion is a human judgement worth keeping.** The
  set encodes "at least as capable as the mid tier", which is a real bar the GM set
  deliberately. FR-013 keeps it; only the inference "not in the list ⇒ too weak" is
  removed.
