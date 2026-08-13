# The genre rulebook — how to actually use it

The genre rulebook is the file that tells Pass 5 what your campaign's prose *is*: tense, POV,
register, stock phrases, banned tics, per-narrator bookkeeping caps. It is one file per
campaign, conventionally `<campaign>/voice/_genre.md`, and **it is the single source of truth**
(#276 fix 2).

Read this to point a campaign at its rulebook, to migrate a campaign that predates the change,
or to work out why a render came out sounding generic. The design rationale is in
[`docs/design/GenreRulebook_implementation.md`](../design/GenreRulebook_implementation.md).

## What changed, and why you should care

`narrate.genre` in `session_doc.yaml` used to hold the rulebook's **text**, pasted. So did
`profiles[].knobs.narration_genre`. Three copies of one document, no divergence check, and the
only sync ran one way.

That is not a theoretical complaint. Editing `voice/_genre.md` did nothing, because the paste
is what the renderer read. out-of-the-abyss' paste had lost every newline, so the campaign with
the biggest rulebook got it as a single-line label. Phandalin's rulebook says "first-person
present tense, always" and **59 of its 62 rendered scenes are in past tense** — the rule was
there the whole time and was not arriving (campaigns#163).

Now there is one copy, it is the file, and `narrate.genre` no longer exists.

**The trade you accept:** there is no fallback. A wrong path means Pass 5 runs with **no** genre
directive — no register rules, no banned-tic list, no bookkeeping caps. The tools say so loudly
in three places, listed under [Troubleshooting](#troubleshooting).

## Step 0 — migrate a campaign that predates the change

Do this **once per campaign**, before the next render. Until you do, that campaign's stale
`narrate.genre` is loaded, announced on stderr, and ignored.

```bash
python -m server.migrate_narrate_genre --campaign-dir ~/src/campaigns/<name>
```

It relocates the paste to `paths.genre_file`, deletes `narrate.genre`, rewrites any
`profiles[].knobs.narration_genre` to `narration_genre_file`, and writes `voice/_genre.md` if no
file exists yet. A clean run looks like this:

```
migrated the genre rulebook to a file
  session_doc.yaml:  …/Phandalin/config/session_doc.yaml
  canonical copy:    file (identical to the paste)
  rulebook:          …/Phandalin/voice/_genre.md  (7351 chars / 61 lines)  [unchanged]
  paths.genre_file:  voice/_genre.md
  narrate.genre:     deleted (7351 chars / 61 lines)
  profiles rewritten: 1 (narration_genre -> narration_genre_file)
```

Useful flags:

| Flag | Use |
|---|---|
| `--genre-file PATH` | Target other than `voice/_genre.md`, relative to the campaign dir |
| `--prefer-file` | On a disagreement, keep the file and discard the paste |
| `--prefer-yaml` | On a disagreement, overwrite the file with the paste |
| `--drop-profile-genre` | Discard a profile's divergent genre text instead of refusing |
| `--config-dir DIR` | Config subdirectory, default `config` |

It is safe to re-run. A second run reports `nothing to migrate — paths.genre_file is already
set to …` and changes nothing.

### When it refuses — this is the interesting part

The CLI stops rather than guessing whenever the answer is about *content*. Two refusals exist.

**The paste and the file disagree.** Exit code 1, nothing written:

```
REFUSING to guess: narrate.genre and voice/_genre.md disagree.
  narrate.genre:  16303 chars / 1 lines
  voice/_genre.md:  16339 chars / 88 lines
  similarity (whitespace-normalised): 0.9989

Which copy is the real rulebook is a content decision, not a merge.
Look at the difference, then re-run with one of:
  --prefer-file   keep the file, discard the YAML paste
  --prefer-yaml   overwrite the file with the YAML paste

What differs (words, not lines — the paste has no line structure):
  after “”:
    only in the file:  “# Out of the Abyss Narration Genre”
```

Read the word list, then pick a flag. It reports **words, not lines**, because a flattened
paste is a single line and a line diff would just print the whole document at you. In the real
example above the entire difference is the file's title, so `--prefer-file` is obviously right —
which is the point of showing it that way.

**A profile's genre text differs from the canonical rulebook.** Exit 1, nothing written. That
profile wanted a *different* rulebook, and a profile now holds a path, so it needs its own
file — which the migration cannot write for you. Either:

1. write it (say `voice/_genre_grimdark.md`), re-run, then set that profile's
   `narration_genre_file` knob by hand; or
2. re-run with `--drop-profile-genre` to discard the text and let the profile inherit the
   campaign rulebook. The output names every profile it discarded from.

**What is *not* a refusal:** a paste that merely lost its newlines. The comparison ignores
whitespace, so a flattened copy of the same document migrates silently — it is the same
rulebook, badly stored. If the CLI wrote the file from a flattened paste it warns, because the
file is meant to be read by a human even though the render is unaffected.

## Step 1 — point a campaign at its rulebook

Already-migrated campaigns are done. For a new campaign, write `voice/_genre.md` and set the
path.

**In the UI:** Session Doc Editor → Config drawer → ④ Narrate → *Narration genre file*. Type a
path relative to the campaign directory. The status line tells you what happened:

```
✓ resolved · 88 lines · 16,340 chars      the file was read
✗ file not found — Pass 5 will run with   the path is wrong, or the file is not there
  no genre directive
No genre file — Pass 5 runs with no       nothing configured
  genre directive.
```

The preview below it is **read-only**. That is deliberate: a browser field is what flattened
out-of-the-abyss' 88 lines into one (#249). Edit the file in your editor; the drawer only
points at it.

**On the CLI:** pass the path directly. This works whether or not the campaign is migrated,
which makes it the quickest way to test a rulebook edit:

```bash
python -m session_doc.sd_narrate <recap> \
  --plan <narration>/plan.md \
  --scene-extractions <session>/scene_extractions_smoothed \
  --per-scene-output /tmp/try \
  --party docs/party.md --party-config config/party.yaml \
  --voice-dir voice --examples examples \
  --characters "Brewbarry, Soma, Valphine, Vukradin" \
  --narration-genre-file voice/_genre.md \
  --prose-mode --narrate-tokens 16000 --scene 4 \
  --model claude-fable-5 --backend claude-code
```

## Step 2 — confirm the rulebook actually arrived

Two ways, both free.

**Before a render**, check the prompt itself. A short directive gets an inline `GENRE:` label; a
document gets its own delimited block, and anything over 200 characters counts as a document
regardless of whether it has newlines (#276 fix 1):

```bash
python - <<'PY'
import sys; sys.path.insert(0, ".")
import session_doc
from session_doc.sd_narrate import _load_genre_file
g = _load_genre_file("/home/kroussos/src/campaigns/Phandalin/voice/_genre.md")
p = session_doc.build_narrate_system(examples_text=None, genre=g)
print(f"{len(g)} chars, {g.count(chr(10))} newlines")
print("delimited block:", "GENRE & REGISTER (campaign-specific) — BEGIN" in p)
print("tail reminder:", p.count("GENRE — FINAL REMINDER"))
PY
```

**After a render**, read the run record. Each scene's `.knobs.json` names the rulebook by path
and by content digest:

```json
{ "narration_genre_file": "…/voice/_genre.md",
  "narration_genre_sha": "a1b2c3d4e5f6",
  "narration_genre_lines": 61 }
```

Two scenes used the same rulebook if and only if the digests match. A differing digest on the
same path means the file was edited between the two renders — which a path alone could never
have told you. If `narration_genre_sha` is absent, the file did not resolve and that scene has
no genre rules in it.

## Verifying a rulebook rule is really being followed

This is the trap that hid a broken rulebook for ten sessions, so it is worth stating as a
method.

out-of-the-abyss' rulebook says first-person **past**, and its renders are past — even though
its paste was flattened and the rulebook was arriving as an unreadable label. The output looked
correct because past tense is what the model does anyway.

> A rule that agrees with the model's default proves nothing about whether the rulebook is being
> read.

So when you want to know whether a rulebook is landing, **test a rule the model would not have
followed by accident.** Phandalin's present-tense requirement is that kind of rule, which is why
it was the one that exposed the bug — and why a tense count is a good smoke test there and a
worthless one in out-of-the-abyss.

## Things that will bite you

- **Migration is per campaign and is not automatic.** Shipping the code changed nothing on
  disk. An unmigrated campaign renders with no genre at all.
- **Editing the file makes the migration refuse.** Once the file differs from the stale paste,
  you need `--prefer-file`. That is correct behaviour, not a bug: the tool will not pick a copy
  for you.
- **A path typo is silent in the render itself.** It warns on stderr and in the drawer, but the
  narration is simply produced without register rules. If output suddenly reads generic, check
  the path before you blame the model.
- **`narrate.genre` is gone, not deprecated.** Writing it does nothing. It is stripped on load
  with a notice.
- **A profile holds a path now.** If you want a profile with its own register, give it its own
  file. Copying text into a profile knob is the shape that was deleted.
- **State a limit, not just a permission.** A rulebook line that says "em-dash for interrupted
  speech or thought" grants a use and forbids nothing, and the renderer will keep the device for
  everything else — measured at 8 of 17 uses in one scene (campaigns#158). The rules in these
  files that hold up are the ones phrased as limits: "Never drift into third person".
- **`/voice-critic` does not read your rulebook.** It carries its own hand-copied fork, which
  currently disagrees with the genre about em-dashes in both directions
  (kostadis/mytools#125). A critic finding is not automatically a rulebook violation.

## Troubleshooting

| Symptom | Meaning | Fix |
|---|---|---|
| `config: ignoring relocated session_doc.yaml narrate field(s) genre (N chars)` | The campaign is not migrated. That text is **not** reaching Pass 5. | Run the migration (Step 0) |
| `Warning: --narration-genre-file <p> does not exist. Pass 5 will run with NO genre directive` | Wrong path, or the file was moved | Fix the path, or drop the flag if intended |
| `Warning: --narration-genre-file <p> is empty` | The file exists and has no content | Write the rulebook |
| Drawer shows `✗ file not found` | Same as above, from the UI | Fix `paths.genre_file` |
| Drawer shows `No genre file` | Nothing configured | Set `paths.genre_file` |
| `REFUSING to guess: narrate.genre and <file> disagree` | Two copies, real content difference | Read the word diff, then `--prefer-file` or `--prefer-yaml` |
| `REFUSING to guess: these profiles carry genre text that differs` | A profile wanted its own rulebook | Give it a file, or `--drop-profile-genre` |
| `REFUSING: profiles carry genre text but there is no rulebook at <p>` | Nothing to seed a file from | Write the file first |
| `--prefer-file and --prefer-yaml are mutually exclusive` | Both flags passed | Pick one |
| `nothing to migrate — paths.genre_file is already set to …` | Already migrated | Nothing to do |
| Renders read generic, no warnings you noticed | Most likely an unmigrated campaign or a bad path | Check the drawer's status line, then a scene's `.knobs.json` for `narration_genre_sha` |
| The rulebook's rule is ignored but everything else looks right | The rule may never have arrived — or the rule agrees with the model's default and you cannot tell | Test with a rule that contradicts the default (see above) |

## Reference

- Config key: `paths.genre_file` in `<campaign>/config/session_doc.yaml`, campaign-relative.
- Profile knob: `narration_genre_file`.
- CLI flag: `sd_narrate --narration-genre-file PATH`.
- Inline-vs-block threshold: `session_doc/narrate.py::GENRE_INLINE_MAX_CHARS` (200).
- Migration: `python -m server.migrate_narrate_genre --campaign-dir DIR`.
- Run record keys: `narration_genre_file`, `narration_genre_sha`, `narration_genre_lines`.
- Tests: `tests/test_narrate_genre.py`, `tests/test_narrate_genre_file.py`,
  `tests/test_migrate_narrate_genre.py`, `tests/test_editor_config_genre_multiline.py`.
