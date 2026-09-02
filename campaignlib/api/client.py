"""Client factory and the live API call surface (streaming, non-streaming, tools)."""

import argparse
import os
import sys
from dataclasses import dataclass

from .backends import (
    _OpenAICompatClient, _OpenRouterClient, _ClaudeCodeClient,
    _claude_code_always_thinking, _claude_code_thinking,
    claude_code_effort_conflict,
)
from .codex_cli import _CodexCliClient
from ..wiring import wiring_get
from ..selection import (
    BACKENDS,
    CLAUDE_CODE_EFFORTS,
    CODEX_REASONING_EFFORTS,
    ClaudeCodeEffort,
    CodexReasoningEffort,
    compatible,
)

# Clients that accept the DGX-style `thinking` request extra (mapped per-backend
# to the right knob: enable_thinking for vLLM, `reasoning` for OpenRouter,
# MAX_THINKING_TOKENS for the `claude -p` subprocess). The real Anthropic SDK
# would reject it, so it is only forwarded to these.
_THINKING_EXTRA_CLIENTS = (_OpenAICompatClient, _OpenRouterClient, _ClaudeCodeClient)
_KEYLESS_CLIENTS = (*_THINKING_EXTRA_CLIENTS, _CodexCliClient)


@dataclass(frozen=True)
class CLIModelIntent:
    """Resolved model value plus the provenance needed by CLI callers.

    ``argparse`` normally replaces an omitted option with its default, making
    an inherited Claude model indistinguishable from one explicitly supplied
    by the operator.  Keeping both values here lets Codex omit an inherited
    default while preserving the exact legacy default for every other
    backend.  ``requested_model`` is retained verbatim when non-empty; the
    resolver does not rewrite an explicit model id.
    """

    backend: str
    requested_model: str | None
    legacy_default: str | None
    effective_model: str | None
    explicit: bool


@dataclass(frozen=True)
class CLIReasoningIntent:
    """Resolved Codex reasoning effort with truthful provenance."""

    backend: str
    requested_effort: CodexReasoningEffort | None
    environment_effort: CodexReasoningEffort | None
    effective_effort: CodexReasoningEffort | None
    source: str
    emit_override: bool


@dataclass(frozen=True)
class ClaudeCodeEffortIntent:
    """Resolved claude-code effort with truthful provenance.

    The claude-code twin of CLIReasoningIntent. Deliberately a separate type
    with a separate vocabulary: `claude --effort` has no "minimal", and
    omission means something different on each backend (see
    specs/021-claude-code-effort/research.md R1).
    """

    backend: str
    requested_effort: ClaudeCodeEffort | None
    environment_effort: ClaudeCodeEffort | None
    effective_effort: ClaudeCodeEffort | None
    source: str
    emit_override: bool


def _effective_backend(args) -> str:
    arg_backend = getattr(args, "backend", "anthropic")
    if arg_backend and arg_backend != "anthropic":
        return arg_backend
    return os.environ.get("CG_BACKEND") or "anthropic"


def _valid_codex_effort(value, *, source: str) -> CodexReasoningEffort:
    if not isinstance(value, str) or not value or value.strip() != value:
        accepted = ", ".join(CODEX_REASONING_EFFORTS)
        raise ValueError(f"{source} must be one of: {accepted}")
    if value not in CODEX_REASONING_EFFORTS:
        accepted = ", ".join(CODEX_REASONING_EFFORTS)
        raise ValueError(f"{source} value {value!r} must be one of: {accepted}")
    return value


def resolve_cli_reasoning(args) -> CLIReasoningIntent:
    """Resolve explicit option, environment fallback, or Codex omission.

    Server-side ``ResolvedSelection`` objects expose an environment preview but
    intentionally set ``codex_reasoning_override`` false.  Treat that value as
    ambient so the in-process Connection Graph path retains ``environment``
    provenance instead of relabeling it as an explicit request.
    """
    backend = _effective_backend(args)
    requested = getattr(args, "codex_reasoning_effort", None)
    origin = getattr(args, "codex_reasoning_effort_origin", None)
    override = getattr(args, "codex_reasoning_override", None)
    if override is False and origin in {"environment", "omitted"}:
        requested = None

    if requested is not None:
        effort = _valid_codex_effort(
            requested, source="--codex-reasoning-effort"
        )
        if backend != "codex-cli":
            raise ValueError(
                "--codex-reasoning-effort applies only to --backend codex-cli; "
                f"effective backend is {backend!r}"
            )
        return CLIReasoningIntent(
            backend=backend,
            requested_effort=effort,
            environment_effort=None,
            effective_effort=effort,
            source="explicit",
            emit_override=True,
        )

    if backend != "codex-cli":
        return CLIReasoningIntent(
            backend=backend,
            requested_effort=None,
            environment_effort=None,
            effective_effort=None,
            source="omitted",
            emit_override=False,
        )

    raw_environment = os.environ.get("CG_CODEX_REASONING_EFFORT")
    if raw_environment is None or not raw_environment.strip():
        return CLIReasoningIntent(
            backend=backend,
            requested_effort=None,
            environment_effort=None,
            effective_effort=None,
            source="omitted",
            emit_override=False,
        )
    environment = _valid_codex_effort(
        raw_environment.strip(), source="CG_CODEX_REASONING_EFFORT"
    )
    return CLIReasoningIntent(
        backend=backend,
        requested_effort=None,
        environment_effort=environment,
        effective_effort=environment,
        source="environment",
        emit_override=True,
    )


