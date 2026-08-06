"""Client factory and the live API call surface (streaming, non-streaming, tools)."""

import os
import sys

from .backends import _OpenAICompatClient, _OpenRouterClient, _ClaudeCodeClient
from ..wiring import wiring_get

# Clients that accept the DGX-style `thinking` request extra (mapped per-backend
# to the right knob: enable_thinking for vLLM, `reasoning` for OpenRouter,
# MAX_THINKING_TOKENS for the `claude -p` subprocess). The real Anthropic SDK
# would reject it, so it is only forwarded to these.
_THINKING_EXTRA_CLIENTS = (_OpenAICompatClient, _OpenRouterClient, _ClaudeCodeClient)


def _require_nonempty(text: str) -> str:
    """Guard against a silently-empty model response (Constitution Principle I).

    A reasoning model can spend its entire token budget on a thinking trace and
    return empty content — which would otherwise be written to disk as a valid
    (but empty) extraction/synthesis artifact. Fail loudly instead so the caller
    aborts before persisting anything.
    """
    if text is None or not text.strip():
        raise RuntimeError(
            "model returned empty output (no content). On a reasoning model this "
            "usually means the token budget was spent on a thinking trace — disable "
            "thinking (DGX_NO_THINKING=1 / OPENROUTER_NO_THINKING=1; the claude-code "
            "backend disables it by default unless CG_CLAUDE_CODE_THINKING is set) "
            "or raise max_tokens."
        )
    return text


