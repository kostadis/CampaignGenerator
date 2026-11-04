# Terra medium entity-reference trial

Runs the frozen real-summary entity-reference fixture with `gpt-6.1-terra` at medium effort through CampaignGenerator's Codex CLI adapter. See [FINDINGS.md](FINDINGS.md) for results.

The task, marked target spans, system message, prompts, and hidden expectations are identical to the final Sol medium trial. Both context and words-only arms were run once; no prompt tuning or response repair was performed. Answers are experimental proposals, with no canonical registry writes.

Private runtime: `/tmp/orc-identity-terra-medium-20261104`. Raw passages and responses remain there. Compact results omit model-generated explanation fields.

To reproduce scoring after generation:

```sh
python experiments/20261104-terra-entity-resolution/compare_terra.py \
  --baseline /tmp/orc-identity-real-20261103-marked \
  --terra /tmp/orc-identity-terra-medium-20261104 \
  --local-comparison /tmp/orc-identity-local-comparison-20261104.json \
  --out /tmp/orc-identity-terra-comparison-20261104.json
```

The shared generation command is `experiments/20261103-summary-entity-resolution/run_models.py --run /tmp/orc-identity-terra-medium-20261104 --model gpt-6.1-terra --effort medium`, after preparing the same frozen inputs. Existing matching responses are reused.
