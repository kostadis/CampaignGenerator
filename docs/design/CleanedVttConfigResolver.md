# Cleaned-VTT Config Resolver — Design Plan

**For:** Claude Code, working in `~/src/CampaignGenerator`.
**Status:** Plan only. No code changes yet.
**Related:** `/vtt-spell-pass` skill, per-campaign `config.yaml`, `notes/vtt_transcription_corrections.md` glossaries.

---

## TL;DR — what's broken

After `/vtt-spell-pass` produces a `*.cleaned.vtt` next to the raw `*.transcript.vtt`, downstream tools that build subprocess commands from the server layer don't reliably pick the cleaned file. Two distinct discovery paths exist and they can disagree silently:

- `server/routers/scene_editor.py:148-157` `_vtt_path()` sorts `sd.glob("*.vtt")` alphabetically — picks `*.cleaned.vtt` (because `cleaned` < `transcript`).
- `server/config.py:104-107` `derive_campaign_paths` uses unsorted `list(sd.glob("*.vtt"))[0]` — filesystem order, non-deterministic.

The UI form and the actual `scene_extract` / `enhance_summary` subprocess can therefore be reading different VTTs for the same session. When the raw is the one fed to the LLM, every Otter mishearing that spell-pass already fixed gets re-injected into quotes, narration, and the next pass's recap.

The user wants:
1. An explicit **config option** that lets a campaign declare "prefer the cleaned VTT for downstream tools."
2. An **error** when the cleaned file is required but missing, so silent drift becomes a visible failure.

Non-goals: no changes to the CLI scripts (`session_doc/scene_extract.py`, `session_doc/enhance_summary.py`, `session_doc/vtt_summary.py`, `session_doc/vtt_voice_compare.py`) — they take a positional VTT arg and are unaffected. Fix lives at the server layer that builds those subprocesses.

---

## Findings (current state)

- **Per-campaign `config.yaml`** has no VTT field. `documents:` is campaign-level only. See `/home/kroussos/campaigns/out-of-the-abyss/config.yaml:18-28` and `/home/kroussos/campaigns/Phandalin/config.yaml:14-24`.
- **VTT discovery is a glob in two places** that don't agree:
  - `server/routers/scene_editor.py:148-157` — honors `CONFIG["vtt"]` else `sorted(sd.glob("*.vtt"))[0]`. Used by Stage 1 (`enhance_summary`) build at `:383-394` and Stage 2 (`scene_extract`) build at `:415-427`.
  - `server/config.py:104-107` — `list(sd.glob("*.vtt"))[0]` (unsorted). Populates `vtt_input` and the UI form.
  - `pipelines/rlm/mcp_server.py:275` — `session.glob("*.vtt")` (display only; not part of the bug, but worth surfacing cleaned-vs-raw here for visibility).
- **CLI scripts take VTT as a positional arg**, no auto-detect: `session_doc/scene_extract.py:249`, `session_doc/enhance_summary.py:271`, `session_doc/vtt_summary.py:254`, `session_doc/vtt_voice_compare.py:150`. Bug surfaces through the server layer only.
- **Config loader**: `campaignlib.py:708-725` — flat `yaml.safe_load`, no schema. New keys just need to be read by callers.
- **Concrete repro on disk now**: `/home/kroussos/campaigns/out-of-the-abyss/summaries/20260518/` has both `GMT20260519-005755_Recording.transcript.cleaned.vtt` and `...transcript.vtt`. The two discovery paths disagree on which to use.

---

## Proposed config shape

Add a single top-level `vtt:` block to each per-campaign `config.yaml`. Per-session granularity isn't needed — the convention is stable across a campaign's sessions, and the existing `summaries/<date>/` layout already provides per-session scoping.

```yaml
vtt:
  prefer_cleaned: true          # default: true
  cleaned_suffix: .cleaned.vtt  # default
  raw_suffix: .transcript.vtt   # default
  require_cleaned: true         # if true, abort when raw exists but cleaned missing
```

Defaults are chosen so that:
- Campaigns that already run `/vtt-spell-pass` (Out of the Abyss, Phandalin) get the correct behavior out of the box.
- A campaign that hasn't adopted spell-pass can opt out with `require_cleaned: false` and keep working against raw VTTs.

`out-of-the-abyss/config.yaml` and `Phandalin/config.yaml` both gain the block above.

---

## Proposed resolver behavior

Replace the two ad-hoc globs with one helper:

```python
# server/config.py, alongside derive_campaign_paths

class MissingCleanedVTTError(RuntimeError): ...

def resolve_session_vtt(session_dir: Path, campaign_config: dict) -> Path:
    ...
```

Algorithm:

