# Contract: installed resource resolution

This contract is for existing callers of `campaignlib.load_agent_prompt`, `campaignlib.load_repo_file`, package-local reviewer content, and command dispatch. It preserves existing campaign-facing names while removing source-checkout dependence.

## Agent prompt selection

`load_agent_prompt(name, base_dir=None, placeholders=None)` accepts a logical name without `.md`, including nested names such as `session_doc/narrate/base`.

1. The override is `<base_dir or CWD>/config/agents/<name>.md`.
2. If absent, the shipped default is the corresponding resource under `campaignlib/resources/agents/`.
3. If neither exists, raise `FileNotFoundError` with the logical name and both locations.
4. If `placeholders` is provided, preserve the current strict two-way placeholder check and substitution.
5. Cache by selected resource identity, not merely the logical name. The existing cache-clear helper remains available to tests.

The override's bytes win exactly when it exists, including after a non-editable install. A missing override is normal; a missing shipped default for a known prompt is a packaging defect.

## Other shipped file selection

`load_repo_file(path, base_dir=None)` retains the existing function name for callers, but its source is a shipped resource rather than a repo-root file.

- An existing explicit absolute path is read as selected.
- A missing explicit absolute path is an error naming that path; no basename recovery.
- For a relative `config/...` name, a `base_dir` ending in `config/` identifies its parent as the campaign root; check `<campaign root>/config/...` first. If no `base_dir` was supplied, check `<CWD>/config/...`. Then try the matching shipped resource. The packaged mapping keeps existing workspace-generated values such as `config/system_prompt.md` and `config/agents/lore_oracle.md` usable even when `prep --config` is run away from the campaign directory.
- A relative name outside the approved shipped namespace is not mapped by basename into the package. It resolves only where the operator selected it, or fails clearly.
- Traversal (`..`) cannot escape the shipped-resource namespace.

`find_default_config()` still requires `<cwd>/config/config.yaml`; the package does not provide an implicit campaign config.

## Package-local content and subprocesses

`session_doc.review.serve` reads `reviewer.html` as a packaged byte resource. Commands that launch another CampaignGenerator command use the active interpreter's module or console entry point, never a path inferred from the parent of a Python file. `new_workspace` prints portable installed commands and explicitly labels `./start` as a checkout-only web path.

## Distribution acceptance

The wheel includes the approved prompt tree, `config/system_prompt.md` logical equivalent, and `session_doc/review/reviewer.html`. A fresh non-editable install from the wheel must pass the imports and representative command help cases in the spec from an unrelated CWD. No test may rely on `PYTHONPATH` pointing at the checkout.
