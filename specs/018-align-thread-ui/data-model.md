# Data Model: Thread UI Consistency and Overflow Access

This feature introduces **no persistent entity, field, relationship, schema,
or migration**. The existing `Thread`, `Proposal`, evidence, log, and API
payload shapes remain unchanged.

The following concepts describe presentation invariants only. They are derived
at render time and must not be stored on disk or added to server payloads.

## Threads Surface Layout

| Property | Source | Rule |
|---|---|---|
| Available width/height | Browser layout of the existing application main region | The Threads root consumes the available page region without forcing an ancestor wider. |
| Content width/height | Rendered descendants: cards, evidence, forms, tables/lists, and output | Content retains its natural required size; the page owns overflow. |
| Horizontal overflow | `content width > available width` | Browser-native horizontal navigation is available. |
| Vertical overflow | `content height > available height` | Browser-native vertical navigation remains available in the same page container. |
| Fits | Both content dimensions are within the available dimensions | No unnecessary scrollbar is forced. |

### Derived state transitions

```text
fits ── content expands / viewport narrows ──> overflows
overflows ── content collapses / viewport widens ──> fits
```

These transitions are browser layout results. No Vue ref, watcher, observer,
timer, or persisted scroll-state field is required.

## Visual Role Mapping

Existing state strings remain the data source; styling adds no new meaning.

| Existing UI meaning | Standard visual role | Non-color cue |
|---|---|---|
| Normal page, panel, form, or neutral/pending item | Application base/mantle/surface and text tokens | Existing heading, label, and status text |
| Healthy, successful, ratified, or open | Success (`--green`) | Existing success/status wording |
| Warning, deferred/discussed, or dormant | Warning (`--peach`) | Existing warning/status wording |
| Error, rejected, abandoned, or failed | Error (`--red`) | Existing error/status wording |
| Matched or informational | Information (`--blue`) | Existing matched/information label |
| Active/focus/primary action | Application accent (`--mauve`) | Focus border, control label, and normal browser focus behavior |

### Validation rules

- No visual state may depend on color alone; existing text labels remain.
- Evidence quotes and CLI/server error strings remain byte-for-byte unchanged.
- Empty, initial loading, load error, loaded, streaming, expanded-form, and
  maintenance states all use the common application palette.
- Presentation mapping is local to the Threads view and never written back to
  thread registry or proposal data.

## Existing domain state transitions

Thread/proposal state transitions are explicitly out of scope. Accept, reject,
discuss, add-log, status-change, and alias actions keep their current requests,
validation, confirmations, and disk outcomes.
