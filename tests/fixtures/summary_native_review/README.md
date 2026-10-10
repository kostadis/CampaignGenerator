# Disposable summary-native review campaign

This fixture is synthetic. It is the only campaign tree used by review,
migration, failure-injection and identity-application tests.

`selection.json` materializes 25 NPC finding IDs, 38 duplicate-pair IDs and
the four grounding drafts. `npcs.json`, `duplicates.json`, and `documents.json`
contain the exact synthetic records selected by those IDs. `expected.json` declares the seven taxonomy
categories and refusal cases (scoped aliases, type mismatch, anti-merge guard,
path collision and authored-content conflict). Tests may copy this directory;
they must never point mutations at a live campaign.
