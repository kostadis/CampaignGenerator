# Contract: keys read from `~/.config/hypostasis/hypostasis.yaml`

CG only reads this file. Hypostasis seeds and owns it (local_machine#1).

```yaml
env:                                   # existing block; merged into the mine/search env, never overriding vars already set
  MEMPALACE_BACKEND: turbovec
  MEMPALACE_EMBEDDING_PROVIDER: ollama
  MEMPALACE_EMBEDDING_MODEL: qwen3-embedding:0.6b
  MEMPALACE_EMBEDDING_ENDPOINT: http://192.168.56.1:11434

library:                               # new block
  palace: ~/.local/share/hypostasis/library/palace   # must not resolve under ~/.mempalace or ~/src/campaigns
  work_dir: ~/.local/share/hypostasis/library
  cache_dir: ~/.local/share/hypostasis/library/cache # optional
  source_root: "/mnt/g/My Drive/DriveThru/Dungeon Masters Guild"
  selection:                           # exactly one of the three forms
    product_types: [adventure, setting, gm_aid]
    # book_ids: [2443, 2475]
    # all_converted: true
  exclude_book_ids: []                 # optional
```

**Rules**

- A missing `library:` block, or a missing `selection`, gives exit 3.
- A `selection` that uses more than one form also gives exit 3, with a message naming the forms found.
- Paths are expanded with `~` and resolved before the live-palace guard checks them.
- `rpg_library_db` is read from the file's existing top-level key of that name.
- The default locations shown above are a suggestion for hypostasis to adopt. CG has no defaults of its own and never falls back to them.