1. If `CONFIG["vtt"]` is an explicit path, use it; skip discovery. (Preserves current explicit-override behavior.)
2. List `sd.glob("*.vtt")`. Partition into `cleaned = [f for f in vtts if f.name.endswith(cleaned_suffix)]` and `raw = [f for f in vtts if f.name.endswith(raw_suffix)]`.
3. If `prefer_cleaned` and `cleaned`: return `cleaned[0]`.
4. If `prefer_cleaned` and `raw` and not `cleaned` and `require_cleaned`: **raise `MissingCleanedVTTError`**.
5. Else fall back to current behavior (sorted `vtts[0]`) — but **emit a stderr warning** when both exist and we picked raw, or when neither cleaned nor raw matches the configured suffixes.

Both call sites (`scene_editor._vtt_path()`, `derive_campaign_paths`) delegate to this helper so they cannot disagree.

---

## Proposed error

Fatal `MissingCleanedVTTError`. The server returns it as the `(None, msg)` tuple, matching the existing pattern at `scene_editor.py:384-385` and `:416-417` — the UI already surfaces that tuple to the user.

**Trigger:** `vtt.prefer_cleaned` is true AND a `*.transcript.vtt` exists in the session dir AND no `*.cleaned.vtt` exists next to it AND `require_cleaned` is true.

**Message text:**

> `Refusing to read raw VTT '<raw_path>' — no cleaned counterpart found. Run /vtt-spell-pass first, or set vtt.require_cleaned: false in config.yaml to allow the raw file.`

**Also:** a non-fatal warning (stderr, prefixed `[vtt]`) when both files exist and the resolver picked one, naming which file is actually being fed to the LLM. This catches the silent mismatch between `_vtt_path()` and `derive_campaign_paths` even after the resolver is unified — if a third call site ever bypasses the helper, the warning makes it visible.

No `--force` CLI flag is needed; the user can flip `require_cleaned: false` in YAML for a one-off.

---

## Step-by-step implementation

1. **`server/config.py`** — add `MissingCleanedVTTError` and `resolve_session_vtt(session_dir, campaign_config)` near line 104. Replace the inline `glob("*.vtt")[0]` block at `:105-107` with a call to it. Read the `vtt:` block from the loaded YAML (passed through whatever currently loads `config.yaml` into `CONFIG`).
2. **`server/routers/scene_editor.py:148-157`** — change `_vtt_path()` to delegate to the shared resolver. Catch `MissingCleanedVTTError` in `_build_enhance_cmd` / `_build_reextract_cmd` and return `(None, str(err))` so the existing tuple-error path at `:384-385` and `:416-417` carries the message to the UI.
3. **`pipelines/rlm/mcp_server.py:275`** *(optional cosmetic)* — surface "cleaned" vs "raw" in the `list_sessions` artifact tags so the MCP side also shows whether the cleaned pass has been done for each session.
4. **`/home/kroussos/campaigns/out-of-the-abyss/config.yaml`** — append the `vtt:` block shown above.
5. **`/home/kroussos/campaigns/Phandalin/config.yaml`** — same block.
6. **No CLI changes.** `session_doc/scene_extract.py`, `session_doc/enhance_summary.py`, `session_doc/vtt_summary.py`, `session_doc/vtt_voice_compare.py` keep their positional VTT arg.

---

## Verification recipe

In `/home/kroussos/campaigns/out-of-the-abyss/summaries/20260518/`:

1. Confirm both `*.cleaned.vtt` and `*.transcript.vtt` exist. Run the Scene Editor Stage 1 / Stage 2 from the UI. Stderr should include:
   ```
   [vtt] using cleaned: GMT20260519-005755_Recording.transcript.cleaned.vtt
   ```
2. `mv GMT20260519-005755_Recording.transcript.cleaned.vtt /tmp/` and re-run. The UI button should fail before any API call with:
   > `Refusing to read raw VTT '.../GMT20260519-005755_Recording.transcript.vtt' — no cleaned counterpart found. Run /vtt-spell-pass first, or set vtt.require_cleaned: false in config.yaml to allow the raw file.`
3. Restore the cleaned file. Set `require_cleaned: false` in `config.yaml`. Remove the cleaned file again. Re-run. Should succeed against the raw VTT with:
   ```
   [vtt] WARNING: falling back to raw transcript; cleaned pass not run for this session
   ```

---

## Critical files for implementation

- `/home/kroussos/src/CampaignGenerator/server/config.py`
- `/home/kroussos/src/CampaignGenerator/server/routers/scene_editor.py`
- `/home/kroussos/src/CampaignGenerator/campaignlib.py` (only if the YAML loader needs to surface the `vtt:` block through `CONFIG`)
- `/home/kroussos/campaigns/out-of-the-abyss/config.yaml`
- `/home/kroussos/campaigns/Phandalin/config.yaml`
- `/home/kroussos/src/CampaignGenerator/pipelines/rlm/mcp_server.py` (optional, for `list_sessions` visibility)
