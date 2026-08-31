# Quickstart: Validate Thread UI Consistency and Overflow Access

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **UI contract**: [contracts/ui.md](./contracts/ui.md)

## Prerequisites

- The existing Python test environment is installed.
- Frontend dependencies are installed under `frontend/`.
- A campaign workspace can load `/grounding/threads`; use a disposable
  workspace if creating unusually long test content.
- Browser zoom is set to **100%**.

## 1. Automated regression checks

From the repository root:

```bash
python -m pytest tests/test_threads_ui_absences.py tests/test_threads_ui_style.py -q
npm --prefix frontend run build
```

Expected:

- existing no-auto-ruling, no-bulk-control, reachability, and derived-count
  guards remain green;
- feature 018's source-contract guards confirm a page-local two-axis scroll
  owner, standard theme tokens, explicit loading presentation, and absence of
  the legacy light-theme fallback dialect;
- Vue/TypeScript production compilation succeeds.

These checks do not substitute for the rendered-browser review below.

## 2. Start the application

Use the normal launcher from a campaign workspace:

```bash
./startup --campaign-dir /path/to/campaign
```

Or run the development pair from the repository checkout:

```bash
uvicorn server.main:app --reload --port 8000
npm --prefix frontend run dev
```

Open `/grounding/threads` in a supported desktop browser.

## 3. Baseline visual comparison (User Story 2)

At 100% zoom, compare Threads with `/grounding/projections` and one other
established page.

Verify all of the following:

- page background, padding, title hierarchy, body type, and section spacing
  follow the same application conventions;
- panels, borders, inputs, selects, buttons, disabled/hover/focus states, code,
  and output use the common dark palette;
- no light card, light form, pale-blue badge, or light error box remains;
- loading, empty, error, populated, expanded-form, and maintenance states do
  not revert to the former palette;
- semantic states remain distinguishable by text and standard accent color.

## 4. Static horizontal overflow (User Story 1)

Use a populated Threads page with a long unbroken title, identifier, source
path, evidence value, or expanded form row. Narrow the browser to a supported
desktop width until content exceeds the available page region.

Verify:

1. a horizontal scroll control belongs to the Threads content region;
2. the application sidebar and non-Threads shell do not become a second scroll
   region;
3. scrolling right exposes every formerly clipped field and action;
4. controls reached by scrolling remain focusable and complete their existing
   workflow;
5. vertical scrolling still reaches the horizontal control when both axes
   overflow.

For a precise browser check, inspect the Threads root in developer tools:

```js
const page = document.querySelector('.threads')
({ clientWidth: page.clientWidth, scrollWidth: page.scrollWidth, scrollLeft: page.scrollLeft })
```

In the overflow case, `scrollWidth` is greater than `clientWidth`, and changing
`scrollLeft` makes the rightmost content visible.

## 5. Dynamic content and resizing (User Story 3)

1. Start with a Threads state that fits horizontally.
2. Open an accept or maintenance form, load a wider candidate set, or reveal a
   long evidence/output value.
3. Confirm horizontal access appears without reloading the route.
4. Resize the browser narrower and wider while horizontally scrolled.
5. Confirm all content stays reachable and the available scroll range updates.
6. Collapse the wide content or widen the browser until it fits.
7. Confirm no unnecessary horizontal scrollbar remains.

## 6. Non-Threads regression check

Return to the two comparison pages used in step 3. Confirm their palette,
layout, vertical scrolling, and horizontal behavior are unchanged. This is the
acceptance gate for FR-013.

## Acceptance record

Record the tested browser, viewport sizes, and states reviewed. Success
requires both automated commands to pass and a human to accept all visual and
overflow scenarios; this document does not authorize task generation or
implementation without that review.
