# Aborted attempt 1 — chapter arm

Killed ~30s in, before any response was returned or saved. No model output
exists for it and nothing was preserved beyond the `running` stub in
`chapter-attempt-01-run.json`.

Reason: the adapter's startup banner read

    claude-code run: model=claude-fable-5-1 effort=inherited from your
    ~/.claude/settings.json (CampaignGenerator sent no override) thinking=on (always)

which, if true, would have run at the operator's pinned `effortLevel: xhigh`
rather than the medium this experiment is about. It was killed on that reading.

The banner was wrong. `ClaudeCodeRunIdentity.banner()` branches on
`source` for the three known values `explicit` / `environment` / `clamp` and
falls through to the "inherited / sent no override" wording for anything else —
including a caller-supplied `source="cli"`, which is what the archived Codex
experiments passed and what attempt 1 passed. `override_sent` was True and
`--effort medium` was in fact on the command line. Confirmed on a one-word call:
the banner said "inherited" while `last_run_identity.as_dict()` returned
`{'claude_code_effort': 'medium', 'claude_code_effort_source': 'cli',
'claude_code_effort_override': True}`.

Attempt 2 passes `source="explicit"` so the printed banner and the recorded
identity agree. That is the only reason for the change; the command line sent
to `claude -p` is identical either way.

Also fixed before attempt 2: the chapter arm's heading check counted the `#`
chapter title alongside the five `##` section headings and would have rejected
a correct response. It now uses the same `^## ` match the archived chapter
experiment used.
