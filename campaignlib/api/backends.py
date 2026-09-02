"""LLM client adapters: OpenAI-compatible (DGX/vLLM) and Claude Code (subscription).

Each presents the small slice of the anthropic SDK surface that
campaignlib.api.client (stream_api / call_api) depends on.
"""

import json
import os
import sys
from dataclasses import dataclass


from ..selection import (
    CLAUDE_CODE_EFFORTS,
    CLAUDE_CODE_THINKING_ONLY_EFFORTS,
    ClaudeCodeEffort,
)
from ..wiring import wiring_get  # noqa: E402

# DGX model is EXTERNAL config (names what the DGX serves) — mneme-owned.
DGX_DEFAULT_MODEL = wiring_get("dgx_model")
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _flatten_to_text(value) -> str:
    """Reduce an Anthropic-style content value to plain text for OpenAI-compat servers.

    Accepts: a string, or a list of content blocks (dicts with "type" + "text").
    Drops any non-text blocks (images, tool_use). vLLM/Qwen doesn't see them.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for block in value:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n\n".join(p for p in parts if p)
    return str(value)


def _anthropic_to_openai_messages(system, messages):
    """Translate (system, [Anthropic messages]) → OpenAI chat.completions messages."""
    out = []
    sys_text = _flatten_to_text(system)
    if sys_text:
        out.append({"role": "system", "content": sys_text})
    for m in messages or []:
        out.append({"role": m["role"], "content": _flatten_to_text(m.get("content"))})
    return out


class _OpenAICompatResponse:
    """Mimics anthropic.types.Message just enough for call_api's `.content[0].text` access."""

    class _Block:
        def __init__(self, text: str):
            self.type = "text"
            self.text = text

    def __init__(self, text: str):
        self.content = [self._Block(text)]
        self.stop_reason = "end_turn"


class _OpenAICompatStream:
    """Mimics the anthropic streaming context manager: `with client.messages.stream(...) as s: s.text_stream`."""

    def __init__(self, oai_client, *, model: str, max_tokens: int, messages: list, extra_body: dict | None = None):
        self._oai = oai_client
        self._model = model
        self._max_tokens = max_tokens
        self._messages = messages
        self._extra_body = extra_body or {}
        self._stream = None

    def __enter__(self):
        self._stream = self._oai.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=self._messages,
            stream=True,
            extra_body=self._extra_body or None,
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self._stream.close()
        except Exception:
            pass
        return False

    @property
    def text_stream(self):
        def _iter():
            for chunk in self._stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None)
                if piece:
                    yield piece
        return _iter()


class _OpenAICompatMessages:
    def __init__(self, client: "_OpenAICompatClient"):
        self._client = client

    def _resolve_model(self, model: str) -> str:
        if self._client.model_override:
            return self._client.model_override
        # Caller passed an Anthropic model name (e.g. "claude-sonnet-4-6") which the
        # DGX server doesn't know about — substitute the configured default rather
        # than 404.
        if isinstance(model, str) and model.startswith("claude-"):
            return DGX_DEFAULT_MODEL
        return model

    def create(self, *, model, max_tokens, system, messages, tools=None,
               thinking=None, **_ignored):
        if tools:
            raise NotImplementedError(
                "tool use is not supported on the DGX endpoint — drop --dgx-endpoint "
                "for paths that need tools (e.g. enhance_recap with tools enabled)."
            )
        resolved = self._resolve_model(model)
        resp = self._client.oai.chat.completions.create(
            model=resolved,
            max_tokens=max_tokens,
            messages=_anthropic_to_openai_messages(system, messages),
            extra_body=self._client.extra_body_for(resolved, thinking) or None,
        )
        text = resp.choices[0].message.content or ""
        return _OpenAICompatResponse(text)

    def stream(self, *, model, max_tokens, system, messages, thinking=None, **_ignored):
        resolved = self._resolve_model(model)
        return _OpenAICompatStream(
            self._client.oai,
            model=resolved,
            max_tokens=max_tokens,
            messages=_anthropic_to_openai_messages(system, messages),
            extra_body=self._client.extra_body_for(resolved, thinking),
        )


