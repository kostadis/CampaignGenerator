"""Anthropic Message Batches orchestration: build / submit / poll / collect."""

import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .client import _is_retryable


# ── Batch API ─────────────────────────────────────────────────────────────────
#
# Anthropic's Message Batches API charges 50% of list price for any request
# that completes within its 24-hour SLA, and honours prompt caching the same
# way live calls do. Our session-prep workflow has a human review step after
# each LLM stage, so giving up live token streaming in exchange for the 50%
# discount is a clean trade — but only when the user explicitly asks (`--batch`).
#
# The helpers below are pure orchestration: they don't know what the prompts
# are, just how to build a Request, submit a batch, poll for completion, and
# stream the results back. Prompt assembly stays in the calling script.


def build_batch_request(
    *,
    custom_id: str,
    system: str,
    user: str | list,
    model: str,
    max_tokens: int = 8192,
    cache_system: bool = False,
) -> dict:
    """Build one Request entry for `client.messages.batches.create(requests=...)`.

    Mirrors the system/messages shape `stream_api` constructs, including the
    optional `cache_control: ephemeral` block on the system prompt so the
    cache breakpoint is identical between live and batched paths.

    user — a string (unchanged behavior, byte-identical payload) or a list of
    content blocks (e.g. an image block + a text block for a vision payload,
    mirroring call_api's `content` parameter). A list is used directly as the
    user message content — no transformation.
    """
    if cache_system:
        system_arg = [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }]
    else:
        system_arg = system

    return {
        "custom_id": custom_id,
        "params": {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_arg,
            "messages": [{"role": "user", "content": user}],
        },
    }


def submit_batch(client, requests: list[dict]) -> str:
    """Submit `requests` as a single Message Batch. Returns the batch ID.

    Retries on transient errors using the same predicate as the streaming path.
    """
    if not requests:
        raise ValueError("submit_batch: requests list is empty")
    delays = [10, 20, 40]
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [Batch submit unavailable — waiting {delay}s before retry "
                  f"{attempt}/{len(delays)}...]", flush=True)
            time.sleep(delay)
        try:
            batch = client.messages.batches.create(requests=requests)
            return batch.id
        except Exception as e:
            if _is_retryable(e) and attempt < len(delays):
                continue
            raise


def poll_batch(client, batch_id: str, *, interval: int = 10, on_tick=None,
               max_wait: int | None = None):
    """Poll until the batch's `processing_status == 'ended'`.

    `on_tick(batch)` is called after each retrieve so the caller can print
    progress (`batch.request_counts.processing/succeeded/errored/...`).
    Returns the final batch object.

    Retries transient retrieve errors. `max_wait` is in seconds; None means
    wait up to the API's 24-hour SLA.
    """
    waited = 0
    delays = [10, 20, 40]
    while True:
        for attempt, delay in enumerate([-1] + delays):
            if delay >= 0:
                print(f"\n  [Batch retrieve unavailable — waiting {delay}s "
                      f"before retry {attempt}/{len(delays)}...]", flush=True)
                time.sleep(delay)
            try:
                batch = client.messages.batches.retrieve(batch_id)
                break
            except Exception as e:
                if _is_retryable(e) and attempt < len(delays):
                    continue
                raise
        if on_tick:
            try:
                on_tick(batch)
            except Exception:
                pass
        if getattr(batch, "processing_status", None) == "ended":
            return batch
        if max_wait is not None and waited >= max_wait:
            raise TimeoutError(
                f"Batch {batch_id} did not finish within {max_wait}s "
                f"(status: {batch.processing_status})"
            )
        time.sleep(interval)
        waited += interval


