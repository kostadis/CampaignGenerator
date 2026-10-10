# Dedicated Review Server and Security Contract

## Routes

One service instance owns one configured review. `CAP` is a 256-bit unguessable token issued locally and persisted only as a hash. Match it in constant time, verify expiry/revocation and review binding on every request. Do not log request paths containing it.

| Method / capability-relative path | Effect |
|---|---|
| GET `/r/CAP/` | Packaged viewer shell and short-lived CSRF nonce bound to grant |
| GET `/r/CAP/assets/<known-name>` | Fixed packaged CSS/JS only |
| GET `/r/CAP/review` | Bounded paginated review snapshot, generation, counts and opaque item IDs |
| GET `/r/CAP/items/ITEM` | One permitted immutable item revision, its evidence and current disposition |
| GET `/r/CAP/history/ITEM` | History of that review item |
| POST `/r/CAP/decisions` | Validated explicit decision batch; invokes CLI `review decide` |

Authenticate the capability before revealing whether an item exists; authentication failures use the same generic response. Viewer resources use capability-relative paths and never include the absolute secret URL in diagnostics or page content. Everything else returns a generic 404. Disable docs/OpenAPI, static filesystem mounts and health/debug routes outside the protected namespace. No HTTP route accepts a campaign path, output path, registry mutation, apply/promote command, service control, arbitrary CLI arguments or new input source. Capability possession authorizes GM review of prepared content; player-facing review is not supported in this release.

## Request and response

POST body: `request_id`, `review_generation`, `reviewer`, `decisions[]`; each includes item ID/revision/digest, expected decision revision, verdict, explicit disposition and note, plus already-staged proposal ID/digest when required. For duplicates, the page displays prepared immutable canonical alternatives and impact previews; choosing an alternative supplies its bound proposal digest. A custom request is Discuss, never remote proposal creation or settled merge approval. Server adds fixed campaign/review/grant binding, never trusts client fields for them. CLI rechecks live grant status under the campaign lock before committing to close revocation/save races. A batch refuses entirely if any item is stale. Domain reads/writes use bounded CLI subprocesses; packaged assets and transport authentication remain adapter concerns.

Responses: 200 for saved/idempotent replay, 400 malformed input, 404 unauthorized/unknown/revoked, 409 stale/conflicting revision or reused request ID with different payload, 413 too large, 422 incompatible disposition, 503 recovery needed or bounded process failure. Return stable JSON error code and safe next action. Never echo a token, source stack trace or forbidden path. Acknowledgment is emitted only after durable journal completion. Reload/reconnect reads saved state; unsent notes may remain in memory but are never labeled saved.

## Security boundaries and selected controls

- The bind address must be assigned to a local interface and allowed by the configured private LAN, Tailscale CGNAT/ULA, or loopback policy; wildcard, unspecified and public-routable addresses refuse. Origin/Host must exactly match configured allowlist. A reverse proxy is opt-in with fixed trusted peer/origin; client-controlled forwarded headers cannot change authorization.
- Tailscale mode supports direct tailnet addressing or an explicitly configured private Serve HTTPS origin. Public Funnel is outside the supported setup. LAN HTTP is deliberately selected trusted-network transport; UI must identify transport and sharing scope. TLS key files never enter a review bundle.
- Browser mutations require `application/json`, exact allowed Origin, same-origin Fetch Metadata where present and a custom `X-Review-CSRF` nonce. No CORS. Cookies, when used for nonce binding, are HttpOnly/SameSite and Secure on HTTPS. No GET has a side effect. CLI clients use the local CLI, not exceptions to browser checks.
- Send `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, restrictive CSP (`default-src 'none'`, same-origin scripts/styles/connect, no frames or forms), `X-Content-Type-Options: nosniff` and frame denial. No CDN, telemetry, third-party image, arbitrary remote fetch or service worker. External document links render as text; source references open only captured permitted excerpts.
- Renderer uses text nodes and a small allowlisted Markdown presentation for headings, paragraphs, lists and code. Raw HTML, event attributes, scripts, SVG, data URLs, javascript URLs and external images are not executed or fetched. Long tokens wrap; code/tables may scroll within their region without horizontal page overflow.
- Limit request bytes, note length, batch members, read page size, subprocess output, process timeout and concurrent writes via one ReviewConfig. Initial limits: 1 MiB request, 16 KiB note, 100 decisions/batch, 50 items/page, 8 MiB bounded response, 30 seconds command timeout; commands return actionable limits without partial silent truncation. Evidence is paginated by item; documents use bounded sections with exact full-document sign-off digest.
- Canonicalize campaign paths during local snapshot creation; reject traversal, escaping symlinks and cross-review identifiers. Remote reads serve snapshots by ID, not request paths. Private grant files/runtime directory use owner-only permissions. Raw capabilities are excluded from application run logs and error reporters; access logs are disabled/redacted.

## Security review and release proof

Implementation must deliver a written review against these boundaries plus adversarial tests for missing/guessed/revoked/expired tokens, other-review IDs, path and symlink traversal, Host/Origin spoofing, CSRF, Markdown payloads, oversized requests, secret logging, concurrent save, replay and revocation race. Verify both grant revocation and server restart. Run tests against an actual bound service, not only mocked router calls. This document is the design threat model; implementation security verification remains an explicit release gate.

Supporting references: [OWASP CSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html), [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve). Decisions above are project-specific design choices.