def make_client(endpoint: str | None = None, model_override: str | None = None,
                backend: str | None = None):
    """Return an LLM client.

    Default: an Anthropic client (existing behaviour).

    When `endpoint` (or the DGX_ENDPOINT env var) is set, returns a thin adapter
    that points at an OpenAI-compatible server — e.g. vLLM serving Qwen on the
    DGX Spark — and presents the small subset of the anthropic SDK surface that
    stream_api / call_api use. `model_override` (or DGX_MODEL env var) controls
    which model name is sent to that server; defaults to Qwen 2.5 14B AWQ.

    When `backend` (or the CG_BACKEND env var) is "claude-code", returns an
    adapter that routes generation through the `claude` CLI in headless mode,
    billing the Pro/Max subscription instead of the metered API. An explicit
    backend takes precedence over the DGX endpoint.

    An explicit `backend="dgx"` resolves its endpoint from the argument, then
    DGX_ENDPOINT, then the mneme-rendered `dgx_endpoint` wiring — and raises if
    none of those name a box. It does NOT quietly become an Anthropic client:
    asking for the local model and silently getting the metered API is the exact
    "obscured swap-back" this docstring forbids, and it bills real money while
    reporting a local run.

    No fallback if the local endpoint is unreachable — the choice is explicit,
    and an obscured swap-back to Anthropic would defeat the point of pointing
    at the DGX in the first place.
    """
    backend = backend or os.environ.get("CG_BACKEND")
    if backend == "claude-code":
        return _ClaudeCodeClient(model_override=model_override)
    if backend == "openrouter":
        return _OpenRouterClient(model_override=model_override)
    if backend == "dgx":
        # Resolved HERE rather than at each call site. Four callers
        # (extract_facts, narrate_chapter, scene_editor, platform_config_service)
        # each re-derived this line; every CLI that did not — enhance_summary and
        # so sd_agent among them — fell through to Anthropic with --backend dgx
        # set, spending metered tokens on a run the GM had asked to keep local.
        endpoint = (endpoint or os.environ.get("DGX_ENDPOINT")
                    or wiring_get("dgx_endpoint"))
        if not endpoint:
            raise SystemExit(
                "--backend dgx: no endpoint. Pass --endpoint, set DGX_ENDPOINT, "
                "or render `dgx_endpoint` into config/wiring.yaml. Refusing to "
                "fall back to the Anthropic API — you asked for the local box."
            )
        return _OpenAICompatClient(endpoint, model_override=model_override)
    endpoint = endpoint or os.environ.get("DGX_ENDPOINT")
    if endpoint:
        return _OpenAICompatClient(endpoint, model_override=model_override)
    try:
        import anthropic
    except ImportError:
        print("Error: anthropic not installed. Run: pip install anthropic", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic()


def add_backend_args(parser, default_backend: str | None = "anthropic") -> None:
    """Register the uniform --backend/--endpoint selection on a CLI.

    Shared so every LLM-bearing script speaks the same backend vocabulary
    (Constitution Principle V). ``default_backend`` lets a script whose
    endpoint always resolves to a real DGX URL (e.g. extract_facts.py, which
    never falls through to Anthropic today) default to "dgx" instead of
    silently changing behaviour when it adopts this seam — see
    client_from_args for the backward-compatibility contract.

    ``default_backend=None`` is for a CLI where the *presence* of --backend is
    the GM's opt-in to token spend, so the flag has to stay falsy when omitted
    (grounding_sections.py: "an LLM section never spends tokens implicitly — a
    build without --backend is a deterministic-only build by definition"). Any
    non-None default would make that guard always-true and start rendering LLM
    sections unasked. client_from_args already treats None the same as
    "anthropic", so the resolved client is unchanged either way.
    """
    _default_note = (
        "no default — omitting it skips every LLM section"
        if default_backend is None else f"default: {default_backend}"
    )
    parser.add_argument(
        "--backend", choices=["anthropic", "dgx", "openrouter", "claude-code"],
        default=default_backend,
        help=f"LLM backend ({_default_note}). 'dgx'/'openrouter'/'claude-code' route "
             "through the campaignlib seam; with no flag, behaviour is unchanged.")
    parser.add_argument(
        "--endpoint", default=None, metavar="URL",
        help="OpenAI-compatible endpoint for --backend dgx (OpenRouter uses its own base URL).")
    parser.add_argument(
        "--batch", action="store_true", default=False,
        help="Process Claude API calls through the Message Batches API (50%% "
             "token cost, asynchronous; blocks and polls until complete). "
             "Anthropic backend only. Unrelated to ensemble_batch (local "
             "dispatch).")


def client_from_args(args, *, endpoint: str | None = None):
    """Build a client from parsed --backend/--endpoint/--model args.

    Backward-compatible: with the default ``--backend anthropic`` and no
    ``--endpoint``, this resolves to ``make_client()`` exactly — env vars
    (CG_BACKEND / DGX_ENDPOINT) still apply, so existing invocations are
    byte-for-byte unchanged. For dgx/openrouter the chosen ``--model`` becomes the
    seam's model override.

    ``endpoint`` — explicit override that wins over ``args.endpoint``, for
    callers that resolve a specific endpoint from a fan-out pool at call time
    (e.g. facts_to_state.py's per-thread worker, one client per DGX box).

    Fails fast (``SystemExit``, before any client construction or token
    spend) when ``args.batch`` is set and the resolved backend isn't
    anthropic — mirrors make_client's own ``backend or CG_BACKEND`` env
    precedence so ``--backend anthropic`` (the default) plus
    ``CG_BACKEND=openrouter`` is caught too, not just an explicit
    ``--backend``.
    """
    if getattr(args, "batch", False):
        arg_backend = getattr(args, "backend", "anthropic")
        resolved_backend = (
            arg_backend if arg_backend != "anthropic"
            else (os.environ.get("CG_BACKEND") or "anthropic")
        )
        if resolved_backend != "anthropic":
            raise SystemExit(
                "--batch requires the Claude API backend (--backend anthropic); "
                f"backend '{resolved_backend}' has no batch support"
            )
    backend = None if getattr(args, "backend", "anthropic") == "anthropic" else args.backend
    model_override = getattr(args, "model", None) if backend in ("dgx", "openrouter", "claude-code") else None
    resolved_endpoint = endpoint if endpoint is not None else getattr(args, "endpoint", None)
    return make_client(backend=backend, endpoint=resolved_endpoint,
                       model_override=model_override)


def _is_retryable(exc) -> bool:
    """Return True for transient API errors that are worth retrying."""
    try:
        import anthropic
        if isinstance(exc, (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        )):
            return True
        if isinstance(exc, anthropic.APIStatusError) and exc.status_code == 529:
            return True  # overloaded_error
    except ImportError:
        pass
    try:
        # The DGX/vLLM path goes through the openai SDK, whose exceptions are
        # distinct from anthropic's and wrap the underlying httpx error as
        # __cause__ (so the httpx isinstance check below does NOT catch them).
        # Without this branch a single transient blip kills a 20-min local run.
        import openai
        if isinstance(exc, (
            openai.RateLimitError,
            openai.InternalServerError,
            openai.APIConnectionError,   # APITimeoutError subclasses this
            openai.APITimeoutError,
        )):
            return True
        if isinstance(exc, openai.APIStatusError) and exc.status_code in (500, 502, 503, 529):
            return True
    except ImportError:
        pass
    try:
        import httpx
        if isinstance(exc, (
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.TimeoutException,
        )):
            return True
    except ImportError:
        pass
    return False


def call_api(client, system: str, content, model: str, max_tokens: int = 8096,
             thinking: bool | None = None) -> str:
    """Non-streaming API call. Returns full response text.

    content — a string or a list of content blocks (for multimodal/vision calls).
    thinking — per-call reasoning intent for the DGX backend (None = the model's
    registry default) and the claude-code backend (None = off; see
    `_claude_code_thinking`). Ignored for the real Anthropic backend, which
    never enables thinking.
    Retries on transient errors (rate limit, overload, connection) with exponential backoff.
    """
    import time
    messages = [{"role": "user", "content": content}]
    # `thinking` is a local/OpenRouter knob; the real Anthropic SDK would reject it.
    extra = {"thinking": thinking} if isinstance(client, _THINKING_EXTRA_CLIENTS) else {}
    delays = [10, 20, 40]
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [API unavailable — waiting {delay}s before retry {attempt}/{len(delays)}...]",
                  flush=True)
            time.sleep(delay)
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                **extra,
            )
            return _require_nonempty(response.content[0].text)
        except Exception as e:
            if _is_retryable(e) and attempt < len(delays):
                continue
            raise