class _OpenAICompatClient:
    """Anthropic-shaped façade over an OpenAI-compatible server (vLLM on the DGX, etc.).

    Supports only the call shapes used by stream_api / call_api: text-in, text-out,
    single-turn user message with an optional system prompt. Batching, tool use,
    and vision content are not implemented — those paths need the real Anthropic API.
    """

    def __init__(self, endpoint: str, model_override: str | None = None,
                 api_key: str = "not-needed"):
        try:
            from openai import OpenAI
        except ImportError:
            print("Error: openai not installed. Run: pip install openai", file=sys.stderr)
            sys.exit(1)
        # vLLM serves under /v1/. Accept both "http://host:port" and "http://host:port/v1".
        base_url = endpoint.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = base_url + "/v1"
        try:
            import dgxlib
        except ImportError:
            print("Error: dgxlib not installed. Run: pip install -e ~/src/dgx",
                  file=sys.stderr)
            sys.exit(1)
        self._dgxlib = dgxlib
        self.model_override = model_override or os.environ.get("DGX_MODEL") or DGX_DEFAULT_MODEL
        # Per-model request behavior comes from the dgxlib registry (one source of
        # truth, edited next to the Spark spin-up scripts) — not inline here.
        cfg = dgxlib.resolve_model_config(self.model_override)
        # Explicit timeouts. A local vLLM box that is wedged, overloaded, or —
        # the case that actually bit us — frozen by a host sleep leaves the TCP
        # socket half-open: the peer is gone, no RST ever arrives, and a blocked
        # read() never returns, so the call hangs forever. A read timeout makes a
        # stalled/stale connection raise httpx.ReadTimeout (which stream_api
        # treats as retryable and reopens on a fresh socket) in minutes, not
        # never. The budget is the model's registry read_timeout; DGX_READ_TIMEOUT
        # still overrides it.
        import httpx
        env_to = os.environ.get("DGX_READ_TIMEOUT")
        read_timeout = float(env_to) if env_to else cfg.read_timeout
        timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=30.0)
        self.oai = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.messages = _OpenAICompatMessages(self)

    def extra_body_for(self, resolved_model: str, thinking: bool | None) -> dict:
        """Per-call request extras (e.g. enable_thinking) from the dgxlib registry.

        ``thinking`` is a per-call decision: ``None`` uses the model's registry
        default; ``True``/``False`` overrides it (honored only for reasoning-capable
        models). ``DGX_NO_THINKING`` forces it off for back-compat when the caller
        did not specify.
        """
        if thinking is None and os.environ.get("DGX_NO_THINKING"):
            thinking = False
        return self._dgxlib.resolve_model_config(resolved_model, thinking=thinking).extra_body


# ── OpenRouter backend ───────────────────────────────────────────────────────
#
# OpenRouter (https://openrouter.ai) is an OpenAI-wire-compatible gateway to many
# model vendors. It is reached ONLY through this class — Constitution Principle V
# (one seam per boundary). Unlike the DGX adapter it (a) uses a real API key from
# OPENROUTER_API_KEY, (b) does NOT consult the dgxlib model registry (OpenRouter
# ids are namespaced, e.g. "anthropic/claude-sonnet-4", and pass through verbatim),
# and (c) maps a no-thinking request to OpenRouter's `reasoning` control so the
# silently-empty-extraction trap (a reasoning model spending its whole budget on a
# think trace) can be suppressed on this path too.


class _OpenRouterMessages(_OpenAICompatMessages):
    """Messages façade for OpenRouter — same wire calls as the DGX adapter, but
    model ids pass through verbatim (no dgxlib registry, no claude→DGX substitution)."""

    def _resolve_model(self, model: str) -> str:
        # Honor an explicit override; otherwise send the caller's id straight
        # through. OpenRouter ids are vendor-namespaced, so the DGX adapter's
        # "claude-* → DGX default" substitution must NOT apply here.
        return self._client.model_override or model