def _valid_claude_code_effort(value, *, source: str) -> ClaudeCodeEffort:
    accepted = ", ".join(CLAUDE_CODE_EFFORTS)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{source} must be one of: {accepted}")
    if value not in CLAUDE_CODE_EFFORTS:
        raise ValueError(f"{source} value {value!r} must be one of: {accepted}")
    return value


def resolve_cli_claude_effort(args) -> ClaudeCodeEffortIntent:
    """Resolve explicit option, environment fallback, or omission.

    Precedence: explicit --claude-code-effort (or a UI selection forwarded as
    one) > CG_CLAUDE_CODE_EFFORT > omission.

    Note the asymmetry in the two backend checks, which is deliberate. An
    EXPLICIT value on another backend is refused — the operator typed
    something that cannot take effect, and silently ignoring it is how a run
    quietly does the wrong thing. An AMBIENT environment variable on another
    backend is merely omission: CG_CLAUDE_CODE_EFFORT exported in a shell is a
    convenience, and refusing on it would break every unrelated command in that
    shell.

    Unlike the Codex resolver this returns "omitted" rather than a value for
    the no-selection case in every branch; the clamp-versus-inherited
    distinction is not knowable here (it depends on the per-call thinking
    state) and is classified at the seam by `claude_code_run_identity`.
    """
    backend = _effective_backend(args)
    requested = getattr(args, "claude_code_effort", None)

    if requested is not None:
        effort = _valid_claude_code_effort(
            requested, source="--claude-code-effort"
        )
        if backend != "claude-code":
            raise ValueError(
                "--claude-code-effort applies only to --backend claude-code; "
                f"effective backend is {backend!r}"
            )
        return ClaudeCodeEffortIntent(
            backend=backend, requested_effort=effort, environment_effort=None,
            effective_effort=effort, source="explicit", emit_override=True,
        )

    if backend != "claude-code":
        return ClaudeCodeEffortIntent(
            backend=backend, requested_effort=None, environment_effort=None,
            effective_effort=None, source="omitted", emit_override=False,
        )

    raw_environment = os.environ.get("CG_CLAUDE_CODE_EFFORT")
    if raw_environment is None or not raw_environment.strip():
        return ClaudeCodeEffortIntent(
            backend=backend, requested_effort=None, environment_effort=None,
            effective_effort=None, source="omitted", emit_override=False,
        )
    environment = _valid_claude_code_effort(
        raw_environment.strip(), source="CG_CLAUDE_CODE_EFFORT"
    )
    return ClaudeCodeEffortIntent(
        backend=backend, requested_effort=None, environment_effort=environment,
        effective_effort=environment, source="environment", emit_override=True,
    )


def resolve_cli_claude_thinking(args) -> bool | None:
    """Resolve the operator's tri-state thinking choice from argv (issue #365).

    Returns ``True``/``False`` for an explicit choice, or ``None`` for
    "defer" — the environment tier is deliberately NOT read here. The seam
    (`_claude_code_thinking`) owns that fallback, and reading it in two places
    is how the two would come to disagree.

    Mirrors the effort resolver's asymmetry: an explicit flag on another
    backend is refused, because the operator typed something that cannot take
    effect. There is no environment case to be ambient about.
    """
    requested = getattr(args, "claude_code_thinking", None)
    if requested is None:
        return None
    backend = _effective_backend(args)
    if backend != "claude-code":
        raise ValueError(
            "--claude-code-thinking applies only to --backend claude-code; "
            f"effective backend is {backend!r}"
        )
    return bool(requested)


