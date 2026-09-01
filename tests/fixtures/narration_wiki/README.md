# Narration-wiki fixtures

Every test copies the relevant fixture tree before running a mutation. The
checked-in copies are immutable evidence inputs, never output directories.

- `layouts/` owns historical collection shapes.
- `gate1/` owns pattern and seed-conflict drafts.
- `proposals/` owns proposal source documents and candidates.
- `portable/` owns companion capability/index variants and is always read-only.
- `campaigns/` owns isolated campaign guidance examples.

Tests hash fixture inputs before and after a workflow when immutability is part
of the contract.
