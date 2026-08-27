# Contract: Consistency Skills

## Canonical sources and delivery boundary

The installed paths below are symlinks and are not independent sources:

```text
/home/kroussos/.codex/skills/consistency-check
/home/kroussos/.codex/skills/staged-consistency
```

Edit their canonical source files instead:

```text
/home/kroussos/src/mytools/dotfiles/codex/skills/consistency-check/SKILL.md
/home/kroussos/src/mytools/dotfiles/codex/skills/staged-consistency/SKILL.md
```

These files are outside the CampaignGenerator worktree and currently belong to a
separate, untracked dotfiles delivery unit. Their changes require separate
tracking/commit or explicit operator delivery. CampaignGenerator tests must not
depend on either absolute home path.

## `consistency-check` behavior

- Replace its hard-coded `--backend claude-code` invocation with
  `--backend codex-cli`.
- Include `codex-cli` in its backend guidance and explain that it uses the saved
  ChatGPT subscription login, not an API key.
- Preserve the existing document/context selection, generated report path,
  issue-by-issue conversation, and explicit approval before applying fixes.
- Surface missing login, incompatible model, and timeout diagnostics from the CLI
  without silently retrying another backend.
- Do not add a Batch API path.

## `staged-consistency` behavior

- Continue delegating the relevant boundary checks to `consistency-check`.
- Update compatibility prose that currently assumes Claude Code so it names the
  Codex subscription backend.
- Preserve existing phase ordering, human checkpoints, and HTML batch-review
  workflow; the backend change does not combine or automate review stages.

## Acceptance

Resolve both installed symlinks to confirm the canonical files are active, then
manually invoke each skill against a safe test session with an authenticated Codex
CLI. Confirm that:

1. the displayed command uses `--backend codex-cli`;
2. the audit report is produced through the CampaignGenerator CLI;
3. findings enter the same conversational review flow;
4. no correction is applied without explicit approval; and
5. the staged skill retains its existing boundary order and HTML review behavior.

Where practical, run this acceptance with the CampaignGenerator subprocess seam
mocked first. A final live invocation is intentional because it consumes
subscription capacity.