def resolve_cli_model(args, *, legacy_default: str | None) -> CLIModelIntent:
    """Resolve a CLI's model without losing omission versus explicit intent.

    ``args.backend`` follows :func:`client_from_args`: an explicitly selected
    non-Anthropic backend wins, while the parser's default ``anthropic``
    defers to ``CG_BACKEND``.  Empty or whitespace-only ``--model`` input is
    omission.  Codex leaves omitted models unset so its adapter can apply
    ``CG_CODEX_MODEL`` or the subscription default; other backends retain the
    command's supplied ``legacy_default`` (including ``None``).

    Explicit Codex Claude model ids are refused here, before a client is
    constructed.  The check is delegated to the canonical selection seam so
    its case-insensitive Codex rule is shared with server resolution.
    """
    backend = _effective_backend(args)

    requested = getattr(args, "model", None)
    explicit = isinstance(requested, str) and bool(requested.strip())
    if not explicit:
        requested = None

    if explicit and backend == "codex-cli" and not compatible(requested, backend):
        raise ValueError(
            f"model {requested!r} is incompatible with backend 'codex-cli': "
            "Claude model ids cannot be used with the Codex subscription"
        )

    effective = requested if explicit else (
        None if backend == "codex-cli" else legacy_default
    )
    return CLIModelIntent(
        backend=backend,
        requested_model=requested,
        legacy_default=legacy_default,
        effective_model=effective,
        explicit=explicit,
    )


def _require_anthropic_credential(client) -> None:
    """Refuse an Anthropic call with no credential, in a sentence (#342).

    This is the single road a missing Anthropic key arrives by, now that the
    UI's ``api_key_present`` pre-flight is gone. It sits at the *call*, not at
    ``make_client``, for two reasons:

    * Constructing a client is not calling one. ``anthropic.Anthropic()``
      happily constructs without a key, and every ``--dump-only`` path in the
      grounding and ensemble CLIs builds a client it then never uses — the
      documented keyless subscription workflow. Refusing at construction would
      break it.
    * Only the four adapter classes know they need no key at all. Anything
      that is *not* one of them is the real SDK client, so this is also the
      cheapest correct test for "is this call going to the metered API".

    Without it the failure is an SDK authentication error raised mid-run, after
    the pipeline has done its assembly work — a traceback where the deleted
    button-disable used to be a message.
    """
    if isinstance(client, _KEYLESS_CLIENTS):
        return
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    raise SystemExit(
        "ANTHROPIC_API_KEY is not set, and this call goes to the metered "
        "Anthropic API. Export it, or choose a backend that needs no key: "
        "--backend claude-code or --backend codex-cli (bills your subscription), "
        "or --backend dgx (local endpoint)."
    )


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
                backend: str | None = None,
                reasoning_effort: CodexReasoningEffort | None = None,
                reasoning_effort_source: str | None = None,
                claude_code_effort: ClaudeCodeEffort | None = None,
                claude_code_effort_source: str | None = None,
                claude_code_thinking: bool | None = None):
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
    if backend == "codex-cli":
        return _CodexCliClient(
            model_override=model_override,
            reasoning_effort=reasoning_effort,
            reasoning_effort_source=reasoning_effort_source,
        )
    if backend == "claude-code":
        return _ClaudeCodeClient(
            model_override=model_override,
            claude_code_effort=claude_code_effort,
            claude_code_effort_source=claude_code_effort_source,
            claude_code_thinking=claude_code_thinking,
        )
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
    # NOT checked here: see _require_anthropic_credential. Constructing a client
    # is not calling one — every --dump-only path builds a client it never uses.
    return anthropic.Anthropic()


def add_codex_reasoning_arg(parser) -> None:
    """Register the one Codex effort spelling used by every CLI surface."""
    parser.add_argument(
        "--codex-reasoning-effort",
        choices=CODEX_REASONING_EFFORTS,
        default=None,
        help=(
            "Codex CLI reasoning effort. Applies only to --backend codex-cli; "
            "CG_CODEX_REASONING_EFFORT is the fallback. Omit to send no "
            "CampaignGenerator override (Codex default). Model support varies; "
            "gpt-5.6-sol supports max. Unsupported combinations fail without "
            "downgrade or provider fallback."
        ),
    )


