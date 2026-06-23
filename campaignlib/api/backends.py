"""LLM client adapters: OpenAI-compatible (DGX/vLLM) and Claude Code (subscription).

Each presents the small slice of the anthropic SDK surface that
campaignlib.api.client (stream_api / call_api) depends on.
"""

import json
import os


DGX_DEFAULT_MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"


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

CLAUDE_CODE_CLI = os.environ.get("CG_CLAUDE_CLI", "claude")


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
    *, system, user: str, model: str, max_tokens: int | None = None
) -> str:
    """Invoke `claude -p` headless and return the assistant text.

    System prompt is passed via a temp file (--system-prompt-file) so a large
    cached prefix doesn't blow ARG_MAX; the user prompt is piped on stdin for
    the same reason. ANTHROPIC_API_KEY is stripped so billing lands on the
    subscription, not the metered API.

    `claude -p` has no output-length CLI flag, but it honors the
    CLAUDE_CODE_MAX_OUTPUT_TOKENS env var. We forward the caller's `max_tokens`
    through it so the subscription path respects the same ceiling the Anthropic
    API and DGX backends do (a ceiling, not a target — it permits longer output,
    it does not force it).
    """
    import subprocess
    import tempfile

    sys_text = _blocks_to_text(system)
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    if max_tokens:
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_tokens)

    cmd = [
        CLAUDE_CODE_CLI, "-p",
        "--model", model,
        "--output-format", "json",
        "--disallowed-tools", "*",   # pure text generation; no agentic tool calls
    ]
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
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude -p exited {proc.returncode}: "
                f"{(proc.stderr or proc.stdout).strip()[:500]}")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"claude -p returned non-JSON output: {proc.stdout[:300]!r}") from e
        if data.get("is_error"):
            result_text = str(data.get("result", ""))
            # Unlike the Anthropic API (which truncates and returns partial text
            # with stop_reason=max_tokens), `claude -p` treats hitting the cap as
            # a hard error and discards the text. Re-phrase its env-var-centric
            # message in terms of the caller's knob (--narrate-tokens / max_tokens).
            if max_tokens and "output token maximum" in result_text:
                raise RuntimeError(
                    f"claude -p hit the {max_tokens}-token output ceiling and "
                    f"returned no text (the subscription backend errors on "
                    f"overflow rather than truncating). Raise --narrate-tokens / "
                    f"max_tokens for this run.")
            raise RuntimeError(f"claude -p error: {result_text[:500]}")
        return data.get("result", "")
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

    def __init__(self, *, system, user: str, model: str, max_tokens: int | None = None):
        self._system = system
        self._user = user
        self._model = model
        self._max_tokens = max_tokens
        self._text = ""

    def __enter__(self):
        self._text = _claude_code_generate(
            system=self._system, user=self._user, model=self._model,
            max_tokens=self._max_tokens)
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

    def create(self, *, model, max_tokens, system, messages, tools=None, **_ignored):
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
        )
        return _OpenAICompatResponse(text)

    def stream(self, *, model, max_tokens, system, messages, **_ignored):
        return _ClaudeCodeStream(
            system=system,
            user=_messages_user_text(messages),
            model=self._resolve_model(model),
            max_tokens=max_tokens,
        )


class _ClaudeCodeClient:
    """Anthropic-shaped façade over `claude -p` (Pro/Max subscription billing).

    Supports only the single-turn text-in/text-out shapes used by call_api and
    stream_api. Tools, vision, batching, and real streaming are unsupported.
    """

    def __init__(self, model_override: str | None = None):
        self.model_override = model_override or os.environ.get("CG_CLAUDE_CODE_MODEL")
        self.messages = _ClaudeCodeMessages(self)
