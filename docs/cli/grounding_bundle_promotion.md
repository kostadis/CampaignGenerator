# Grounding bundle review and promotion

Promotion publishes a reviewed summary-native range as one managed generation.
It includes all four documents, the canon timeline, the full nested reference
tree, retained dependency records, a manifest, and an accountable receipt.

First complete [grounding bundle migration](grounding_bundle_migration.md).

## Review workflow

Use the campaign's `config/grounding.yaml` and an explicit range:

```bash
summary_native claims select --config config/grounding.yaml --since 1 --until 3 --json
summary_native claims selection chunks --config config/grounding.yaml \
  --input proposed-selection.json --source <source-id> --json
summary_native claims selection save --config config/grounding.yaml \
  --input confirmed-selection.json --reviewer "GM name" --json
summary_native claims import --config config/grounding.yaml \
  --selection confirmed-selection.json --candidates candidates.json --json
summary_native claims review --config config/grounding.yaml \
  --selection confirmed-selection.json --review promotion-check --json
summary_native claims check --config config/grounding.yaml \
  --selection confirmed-selection.json --review promotion-check --json
summary_native claims show --config config/grounding.yaml --report <report-id> --json
```

`select` proposes the mandatory source closure. Confirm exact sources and only
the chunks you want sent to a model; zero chunks is a supported no-model path
with an explicit coverage limitation. `extract` is the only claims command that
calls a model and exposes backend, model, token, chunk size, and force choices.
`import` accepts attributed prepared candidates but grants them no authority.

Review every proposed normalized meaning. Run the deterministic check, resolve
semantic findings through prepared evidence-bound actions, and rerun it.
Mechanical and GM-confirmed false claims cannot be waived. Then sign the exact
current v2 item for each of `world_state`, `campaign_state`, `party`, and
`planning`. A changed source, meaning, rule, report, audience, authority record,
or document invalidates the affected approval.

Private phone review may save review decisions. It cannot select sources, run a
model, migrate, or publish.

## Preview and publish

```bash
summary_native promote --config config/grounding.yaml --since 1 --until 3 \
  --review promotion-check --check-report <report-id> --dry-run --json
summary_native promote --config config/grounding.yaml --since 1 --until 3 \
  --review promotion-check --check-report <report-id> \
  --preview-sha256 <preview-sha256> --request-id <unique-request-id> --json
```

Preview recomputes current source custody, findings, dispositions, sign-offs,
live differences, and the destination generation. It writes nothing. Commit
recomputes those bindings under the publication lock and refuses a stale
preview. Never submit a digest from an earlier preview after refreshing.

An identical retry returns the original historical receipt, even after a newer
publication. Reusing a request ID for different intent refuses.

## Status, receipt, and recovery

```bash
summary_native promotion status --config config/grounding.yaml --json
summary_native promotion receipt --config config/grounding.yaml \
  --operation <operation-id> --json
summary_native promotion recover --config config/grounding.yaml \
  --operation <operation-id> --json
```

Status is read only and may report blocked, edited live, recovery required, or
unknown without claiming publication failed. A transport loss after activation
can produce `PROMOTION_COMMIT_UNKNOWN`; keep the operation ID and inspect or
recover it. Do not retry with a new request ID. Recovery either proves the
durable activation or aborts a known preactivation attempt. It never silently
publishes an orphan.

Human edits to a live document remain visible and are included in the next
preview. Published bytes and historical receipts stay immutable. Promotion
does not edit summaries or invoke Git.