class _OpenRouterClient:
    """Anthropic-shaped façade over OpenRouter's OpenAI-compatible API.

    Presents the same small slice of the anthropic SDK surface
    (``.messages.create`` / ``.messages.stream``) that stream_api / call_api use,
    reusing the OpenAI-compat stream/response machinery.
    """

    def __init__(self, model_override: str | None = None):
        # Check config before importing the SDK so a missing key fails with a
        # clear, deterministic error (no silent fallback to another backend).
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. The openrouter backend requires a key; "
                "export OPENROUTER_API_KEY in the environment."
            )
        try:
            from openai import OpenAI
        except ImportError:
            print("Error: openai not installed. Run: pip install openai", file=sys.stderr)
            sys.exit(1)
        base_url = (os.environ.get("OPENROUTER_BASE_URL")
                    or OPENROUTER_DEFAULT_BASE_URL).rstrip("/")
        self.model_override = model_override or os.environ.get("OPENROUTER_MODEL")
        import httpx
        env_to = os.environ.get("OPENROUTER_READ_TIMEOUT")
        read_timeout = float(env_to) if env_to else 600.0
        timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=30.0)
        self.oai = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.messages = _OpenRouterMessages(self)

    def extra_body_for(self, resolved_model: str, thinking: bool | None) -> dict:
        """Per-call request extras. Maps no-thinking to OpenRouter's `reasoning`.

        ``thinking`` is a per-call decision: ``None`` leaves OpenRouter's default
        (but OPENROUTER_NO_THINKING / DGX_NO_THINKING force it off for parity with
        the DGX extraction path); ``False`` disables reasoning; ``True`` leaves it on.
        """
        if thinking is None and (os.environ.get("OPENROUTER_NO_THINKING")
                                 or os.environ.get("DGX_NO_THINKING")):
            thinking = False
        if thinking is False:
            return {"reasoning": {"enabled": False}}
        return {}


# ── Claude Code (subscription) backend ──────────────────────────────────────
#
# Routes generation through the `claude` CLI in headless print mode (`claude -p`)
# instead of the metered Anthropic API. When Claude Code is logged in with a
# Pro/Max subscription, these calls draw on the subscription quota — no per-token
# API charge. The whole point is to spend the subscription you already pay for
# rather than API credits.
#
# Critical: `claude` bills the metered API if ANTHROPIC_API_KEY is present in its
# environment. We strip it from the subprocess env so it falls back to the stored
# subscription OAuth login. If you ever see API spend while on this backend, the
# key leaked into the child env.
#
# Limitations (mirror the DGX/OpenAI-compat adapter): single-turn text in / text
# out only. Tool use, vision, and true token streaming are not supported — those
# paths keep the real Anthropic API. Output is delivered as one chunk, so the
# streaming UI shows the whole block at once after the call returns.
#
# Thinking is OFF by default on this backend, unlike every other one. `claude -p`
# runs extended thinking by default, but the real Anthropic SDK path does not
# (stream_api only forwards `thinking` to _THINKING_EXTRA_CLIENTS), so leaving it
# on made the two backends do measurably different work for the same call. Worse,
# `max_tokens` is forwarded as CLAUDE_CODE_MAX_OUTPUT_TOKENS, which the CLI
# charges the thinking trace against: a ~14K-token trace against enhance_summary's
# default 16384 ceiling left no room for the answer, so the CLI auto-continued
# into a fresh turn and thought another ~14K. Measured on a 130,412-char VTT:
#
#   --backend anthropic                          3m23s   ~9K output tokens
#   --backend claude-code (16384 ceiling)        17m43s  53,387 output tokens (+ seam)
#   --backend claude-code --max-tokens 32000     10m54s  clean, no seam
#   ... plus MAX_THINKING_TOKENS=0                3m57s  10,100 output tokens
#
# Raising the ceiling only stops the auto-continue loop; suppressing the trace is
# what closes the gap. Every pipeline on this backend is a render/extract pass
# ("LLM renders, humans decide"), and the tool-use judgement passes can't run here
# at all — `create()` rejects tools. Set CG_CLAUDE_CODE_THINKING=1, or pass
# thinking=True per call, to opt back in.
#
# Suppressing the trace also constrains effort: the API rejects the top two
# effort levels outright when thinking is disabled —
#
#   API Error: 400 output_config.effort 'xhigh' is not supported when thinking
#   is disabled on this model. Use effort 'high' or below, or enable thinking.
#
# — and the CLI resolves effort from the GM's own `~/.claude/settings.json`
# (`effortLevel`), which a power user may well have pinned to xhigh/max. That
# is not an env var we can unset in the child: the setting is read from disk,
# so every subscription-backed call hard-fails until it is overridden on the
# command line. We pass `--effort` explicitly, at the highest level that is
# legal without thinking, whenever we actually suppress the trace.
#
# "Actually" is the model-conditional part. On the Fable/Mythos family thinking
# is always on and cannot be disabled at all, so MAX_THINKING_TOKENS=0 is a
# no-op there and xhigh/max stay legal (verified: a `claude -p` call on
# claude-fable-5 with the var set and an inherited xhigh returns clean). Pinning
# effort on those models would silently downgrade the GM's configured level to
# dodge an error that cannot occur, so we skip the clamp for them.