def collect_batch(client, batch_id: str) -> dict[str, dict]:
    """Stream the batch's results back into a dict keyed by `custom_id`.

    Each value: `{"status": "succeeded" | "errored" | "canceled" | "expired",
                  "text": str | None, "stop_reason": str | None,
                  "error": str | None, "usage": dict | None}`.

    `text` and `stop_reason` are populated only for succeeded results (a
    `stop_reason` of "max_tokens" flags a truncated response). The caller is
    responsible for deciding what to do with non-succeeded entries (typically:
    print the error message and let the user re-run; sidecar files stay on
    disk so a subsequent `--collect` can retry).
    """
    delays = [10, 20, 40]
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [Batch results unavailable — waiting {delay}s before retry "
                  f"{attempt}/{len(delays)}...]", flush=True)
            time.sleep(delay)
        try:
            stream = client.messages.batches.results(batch_id)
            break
        except Exception as e:
            if _is_retryable(e) and attempt < len(delays):
                continue
            raise

    out: dict[str, dict] = {}
    for entry in stream:
        custom_id = getattr(entry, "custom_id", None)
        result = getattr(entry, "result", None)
        if custom_id is None or result is None:
            continue
        result_type = getattr(result, "type", None)
        record: dict = {"status": result_type, "text": None,
                        "stop_reason": None, "error": None, "usage": None}
        if result_type == "succeeded":
            message = getattr(result, "message", None)
            if message is not None:
                blocks = getattr(message, "content", []) or []
                text_parts = [getattr(b, "text", "") for b in blocks
                              if getattr(b, "type", None) == "text"]
                record["text"] = "".join(text_parts)
                record["stop_reason"] = getattr(message, "stop_reason", None)
                usage = getattr(message, "usage", None)
                if usage is not None:
                    record["usage"] = {
                        "input_tokens": getattr(usage, "input_tokens", None),
                        "output_tokens": getattr(usage, "output_tokens", None),
                        "cache_creation_input_tokens":
                            getattr(usage, "cache_creation_input_tokens", None),
                        "cache_read_input_tokens":
                            getattr(usage, "cache_read_input_tokens", None),
                    }
        elif result_type == "errored":
            err = getattr(result, "error", None)
            record["error"] = (
                getattr(getattr(err, "error", None), "message", None)
                or str(err)
            )
        else:
            record["error"] = f"result type: {result_type}"
        out[custom_id] = record
    return out


def run_batch(client, requests: list[dict], *, label: str = "",
              poll_interval: int = 10, on_tick=None) -> dict[str, dict]:
    """Blocking submit -> poll -> collect composition (FR-012).

    1. Prints `Batch submitted: <id> (<n> requests)` to stderr immediately
       after submission (FR-013) — the trail for a hard-killed wait.
       `label`, if given, is appended (`... [label]`) so concurrent callers'
       stderr output can be told apart; omitted entirely when empty.
    2. Installs SIGINT/SIGTERM handlers for the duration of the poll: either
       signal attempts `client.messages.batches.cancel(batch_id)`, reports
       the outcome, and raises SystemExit(1) (FR-009). Handlers are restored
       on return. SIGTERM matters because the web UI's abort (spec 002) is a
       graceful-then-force process-group kill — the graceful phase must
       trigger the cancel.
    3. Polls until `processing_status == "ended"`, printing a progress line
       from `request_counts` each tick unless `on_tick` overrides it (FR-007).
    4. After collection, every item with `stop_reason == "max_tokens"` gets
       the same loud truncation banner `stream_api` prints, naming the
       item's `custom_id` (FR-010).
    5. Returns every item (succeeded and failed) keyed by `custom_id` — never
       raises on a per-item failure (FR-008); only the caller knows the
       unit<->file mapping needed to write successes and report failures.

    Raises only on transport-level failure of submit/poll/collect after the
    seam's standard retries (`_is_retryable`).
    """
    n = len(requests)
    batch_id = submit_batch(client, requests)
    suffix = f" [{label}]" if label else ""
    print(f"Batch submitted: {batch_id} ({n} requests){suffix}",
          file=sys.stderr, flush=True)

    start = time.monotonic()
    max_tokens_by_id = {
        r.get("custom_id"): r.get("params", {}).get("max_tokens")
        for r in requests
    }

    def _default_tick(batch) -> None:
        counts = getattr(batch, "request_counts", None)
        processing = getattr(counts, "processing", 0) or 0 if counts else 0
        succeeded = getattr(counts, "succeeded", 0) or 0 if counts else 0
        errored = getattr(counts, "errored", 0) or 0 if counts else 0
        elapsed = int(time.monotonic() - start)
        print(f"[batch {batch_id}] processing: {processing} "
              f"succeeded: {succeeded} errored: {errored} "
              f"(elapsed {elapsed}s)", file=sys.stderr, flush=True)

    tick = on_tick or _default_tick

    def _handle_abort(signum, frame):
        try:
            cancelled = client.messages.batches.cancel(batch_id)
            status = getattr(cancelled, "processing_status", None) or "canceling"
        except Exception as e:
            status = f"failed: {e}"
        print(f"Abort received — requesting batch cancellation… status: {status}",
              file=sys.stderr, flush=True)
        raise SystemExit(1)

    prev_sigint = signal.getsignal(signal.SIGINT)
    prev_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _handle_abort)
    signal.signal(signal.SIGTERM, _handle_abort)
    try:
        poll_batch(client, batch_id, interval=poll_interval, on_tick=tick)
    finally:
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)

    results = collect_batch(client, batch_id)
    for custom_id, record in results.items():
        if record.get("stop_reason") == "max_tokens":
            mt = max_tokens_by_id.get(custom_id)
            mt_str = f"{mt}-token " if mt is not None else ""
            print(f"\n{'!' * 70}\n"
                  f"!!  WARNING: output TRUNCATED at the {mt_str}max_tokens\n"
                  f"!!  ceiling (stop_reason=max_tokens) for item '{custom_id}'. "
                  f"The tail of\n"
                  f"!!  the response is MISSING. Re-run with a higher max_tokens "
                  f"ceiling.\n"
                  f"{'!' * 70}", file=sys.stderr, flush=True)
    return results


