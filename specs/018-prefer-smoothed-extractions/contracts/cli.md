# CLI Contract: Exact Scene Extraction Input

**Feature**: `018-prefer-smoothed-extractions` | **Command**: `sd_narrate`

## Additive option

```text
--scene-extraction-file FILE
```

Use one exact scene-extraction file for a single-scene Narrate run. This is an
override for the selected scene only; it does not replace the existing
`--scene-extractions DIR` option or change multi-scene behavior.

Canonical usage:

```bash
sd_narrate session-summary.md \
  --plan narration/plan.md \
  --scene-extractions scene_extractions_new \
  --scene-extraction-file scene_extractions_smoothed/03_scene_name.md \
  --per-scene-output narration \
  --scene 3
```

## Validation

The CLI MUST refuse before the first model call when any of these is true:

1. `--scene-extraction-file` is supplied without `--scene`.
2. `--scene` contains zero or more than one scene number when the exact-file
   option is supplied.
3. The file does not exist, is not a regular file, or cannot be read as UTF-8.
4. The file is not an eligible `NN_*.md` scene extraction under the shared
   `session_doc.io` rules.
5. The file cannot be associated with the selected plan scene by scene
   identity or its `NN_` prefix.

Every refusal names the option/file and the violated rule. No refusal may
silently fall back to the directory input.

## Selection behavior

For the sole selected scene:

1. A valid `--scene-extraction-file` is loaded and used directly.
2. Otherwise the existing directory behavior applies: match the plan scene by
   canonical name, then use the established directory fallback.

For all invocations without the new option, behavior is byte-for-byte
compatible at the command surface and semantically unchanged.

`--scene-extractions DIR` remains required. The UI command builder supplies:

| Active source | `--scene-extractions` | `--scene-extraction-file` |
|---|---|---|
| Smoothed, raw directory exists | configured raw directory | exact smoothed file |
| Smoothed, raw directory absent | smoothed file's directory | exact smoothed file |
| Raw fallback | configured raw directory | omitted |
| Missing or unreadable | no command is launched | no command is launched |

## Content and side-effect guarantees

- The exact file supplies the selected scene's moments/body/summary exactly as
  the ordinary loader would parse them.
- The exact file is included in session-source knowledge checks without being
  duplicated when it is already present in the directory load.
- Alias normalization remains in-memory only; source bytes are not rewritten.
- The option never copies, moves, renames, or writes the exact file.
- Output location and naming remain governed by `--per-scene-output` and the
  selected plan scene, not by the exact input filename.

## Help contract

`sd_narrate --help` describes the option as a single-scene input override and
states that exactly one `--scene N` is required. The spelling
`--scene-extraction-file` is the only accepted spelling.
