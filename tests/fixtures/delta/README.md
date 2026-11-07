# delta fixture (spec 039)

`campaign/` is a synthetic campaign (invented names, no private data) used by every
spec 039 test. Tests copy it to `tmp_path`; never run against it in place.

Chapters 001-002 are the baseline; 003 is the new chapter.

| NPC | Published | Chapter 003 disposition |
|---|---|---|
| Brannoc Ironvein | horizon ch002 (`ch001-002`) | changed: restarts the forge |
| Envoy Sella Marr | horizon ch001 (`ch001-001`) | mentioned_unchanged: one passing sentence in 003.02 |
| Tobin Fenwick | none (in registry) | new: first appears in 003 |
| Old Marrow Pike | none (NOT in registry) | unresolved: unknown name, relays the Lantern Guild offer |

Other: faction `The Lantern Guild`, location `Emberfall`; PCs (players.yaml) Ruck Halloway,
Sister Ines. `Sister Ines` is also in the registry as an NPC entry and speaks a ch002 moment.

Secrets canary: `CANARY-SECRET-7f3a` lives only in
`docs/npcs/authored/brannoc-ironvein.authored.yaml`, composed into the GM dossier
and (by design, the published dossier is GM-only) the published `brannoc-ironvein.md`.
It must never appear in a prompt or `runs/*/*.user.md`.

## Invariants that hold (checked by `tests/test_delta_fixture.py`)

- `validate.scan` over `docs/summaries` has no blocking findings; `build_corpus` works.
- Each published dossier's `published_body_sha` equals its header digest and the
  `publish_log.json` `published_sha256`.
- Draft / GM / verify (`**Verdict: pass**`) / authored files exist for each range folder; the
  GM header's draft sha matches the draft bytes (so `npc_publish` plans them cleanly).
- Produced by the real `npc_compose.compose_gm` and `npc_publish.publish` (signoff checker
  bypassed). No authority ledger or review snapshot exists in the fixture; tests that need
  signoff must create them.
- Draft evidence-pack lineage (`runs/`, `record.json`, corpus `state/`) is NOT in the fixture.