def run_single_batch(client, *, system: str, user: str | list, model: str,
                     max_tokens: int = 8192, cache_system: bool = False) -> str:
    """One-request convenience wrapper over `run_batch` for single-call CLIs.

    Builds one Request (`custom_id="single"`), runs it through the full
    submit/poll/collect/abort/truncation machinery, and returns its text on
    success. Raises RuntimeError (including status + error) if the item did
    not succeed — callers of single-call CLIs don't have a unit<->file map
    to report partial failure against, so failure here is fatal.
    """
    request = build_batch_request(
        custom_id="single", system=system, user=user, model=model,
        max_tokens=max_tokens, cache_system=cache_system,
    )
    results = run_batch(client, [request])
    record = results["single"]
    if record["status"] != "succeeded":
        raise RuntimeError(
            f"batch item 'single' did not succeed: status={record['status']} "
            f"error={record.get('error')}"
        )
    return record["text"]


def write_batch_sidecar(path: Path, payload: dict) -> None:
    """Persist batch metadata (id, model, custom_ids, etc.) for later --collect."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def read_batch_sidecar(path: Path) -> dict:
    """Read a sidecar previously written by `write_batch_sidecar`."""
    if not path.exists():
        print(f"Error: batch sidecar not found: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_batch_progress(batch) -> str:
    """One-line summary like '[batch ... | 4/8 succeeded | 1 processing]'."""
    counts = getattr(batch, "request_counts", None)
    if counts is None:
        return f"[batch {batch.id} | status: {batch.processing_status}]"
    succeeded = getattr(counts, "succeeded", 0) or 0
    errored = getattr(counts, "errored", 0) or 0
    canceled = getattr(counts, "canceled", 0) or 0
    expired = getattr(counts, "expired", 0) or 0
    processing = getattr(counts, "processing", 0) or 0
    total = succeeded + errored + canceled + expired + processing
    parts = [f"[batch {batch.id}", f"{succeeded}/{total} succeeded"]
    if processing:
        parts.append(f"{processing} processing")
    if errored:
        parts.append(f"{errored} errored")
    if canceled:
        parts.append(f"{canceled} canceled")
    if expired:
        parts.append(f"{expired} expired")
    return " | ".join(parts) + "]"
