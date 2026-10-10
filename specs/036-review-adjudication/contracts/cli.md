# CLI and Application Integration Contract

Planned interfaces; they do not exist yet. All commands use `summary_native` and accept `--config PATH` or `--campaign-dir DIR`; if both are given they must agree. Default config discovery is the existing `find_default_config()` behavior. One strict ReviewConfig owns defaults; routes use sentinels. Commands below accept `--json`; foreground `serve` emits one readiness JSON line and remains running, while `service start` is the bounded completion-envelope operation. IDs are opaque returned values, never paths.

## Review engine

```text
summary_native review init --campaign-dir DIR
summary_native review create --kind npc_verification|duplicate_identity|grounding_documents --selection FILE
summary_native review list
summary_native review show REVIEW [--item ITEM]
summary_native review status REVIEW
summary_native review refresh REVIEW --expected-generation N
summary_native review finding add REVIEW --finding FILE --expected-generation N
summary_native review decide REVIEW --decisions FILE
summary_native review history REVIEW [--item ITEM]
summary_native review retract REVIEW --event EVENT --expected-decision-revision N --reason TEXT
summary_native review export REVIEW --selection FILE
summary_native review import --bundle FILE --expected-generation N
summary_native review rerun-preview REVIEW --selection FILE --mode unresolved|selected
summary_native review rerun REVIEW --selection-sha256 SHA
summary_native review propose REVIEW --selection FILE
summary_native review apply REVIEW --proposal ID --proposal-sha256 SHA --reviewer NAME
summary_native review recover TRANSACTION
summary_native review signoff REVIEW --document ITEM --item-sha256 SHA --expected-decision-revision N --reviewer NAME
summary_native review promote REVIEW --proposal ID --proposal-sha256 SHA --reviewer NAME
```

- `init` creates the campaign review identity/layout deliberately; existing valid initialization is idempotent. It does not silently upgrade the authority ledger.
- Selection files contain explicit item/subject IDs and revisions, or explicit document paths for local review creation. Empty/missing selection refuses. The application materializes Select all. NPC creation calls scoped verification over selected dossiers; duplicate creation consumes explicit candidate pairs; document creation selects the existing world_state, campaign_state, party, planning drafts.
- `refresh` checks semantic item continuity and journals a new source-manifest custody generation; it never changes an immutable item revision or transfers an exact-patch approval. See verification.md for digest exclusions.
- `decide` consumes the exact DecisionEvent request contract in data-model.md; records decisions only. It records approved dispositions in authority v2 in the same journal. Source changes and publication require separate apply/promote.
- `retract` records withdrawal of the decision; applied artifacts remain tracked. The command returns required inverse-review instructions rather than undoing them.
- `export` writes a canonical immutable bundle under the review root; contains selected items/evidence/events/sign-offs and hashes, no credentials. `import` validates campaign, item revisions, provenance and expected generation. It is a reviewed local interchange operation, not a remote arbitrary-write endpoint. Imported foreign/stale decisions refuse. Arbitrary HTML narration decisions are not auto-adopted.
- At duplicate review creation, the local producer prepares bounded immutable canonical alternatives for the explicit pair (each eligible member as survivor), including global alias sets, full impact previews and proposal digests. The phone may select/approve one prepared alternative. New canonical identities, custom alias scope or modified actions become Discuss/blocked requests for trusted local proposal preparation, followed by fresh phone review. Intent alone is not an approved merge.
- `propose` dispatches typed source-correction, identity, or document-publication adapters. It never guesses replacement prose or canonical identity. Missing required fields return an actionable review requirement. Identity proposals obey the persistent-scope/type/guard refusals in identity-apply.md, build a pure candidate Registry, and never invoke the direct `registry merge` writer. A document finding needs its explicit sign-off item as well as resolved findings before publication.
- `apply` validates the reviewed digest, decision freshness, full input hashes and exact targets. Completed identical application returns its receipt. `recover` uses shared authority recovery; unexpected bytes refuse.
- `promote` publishes a reviewed grounding bundle only after existing pointer, outline, freshness, audience and required verifier checks. Proposals contain destination paths, collision checks, bundle dependencies and exact bytes. NPC publishing reuses `npc-publish`; this feature adds binding to exact review/sign-off, not a bypass of existing checks.

## Capability service management (local control only)

```text
summary_native review serve REVIEW --host ADDRESS --port PORT --origin URL [--tls-cert FILE --tls-key FILE]
summary_native review service start REVIEW --host ADDRESS --port PORT --origin URL [--tls-cert FILE --tls-key FILE]
summary_native review service status REVIEW
summary_native review service stop REVIEW
summary_native review access issue REVIEW [--expires-in SECONDS]
summary_native review access revoke REVIEW --grant GRANT_ID
summary_native review migrate --campaign-dir DIR --dry-run
summary_native review migrate --campaign-dir DIR --plan-sha256 SHA
```

`serve` is foreground; `service start` launches the same command as a managed background child and returns after a bounded readiness handshake. CLI owns start/status/stop and secure handles. Browser/SSE disconnect must not kill a successfully started review service; this intentionally uses a bounded lifecycle command, not a long-lived SSE stream. Stop validates process-start identity. Access issue returns one secret link to the trusted local caller; status never redisplays credentials. Binding is required; no implicit `0.0.0.0`. `--origin` is the exact browser origin, including external HTTPS when behind explicitly configured Tailscale Serve. No automatic Tailscale/Funnel configuration.

Migration covers live ledger v2 and identity-dependency manifests specified in migration.md; the entity registry remains v1. Dry-run returns the exact migration proposal digest; execution validates it. `--force` does not bypass review, source hashes, capability controls or migration gates. Existing source-authority commands keep their syntax.

## Exit / JSON envelope

Reuse `{ok, code, message, artifacts, data}`. Exit 0 completed; 2 invalid input/selection/version; 3 stale review/proposal; 4 recovery required; 5 unresolved/blocking finding or conflict; 70 bounded process failure. `status`, `show` and `history` return 0 with structured unresolved counts; they are inspection commands. A rerun reports its completed members even when exit 5. The existing npc-verify numeric meanings remain intact; queue output is added without claiming semantic pass.

## Main application parity

New `server/routers/review_routes.py` exposes typed local-control POST commands and read status using `server/subprocess_runner.run_bounded_json`; larger verification/rebuild commands use existing SSE execution only through trusted local application routes. Every above command has a corresponding action reachable from `SummaryNative.vue`/NPC dossier screens through a shared `ReviewLauncher` component. Creation, selection, rerun, export/import, proposal, apply/promote, retract/history, access issue/revoke, migration and recovery all have visible controls. Mutation arguments retain CLI meaning, especially digest bindings and explicit selections.

The dedicated page only reviews/saves. Apply, server administration and filesystem selection are available in trusted local application controls or CLI. Transport authorization is separate from domain judgment; all transports execute the same CLI engine with fixed argument arrays, never a shell command string. Capability/CSRF material is passed through private bounded input/environment and redacted; no secret in logged argv, saved SSE logs, or generic status.
