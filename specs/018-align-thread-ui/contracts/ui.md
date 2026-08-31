# UI Contract: Threads Visual Consistency and Overflow

## Route and boundary

- Existing route: `/grounding/threads`
- Existing component: `frontend/src/views/grounding/Threads.vue`
- No route, API request, response shape, CLI command, or persistent model
  changes.
- `frontend/src/App.vue`, `frontend/src/style.css`, and non-Threads views retain
  their current appearance and overflow behavior.

## Page scroll contract

The root Threads surface owns both horizontal and vertical overflow inside the
application's existing overflow-hidden main region.

| Rendered condition | Required outcome |
|---|---|
| Content width is less than or equal to available width | No horizontal scrollbar is forced. |
| Content width exceeds available width | A horizontal scrolling control is available on the Threads page. |
| Content becomes wider after load or expansion | Horizontal access becomes available without reload. |
| Content becomes narrow enough after collapse | The unnecessary horizontal control disappears. |
| Browser viewport narrows or widens | Scrollability is recalculated by normal browser layout. |
| Both dimensions overflow | The same page container supports both axes, and the horizontal control is reachable by vertical navigation. |
| User scrolls to an initially clipped control | The control becomes fully visible, focusable, and operable; its existing workflow outcome is unchanged. |

The contract requires browser-native automatic overflow, not a permanently
visible scrollbar and not a JavaScript-calculated width.

## Shared visual contract

Threads consumes the established application design language:

- page padding, maximum reading width, header hierarchy, and section spacing
  follow sibling grounding views;
- backgrounds, panels, form surfaces, borders, text, and code use the tokens
  defined in `frontend/src/style.css`;
- corresponding controls use the application's existing button, input,
  select, focus, hover, disabled, and typography conventions;
- undefined legacy variables (`--muted`, `--border`, `--chip`, `--panel`) and
  their light-theme fallback palette are not part of the Threads contract;
- error, warning, success, information, pending, ratified, rejected, deferred,
  open, dormant, resolved, and abandoned states remain named in text and use
  the standard semantic accents as a supplemental cue.

## State coverage

The contract applies to every visible state of the route:

1. initial loading;
2. top-level load failure;
3. clean or unhealthy registry;
4. empty or populated harvest result;
5. idle, running, successful, or failed harvest;
6. empty, filtered, or populated candidate queue;
7. accept, reject, and discuss forms, including validation/refusal text;
8. empty or populated ratified-thread groups;
9. maintenance forms and their success/error states;
10. wide evidence, source paths, output, identifiers, and user-entered values.

## Preserved behavior contract

- No thread action, confirmation, filtering rule, band ordering, data refresh,
  or request path changes.
- No bulk or automatic ruling appears.
- Evidence quotes remain verbatim and visually distinct from facts.
- All existing tests in `tests/test_threads_ui_absences.py` remain green.
- Non-Threads routes acquire neither a new outer scrollbar nor changed theme
  values as a side effect.

## Verification boundary

Automated source-contract tests may verify durable code structure and token
usage. Only a rendered desktop-browser review can accept the actual scrollbar,
dynamic resize behavior, focus/accessibility, and visual parity. That human
review is the gate; passing a string-based test is not evidence by itself that
the UI works.
