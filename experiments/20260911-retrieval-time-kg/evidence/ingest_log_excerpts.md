# Ingest log excerpts — evidence for FINDINGS.md

Full logs were multi-megabyte and are not copied. Counts and representative lines below.
Original paths: /home/kostadis/cognee-local/*.log

## ingest_toee.spark1-unbounded.log  (7206793 bytes)

```
APITimeoutError count:            493
auto-rate-limit activations:      6
RememberResult lines:             0
sample: timeout value=1800.0, time taken=5401.29 seconds
sample: timeout value=1800.0, time taken=5401.2 seconds
limiter: Potential RPM issues detected (Timeout) — slowing down processing to accommodate: enabling the RPM limiter (60 requests per 60s) for the next 900s, extended while issues persist.
```

## ingest_toee.spark1-bounded-thinking-on.log  (325872 bytes)

```
APITimeoutError count:            14
auto-rate-limit activations:      0
RememberResult lines:             0
sample: timeout value=600.0, time taken=1801.36 seconds
sample: timeout value=600.0, time taken=1801.33 seconds
```

## ingest_toee.log  (1062265 bytes)

```
APITimeoutError count:            0
auto-rate-limit activations:      0
RememberResult lines:             1
```

## ingest_tiered.log  (2859947 bytes)

```
APITimeoutError count:            0
auto-rate-limit activations:      0
RememberResult lines:             5
result: ### tier 'play_record' DONE in 2242.8s
result: ### tier 'module_canon' DONE in 3380.2s
result: ### tier 'curated_state' DONE in 1521.4s
result: ### tier 'prep_plan' DONE in 175.3s
result: ### tier 'superseded' DONE in 406.2s
```

## ingest_entity.log  (2230974 bytes)

```
APITimeoutError count:            0
auto-rate-limit activations:      0
RememberResult lines:             1
```
