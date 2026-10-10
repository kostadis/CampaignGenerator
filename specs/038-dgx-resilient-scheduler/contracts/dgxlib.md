# dgxlib Model Concurrency Contract

## Registry field

Each model entry may declare `max_concurrency: 8`.

- Type: integer greater than zero.
- Meaning: default maximum concurrent requests CampaignGenerator may place on each endpoint serving that model.
- Owner: dgxlib/dgx-fun model registry beside served-model configuration.
- `qwen3.8-flash-next` declares 8, matching served `max-num-seqs`.
- Absence means consumer fallback. Invalid presence is a configuration error and never silently falls back.

`resolve_model_config(model)` exposes `.max_concurrency` as `int | None` without changing existing timeout, thinking, or request-extra fields.

## CampaignGenerator resolution

```text
explicit --parallel N
  -> N, source=explicit
else backend == dgx and selected model declares max_concurrency
  -> declared value, source=dgxlib:<model>
else
  -> 6, source=fallback
```

Resolve after actual backend/model selection and before workers. Start line and run record expose value/source. Older registries remain usable through fallback 6. Tests use fake registry objects and require no live dgx checkout.