def add_claude_code_effort_arg(parser) -> None:
    """Register the one claude-code effort spelling used by every CLI surface.

    Called from add_backend_args, so all 30 model-bearing CLIs inherit it as
    one act rather than thirty — the family-wide introduction Principle XII
    requires. Exported separately for the few CLIs that build their own
    backend arguments (facts_to_state) or forward it to child argv.
    """
    parser.add_argument(
        "--claude-code-effort",
        choices=CLAUDE_CODE_EFFORTS,
        default=None,
        help=(
            "Claude Code CLI effort level. Applies only to --backend "
            "claude-code; CG_CLAUDE_CODE_EFFORT is the fallback. Omit to keep "
            "the current behaviour (a compatibility clamp when thinking is "
            "suppressed, otherwise your own ~/.claude/settings.json "
            "effortLevel). 'xhigh' and 'max' require thinking — set "
            "CG_CLAUDE_CODE_THINKING=1, or the call is refused. Higher levels "
            "increase run time."
        ),
    )


def add_claude_code_thinking_arg(parser) -> None:
    """Register the one claude-code thinking spelling (issue #365).

    ``BooleanOptionalAction`` gives ``--claude-code-thinking`` and
    ``--no-claude-code-thinking`` from one declaration, with ``default=None``
    so the tri-state survives argv: absent defers to
    ``CG_CLAUDE_CODE_THINKING``, ``--no-…`` is a sticky off that beats it.

    Registered from add_backend_args beside the two effort registrars, so all
    30 model-bearing CLIs inherit it together (Principle XII).
    """
    parser.add_argument(
        "--claude-code-thinking",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Extended thinking on the claude-code backend. Applies only to "
            "--backend claude-code. Omit to defer to CG_CLAUDE_CODE_THINKING "
            "(off by default: suppressing the trace is measurably faster). "
            "Required for --claude-code-effort xhigh/max. Cannot be disabled "
            "on the Fable/Mythos families, where --no-claude-code-thinking is "
            "accepted and has no effect."
        ),
    )


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
        "--backend", choices=BACKENDS,
        default=default_backend,
        help=f"LLM backend ({_default_note}). 'dgx'/'openrouter'/'claude-code'/'codex-cli' route "
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
    add_codex_reasoning_arg(parser)
    add_claude_code_effort_arg(parser)
    add_claude_code_thinking_arg(parser)


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
    reasoning = resolve_cli_reasoning(args)
    claude_effort = resolve_cli_claude_effort(args)
    claude_thinking = resolve_cli_claude_thinking(args)
    if claude_effort.effective_effort is not None:
        # Fail fast at the edge when the conflict is ALREADY determined: the
        # model and the environment thinking opt-in are both known here. The
        # seam guards again before the child spawns, because a per-call
        # thinking=True is not visible from argv (research R2). Same helper,
        # so there is one wording rather than two that drift.
        conflict = claude_code_effort_conflict(
            claude_effort.effective_effort,
            thinking_on=_claude_code_thinking(None, selection=claude_thinking),
            model=getattr(args, "model", None) or "",
        )
        if conflict:
            raise SystemExit(conflict)
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
    model_override = getattr(args, "model", None) if backend in (
        "dgx", "openrouter", "claude-code", "codex-cli"
    ) else None
    resolved_endpoint = endpoint if endpoint is not None else getattr(args, "endpoint", None)
    client_kwargs = {
        "backend": backend,
        "endpoint": resolved_endpoint,
        "model_override": model_override,
    }
    if reasoning.backend == "codex-cli" and reasoning.effective_effort is not None:
        client_kwargs.update(
            reasoning_effort=reasoning.effective_effort,
            reasoning_effort_source=reasoning.source,
        )
    if (claude_effort.backend == "claude-code"
            and claude_effort.effective_effort is not None):
        client_kwargs.update(
            claude_code_effort=claude_effort.effective_effort,
            claude_code_effort_source=claude_effort.source,
        )
    if backend == "claude-code" and claude_thinking is not None:
        client_kwargs.update(claude_code_thinking=claude_thinking)
    return make_client(**client_kwargs)


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
    _require_anthropic_credential(client)
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
    _require_anthropic_credential(client)
    delays = [10, 20, 40]
    for attempt, delay in enumerate([-1] + delays):
        if delay >= 0:
            print(f"\n  [API unavailable — waiting {delay}s before retry {attempt}/{len(delays)}...]",
                  flush=True)
            time.sleep(delay)
        try:
            # Most providers expose the Anthropic-shaped ``messages`` API.
            # Codex's structured polish turn is deliberately a separate
            # capability on the same client; selecting it by capability keeps
            # this seam provider-neutral and leaves all operation dispatch in
            # the caller.
            messages_api = getattr(client, "brokered_messages", client.messages)
            return messages_api.create(
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
    _require_anthropic_credential(client)
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