CLAUDE_CODE_CLI = os.environ.get("CG_CLAUDE_CLI", "claude")

# Highest effort level the API accepts when thinking is disabled.
CLAUDE_CODE_NO_THINKING_EFFORT = "high"

# Substrings identifying model families whose thinking cannot be disabled.
# Matched against the model id, so they cover bare aliases, date suffixes, and
# provider-prefixed ids (`anthropic.claude-fable-5`) alike.
CLAUDE_CODE_ALWAYS_THINKING_MARKERS = ("fable", "mythos")


def _claude_code_always_thinking(model: str) -> bool:
    """True when `model`'s extended thinking cannot be turned off.

    The Fable/Mythos family runs adaptive thinking unconditionally — an
    explicit disable is rejected outright — so the effort ceiling that applies
    to thinking-disabled calls never binds there.
    """
    return any(m in (model or "").lower() for m in CLAUDE_CODE_ALWAYS_THINKING_MARKERS)


def _claude_code_thinking(
    thinking: bool | None, *, selection: bool | None = None,
) -> bool:
    """Resolve reasoning intent for the `claude -p` backend.

    Three tiers, most specific first:

    1. ``thinking`` — the per-call argument ``stream_api``/``call_api``
       forward. A caller that names it for this one call always wins.
    2. ``selection`` — the operator's stored/typed choice (issue #365):
       ``--claude-code-thinking`` / ``--no-claude-code-thinking``, or the UI
       toggle, resolved through the same tiers as model and effort.
    3. ``CG_CLAUDE_CODE_THINKING`` — the environment opt-in, which was the
       ONLY reachable lever before #365.

    All three absent resolves to OFF — see the module comment above for the
    measurement that motivates the inverted default. That default is
    deliberately unchanged by #365: making thinking selectable is not the same
    as deciding it should be on, and re-deciding it deserves a fresh
    measurement rather than a side effect of adding a control.

    Note that ``selection=False`` is a genuine, sticky "off" that beats the
    environment variable, while ``selection=None`` defers to it. A plain bool
    could not express that difference — the same reason ``ModelSelection.batch``
    is ``bool | None``.
    """
    if thinking is not None:
        return bool(thinking)
    if selection is not None:
        return bool(selection)
    return bool(os.environ.get("CG_CLAUDE_CODE_THINKING"))


def claude_code_effort_conflict(
    effort: str | None, *, thinking_on: bool, model: str
) -> str | None:
    """Return the refusal message when `effort` cannot run, else None.

    ONE source for this wording. It is called from two places — the CLI edge
    (`client_from_args`, which fails fast when the state is already known) and
    the seam (`_claude_code_generate`, immediately before the child spawns,
    which is the only place that sees a per-call `thinking=True`). Two call
    sites with two hand-written messages would be the same refusal in two
    dialects; see specs/021-claude-code-effort/research.md R2.

    The three conditions are all required:

    1. the requested level is one the API refuses with thinking disabled,
    2. thinking is in fact disabled for this call, and
    3. the model's thinking CAN be disabled — on the Fable/Mythos families it
       cannot, so the top levels stay legal and refusing would block a working
       configuration (FR-009a).

    Returns a message rather than raising so each caller can raise the
    exception type its layer already uses.
    """
    if effort not in CLAUDE_CODE_THINKING_ONLY_EFFORTS:
        return None
    if thinking_on or _claude_code_always_thinking(model):
        return None
    return (
        f"--claude-code-effort {effort!r} requires extended thinking, which is "
        f"disabled for this call. Either lower the effort to "
        f"{CLAUDE_CODE_NO_THINKING_EFFORT!r} or below, or enable thinking with "
        f"--claude-code-thinking (the Thinking control in the UI, or "
        f"CG_CLAUDE_CODE_THINKING=1). Refusing rather than changing your "
        f"thinking setting or silently lowering the effort."
    )