def call_api_with_tools(client, *, system: str, messages: list, tools: list,
                        model: str, max_tokens: int = 8192):
    """Non-streaming tool-use API call. Returns the raw Message response.

    Caller is responsible for the loop, message history, and dispatching
    tool_use blocks. Caller needs response.content (list of blocks),
    response.stop_reason, response.usage.

    Retries on transient errors (rate limit, overload, connection) with
    exponential backoff — same behaviour as call_api / stream_api.
    """
    import time
    delays = [10, 20, 40]
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [API unavailable — waiting {delay}s before retry {attempt}/{len(delays)}...]",
                  flush=True)
            time.sleep(delay)
        try:
            return client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools,
            )
        except Exception as e:
            if _is_retryable(e) and attempt < len(delays):
                continue
            raise


def stream_api(client, system, user: str, model: str, max_tokens: int = 8096,
               silent: bool = False, verbose: bool = False,
               cache_system: bool = False, thinking: bool | None = None) -> str:
    """Stream a Claude API call, printing each token as it arrives. Returns full response.

    Retries on transient errors (rate limit, overload, connection) with exponential backoff
    (up to 4 attempts). Pass silent=True to suppress all output (useful for
    filter/classification passes). Pass verbose=True to print the system and user prompts
    before calling.

    system — string, or a pre-built list of content blocks (for callers that want to
             control caching breakpoints precisely).
    cache_system — when True and `system` is a string, wrap it in a single
             cache_control: ephemeral block so subsequent calls with the same prefix
             get the prompt-cache discount. Useful when a large fixed context (e.g.
             a full VTT transcript) is reused across many short calls.
    """
    if verbose:
        print("\n" + "▲" * 60)
        print("SYSTEM PROMPT:")
        print(system if isinstance(system, str) else _render_system_blocks_for_log(system))
        print("─" * 60)
        print("USER PROMPT:")
        print(user)
        print("▲" * 60 + "\n")
    import time

    if cache_system and isinstance(system, str):
        system_arg = [{"type": "text", "text": system,
                       "cache_control": {"type": "ephemeral"}}]
    else:
        system_arg = system

    # `thinking` is a local/OpenRouter knob; the real Anthropic SDK would reject it.
    extra = {"thinking": thinking} if isinstance(client, _THINKING_EXTRA_CLIENTS) else {}
    delays = [60, 120, 240]  # seconds to wait before each retry
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [API unavailable — waiting {delay}s before retry {attempt}/{len(delays)}...]",
                  flush=True)
            time.sleep(delay)
        try:
            chunks = []
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system_arg,
                messages=[{"role": "user", "content": user}],
                **extra,
            ) as stream:
                for text in stream.text_stream:
                    if not silent:
                        print(text, end="", flush=True)
                    chunks.append(text)
                # Only the real anthropic SDK stream exposes get_final_message() —
                # the DGX/openrouter (_OpenAICompatStream) and claude-code
                # (_ClaudeCodeStream) façades in campaignlib/api/backends.py do
                # not, and must not break on this defensive check.
                get_final = getattr(stream, "get_final_message", None)
                if callable(get_final):
                    final = get_final()
                    if getattr(final, "stop_reason", None) == "max_tokens":
                        print(f"\n{'!' * 70}\n"
                              f"!!  WARNING: output TRUNCATED at the {max_tokens}-token max_tokens\n"
                              f"!!  ceiling (stop_reason=max_tokens). The tail of the response is\n"
                              f"!!  MISSING. Re-run with a higher max_tokens ceiling.\n"
                              f"{'!' * 70}", file=sys.stderr, flush=True)
            if not silent:
                print()
            return _require_nonempty("".join(chunks))
        except Exception as e:
            if _is_retryable(e) and attempt < len(delays):
                continue
            raise


def _render_system_blocks_for_log(blocks) -> str:
    if not isinstance(blocks, list):
        return str(blocks)
    parts = []
    for b in blocks:
        if isinstance(b, dict) and "text" in b:
            cache = " [cached]" if b.get("cache_control") else ""
            parts.append(f"<block{cache}>\n{b['text']}\n</block>")
        else:
            parts.append(str(b))
    return "\n".join(parts)