@dataclass(frozen=True)
class ClaudeCodeRunIdentity:
    """What a claude-code run actually did — not what was asked for.

    The two are not the same object, and the gap between them is the defect
    this feature exists to close: today a run can send `--effort high` that
    nobody chose, silently overriding the level the operator pinned in their
    own ~/.claude/settings.json, and nothing anywhere says so.
    """

    effective_model: str
    effort_sent: ClaudeCodeEffort | None
    source: str          # explicit | environment | clamp | inherited
    override_sent: bool
    thinking_on: bool

    @property
    def always_thinking(self) -> bool:
        return _claude_code_always_thinking(self.effective_model)

    def banner(self) -> str:
        # "on (always)" rather than "off" on the Fable/Mythos families. We did
        # not *request* thinking there, but it cannot be disabled, which is
        # exactly why the top effort levels stay legal and the clamp is
        # skipped. Printing a bare "off" beside "effort=max" would read as a
        # refusal that should have fired and did not.
        if self.always_thinking:
            thinking = "on (always)"
        else:
            thinking = "on" if self.thinking_on else "off"
        if self.source == "explicit":
            effort = f"effort={self.effort_sent} (explicit)"
        elif self.source == "environment":
            effort = f"effort={self.effort_sent} (CG_CLAUDE_CODE_EFFORT)"
        elif self.source == "clamp":
            # Says WHY. A bare "high" here would attribute the engine's
            # compatibility decision to the human (FR-020).
            effort = (
                f"effort={self.effort_sent} (compatibility clamp — thinking is "
                f"off, and the provider refuses "
                f"{'/'.join(CLAUDE_CODE_THINKING_ONLY_EFFORTS)} without it; your "
                f"settings.json effortLevel was not used)"
            )
        else:
            # Claims no value: we never read ~/.claude/settings.json, so
            # printing a level from it would be a guess presented as a record.
            effort = (
                "effort=inherited from your ~/.claude/settings.json "
                "(CampaignGenerator sent no override)"
            )
        return (
            f"claude-code run: model={self.effective_model} {effort} "
            f"thinking={thinking}"
        )

    def as_dict(self) -> dict:
        """Wire shape for `client.last_run_identity`, which the Connection
        Graph renders. Mirrors the Codex client's contract so one consumer
        can handle both without a second code path."""
        return {
            "backend": "claude-code",
            "model": self.effective_model,
            "claude_code_effort": self.effort_sent or "inherited",
            "claude_code_effort_source": self.source,
            "claude_code_effort_override": self.override_sent,
            "thinking": self.thinking_on or self.always_thinking,
        }


def claude_code_run_identity(
    *, model: str, thinking_on: bool,
    effort: str | None = None, source: str | None = None,
) -> ClaudeCodeRunIdentity:
    """Classify what this run will send, and who decided it.

    Four sources, where Codex has three. Today's single silent "omission" is
    really two different behaviours the operator cannot tell apart:

    - ``clamp``     — nothing was chosen, thinking is suppressed, and the model
                      permits that, so the engine pins the highest legal level.
    - ``inherited`` — nothing was chosen and no clamp applies, so no --effort
                      is sent at all and the child resolves the operator's own
                      settings.json.

    Splitting them is what makes SC-008 answerable.
    """
    if effort is not None:
        return ClaudeCodeRunIdentity(
            effective_model=model, effort_sent=effort,
            source=source or "explicit", override_sent=True,
            thinking_on=thinking_on,
        )
    if not thinking_on and not _claude_code_always_thinking(model):
        return ClaudeCodeRunIdentity(
            effective_model=model, effort_sent=CLAUDE_CODE_NO_THINKING_EFFORT,
            source="clamp", override_sent=True, thinking_on=thinking_on,
        )
    return ClaudeCodeRunIdentity(
        effective_model=model, effort_sent=None,
        source="inherited", override_sent=False, thinking_on=thinking_on,
    )


def _blocks_to_text(x) -> str:
    """Flatten a string | list-of-content-blocks into plain text.

    Accepts the shapes campaignlib passes as `system` (str, or a list with a
    cache_control text block) and as message `content` (str, or a list of
    text blocks). Raises on image blocks — vision is not supported here.
    """
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        parts = []
        for b in x:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                if b.get("type") == "image":
                    raise NotImplementedError(
                        "vision/image content is not supported on the claude-code "
                        "backend — use the Anthropic API for vision calls."
                    )
                if "text" in b:
                    parts.append(b["text"])
        return "\n".join(p for p in parts if p)
    return str(x)


def _messages_user_text(messages: list) -> str:
    """Concatenate the text of all user-role messages into a single prompt.

    The campaignlib call paths only ever send a single user turn (assistant
    turns appear solely in tool-use loops, which this backend rejects).
    """
    parts = [
        _blocks_to_text(m.get("content"))
        for m in messages
        if m.get("role") == "user"
    ]
    return "\n\n".join(p for p in parts if p)


def _claude_code_generate(
    *, system, user: str, model: str, max_tokens: int | None = None,
    thinking: bool | None = None, effort: str | None = None,
    effort_source: str | None = None, thinking_selection: bool | None = None,
    announce=None,
) -> str:
    """Invoke `claude -p` headless and return the assistant text.

    System prompt is passed via a temp file (--system-prompt-file) so a large
    cached prefix doesn't blow ARG_MAX; the user prompt is piped on stdin for
    the same reason. ANTHROPIC_API_KEY is stripped so billing lands on the
    subscription, not the metered API.

    Thinking is suppressed via MAX_THINKING_TOKENS=0 unless the caller asks for
    it (`thinking=True`) or CG_CLAUDE_CODE_THINKING is set — see the module
    comment for why this backend inverts the usual default.

    `effort` is the operator's resolved choice (feature 021), or None. When it
    is None the pre-021 behaviour is reproduced exactly: suppressing thinking
    forces `--effort high`, because the API refuses effort above that with
    thinking off and the CLI would otherwise resolve the GM's own settings.json
    `effortLevel` (xhigh/max for a power user) and 400 on every call. That
    clamp is skipped on models whose thinking can't be disabled in the first
    place (Fable/Mythos), where the ceiling doesn't apply. An explicit `effort`
    replaces the clamp; it never stacks with it.

    The clamp used to be invisible, which is the defect 021 closes: it silently
    overrode a level the operator had deliberately set, and no output said so.
    `claude_code_run_identity` classifies which of the four things happened and
    `announce` (called at most once per client) reports it.

    `--strict-mcp-config` is passed with no `--mcp-config`, so the CLI ignores
    every configured MCP server. `--disallowed-tools '*'` already stops the
    tools being *used*, but not the servers being *spawned*: a campaign
    workspace launched seven of them (codebase-memory, headroom, mcp-server-git,
    campaign, mempalace, 5etools, registry) on every single call, at ~300MB
    apiece. They contribute no tokens either way (measured: an identical
    13,399-token cached prefix with and without the flag), so this is pure
    process/memory overhead — which scene_extract paid once per scene.

    `claude -p` has no output-length CLI flag, but it honors the
    CLAUDE_CODE_MAX_OUTPUT_TOKENS env var. We forward the caller's `max_tokens`
    through it so the subscription path respects the same ceiling the Anthropic
    API and DGX backends do (a ceiling, not a target — it permits longer output,
    it does not force it).

    Uses `--output-format stream-json --verbose` (print mode requires
    --verbose when stream-json is requested) instead of the single-envelope
    `json` format. Current CLI versions (observed: 2.1.220) do NOT hard-error
    when generation hits CLAUDE_CODE_MAX_OUTPUT_TOKENS mid-turn — they
    AUTO-CONTINUE in a second (or further) assistant turn, and
    `--output-format json`'s single `result` field only reflects the LAST
    turn, silently dropping the head of the response. Streaming NDJSON lets
    us concatenate the text of every assistant turn ourselves instead. The
    is_error / "output token maximum" hard-error branch below is kept for
    older CLI versions that still exit that way.

    The auto-continue WARNING counts assistant events that carry a `text`
    block, NOT assistant events outright. A thinking-capable model emits its
    `thinking` block as a separate assistant event, so an ordinary untruncated
    call already yields two events. Counting events outright made the warning
    fire on every claude-fable-5 call (thinking is always on there and cannot
    be disabled) and every claude-opus-5 call (thinking on by default) —
    crying wolf until a real truncation was indistinguishable from noise.
    """
    import subprocess
    import tempfile

    sys_text = _blocks_to_text(system)
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    if max_tokens:
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_tokens)
    thinking_on = _claude_code_thinking(thinking, selection=thinking_selection)
    if thinking_on:
        # Opted in — inherit whatever the CLI/model would do on its own. Drop any
        # inherited MAX_THINKING_TOKENS=0 so the opt-in actually takes effect.
        env.pop("MAX_THINKING_TOKENS", None)
    else:
        env["MAX_THINKING_TOKENS"] = "0"

    # Refuse an impossible effort/thinking pair BEFORE the child exists — that
    # is what "before any model work starts" means here, and it is the only
    # place a per-call thinking=True is visible (research R2). No fallback: we
    # neither enable thinking nor lower the level on the operator's behalf.
    conflict = claude_code_effort_conflict(
        effort, thinking_on=thinking_on, model=model)
    if conflict:
        raise ValueError(conflict)

    identity = claude_code_run_identity(
        model=model, thinking_on=thinking_on,
        effort=effort, source=effort_source,
    )
    if announce is not None:
        announce(identity)

    cmd = [
        CLAUDE_CODE_CLI, "-p",
        "--model", model,
        "--output-format", "stream-json",
        "--verbose",   # required by print mode when --output-format is stream-json
        "--disallowed-tools", "*",   # pure text generation; no agentic tool calls
        "--strict-mcp-config",       # ...and don't even spawn the MCP servers
    ]
    if identity.override_sent:
        # One decision point for --effort: an explicit/environment level, or
        # the compatibility clamp. Splitting them would let two branches
        # disagree about what the child receives.
        cmd += ["--effort", identity.effort_sent]
    sp_file = None
    try:
        if sys_text:
            sp_file = tempfile.NamedTemporaryFile(
                "w", suffix=".txt", prefix="cg_sysprompt_", delete=False, encoding="utf-8")
            sp_file.write(sys_text)
            sp_file.close()
            cmd += ["--system-prompt-file", sp_file.name]
        proc = subprocess.run(
            cmd, input=user, capture_output=True, text=True, env=env)

        # stdout is newline-delimited JSON events. Collect the concatenated
        # text of every "assistant" event (in turn order) and keep the
        # terminal "result" event for error handling — it carries the same
        # `result` / `is_error` / `num_turns` fields the old single-envelope
        # `json` format did, just as one event among many now.
        assistant_text_parts: list[str] = []
        num_text_turns = 0
        result_event: dict | None = None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "assistant":
                # Count only turns that actually carry text. A thinking-capable
                # model emits its `thinking` block as its OWN assistant event,
                # so counting every assistant event would report a continuation
                # on every single call — see the auto-continue note above.
                message = event.get("message") or {}
                had_text = False
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        assistant_text_parts.append(block.get("text", ""))
                        had_text = True
                if had_text:
                    num_text_turns += 1
            elif event.get("type") == "result":
                result_event = event

        # `claude -p` emits a parseable result envelope even when it fails on
        # an output-token overflow — and in that case it ALSO exits non-zero.
        # Inspect the envelope BEFORE the returncode so the overflow-specific
        # message is reachable; fall back to the raw exit error only when no
        # result event was found at all (genuine failures: CLI not found,
        # auth failure, crash — no JSON envelope ever emitted).
        if result_event is not None:
            if result_event.get("is_error"):
                result_text = str(result_event.get("result", ""))
                # Older CLI versions treat hitting the cap as a hard error and
                # discard the text, rather than auto-continuing (see
                # docstring). Re-phrase the env-var-centric message in terms
                # of the caller's knob (--narrate-tokens / max_tokens).
                if max_tokens and "output token maximum" in result_text:
                    raise RuntimeError(
                        f"claude -p hit the {max_tokens}-token output ceiling and "
                        f"returned no text (this CLI version errors on overflow "
                        f"rather than auto-continuing). Raise --narrate-tokens "
                        f"/ max_tokens for this run.")
                raise RuntimeError(f"claude -p error: {result_text[:500]}")

            if num_text_turns > 1:
                print(
                    f"\n{'!' * 70}\n"
                    f"!!  WARNING: claude -p hit its output ceiling mid-generation and AUTO-CONTINUED\n"
                    f"!!  across {num_text_turns} assistant turns. All turns were concatenated, but there may be a\n"
                    f"!!  seam at the continuation boundary — review the output, and consider raising\n"
                    f"!!  max_tokens (CLAUDE_CODE_MAX_OUTPUT_TOKENS) for this call.\n"
                    f"{'!' * 70}",
                    file=sys.stderr, flush=True)

            if assistant_text_parts:
                return "".join(assistant_text_parts)
            # Defensive fallback — no assistant text blocks were parsed at all.
            return str(result_event.get("result", ""))

        # No result event found among the parsed lines — a genuine process
        # failure (CLI not found, auth error, crash before emitting one).
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude -p exited {proc.returncode}: "
                f"{(proc.stderr or proc.stdout).strip()[:500]}")

        # Exited 0 but produced no usable result envelope.
        raise RuntimeError(
            f"claude -p returned non-JSON output: {proc.stdout[:300]!r}")
    finally:
        if sp_file is not None:
            try:
                os.unlink(sp_file.name)
            except OSError:
                pass


class _ClaudeCodeStream:
    """Mimics the anthropic streaming context manager over `claude -p`.

    No real token streaming: the call runs to completion on __enter__ and the
    whole result is yielded as a single chunk. Satisfies stream_api's
    `with client.messages.stream(...) as s: s.text_stream` contract.
    """

    def __init__(self, *, system, user: str, model: str, max_tokens: int | None = None,
                 thinking: bool | None = None, effort: str | None = None,
                 effort_source: str | None = None,
                 thinking_selection: bool | None = None, announce=None):
        self._system = system
        self._user = user
        self._model = model
        self._max_tokens = max_tokens
        self._thinking = thinking
        self._effort = effort
        self._effort_source = effort_source
        self._thinking_selection = thinking_selection
        self._announce = announce
        self._text = ""

    def __enter__(self):
        self._text = _claude_code_generate(
            system=self._system, user=self._user, model=self._model,
            max_tokens=self._max_tokens, thinking=self._thinking,
            effort=self._effort, effort_source=self._effort_source,
            thinking_selection=self._thinking_selection,
            announce=self._announce)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def text_stream(self):
        def _iter():
            if self._text:
                yield self._text
        return _iter()


class _ClaudeCodeMessages:
    def __init__(self, client: "_ClaudeCodeClient"):
        self._client = client

    def _resolve_model(self, model: str) -> str:
        # Unlike the DGX endpoint, the subscription speaks native Anthropic model
        # names, so the picker's claude-* value flows straight through.
        return self._client.model_override or model

    def create(self, *, model, max_tokens, system, messages, tools=None,
               thinking=None, **_ignored):
        if tools:
            raise NotImplementedError(
                "tool use is not supported on the claude-code backend — switch to "
                "the Anthropic API for tool-use paths (Stage 1/2/Plan)."
            )
        text = _claude_code_generate(
            system=system,
            user=_messages_user_text(messages),
            model=self._resolve_model(model),
            max_tokens=max_tokens,
            thinking=thinking,
            effort=self._client.claude_code_effort,
            effort_source=self._client.claude_code_effort_source,
            thinking_selection=self._client.claude_code_thinking,
            announce=self._client.announce_once,
        )
        return _OpenAICompatResponse(text)

    def stream(self, *, model, max_tokens, system, messages, thinking=None, **_ignored):
        return _ClaudeCodeStream(
            system=system,
            user=_messages_user_text(messages),
            model=self._resolve_model(model),
            max_tokens=max_tokens,
            thinking=thinking,
            effort=self._client.claude_code_effort,
            effort_source=self._client.claude_code_effort_source,
            thinking_selection=self._client.claude_code_thinking,
            announce=self._client.announce_once,
        )


class _ClaudeCodeClient:
    """Anthropic-shaped façade over `claude -p` (Pro/Max subscription billing).

    Supports only the single-turn text-in/text-out shapes used by call_api and
    stream_api. Tools, vision, batching, and real streaming are unsupported.
    """

    def __init__(self, model_override: str | None = None,
                 claude_code_effort: str | None = None,
                 claude_code_effort_source: str | None = None,
                 claude_code_thinking: bool | None = None):
        self.model_override = model_override or os.environ.get("CG_CLAUDE_CODE_MODEL")
        self.claude_code_effort = claude_code_effort
        self.claude_code_effort_source = claude_code_effort_source
        # Tri-state (#365): None defers to CG_CLAUDE_CODE_THINKING, False is a
        # sticky "off" that beats it.
        self.claude_code_thinking = claude_code_thinking
        self._announced = False
        self.last_run_identity: ClaudeCodeRunIdentity | None = None
        self.messages = _ClaudeCodeMessages(self)

    def announce_once(self, identity: "ClaudeCodeRunIdentity") -> None:
        """Emit the run-identity banner the first time this client generates.

        Once per client, not once per call. #359 learned this the expensive
        way on the Codex side: a per-call print flooded streamed polish output,
        and a fan-out to 40 scenes would put 40 identical banners into one
        stream. stderr because subprocess_runner merges it into the stream the
        UI already renders, while leaving stdout clean for CLI piping.
        """
        # Recorded even on a repeat call: `last_run_identity` is what the
        # Connection Graph renders, and it must describe the LATEST call, not
        # the first one that happened to print.
        self.last_run_identity = identity
        if self._announced:
            return
        self._announced = True
        print(identity.banner(), file=sys.stderr, flush=True)
