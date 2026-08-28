"""Anthropic-shaped adapter over ``codex exec`` subscription authentication.

This module is the sole CampaignGenerator boundary to the Codex CLI.  Direct
requests are single-turn and text-only; brokered polish turns use a strict typed
transcript and structured result. Both launch one fail-closed, ephemeral
subprocess with no shell or provider fallback.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path


CODEX_CLI = "codex"
DEFAULT_CODEX_TIMEOUT = 600.0
_MAX_DIAGNOSTIC_CHARS = 1000

_BROKER_RESULT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://campaigngenerator.local/contracts/codex-brokered-turn.schema.json",
    "title": "CodexBrokeredTurnResult",
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "tool_calls"],
    "anyOf": [
        {"properties": {"text": {"minLength": 1}}},
        {"properties": {"tool_calls": {"minItems": 1}}},
    ],
    "properties": {
        "text": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "arguments_json"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "arguments_json": {"type": "string", "minLength": 2},
                },
            },
        },
    },
}

_DISABLED_FEATURES = (
    "apps",
    "hooks",
    "multi_agent",
    "plugins",
    "remote_plugin",
    "shell_tool",
    "skill_search",
    "skill_mcp_dependency_install",
    "workspace_dependencies",
    "tool_suggest",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "view_image",
    "code_mode_host",
)

_AUTH_FAILURE_MARKERS = (
    "authentication",
    "not logged in",
    "login required",
    "log in",
    "sign in",
    "unauthorized",
    "forbidden",
)

_MISSING = object()

_BROKER_PROTOCOL = """Broker protocol:
Return one JSON object matching the supplied output schema. The `text` field is
the response text and `tool_calls` contains host-operation requests only. Never
execute, invent, or describe tool results as completed work. Tool names are
opaque strings; arguments_json must be a JSON object encoded as a string.
"""


class CodexCliError(RuntimeError):
    """Actionable, non-retryable failure at the Codex subscription boundary."""


class _CodexTextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _CodexToolUseBlock:
    type = "tool_use"

    def __init__(self, *, tool_id: str, name: str, input: dict):
        self.id = tool_id
        self.name = name
        self.input = input


class _CodexUsage:
    """Trace-compatible usage facade; Codex subscription calls have no counts."""

    input_tokens = None
    output_tokens = None


class _CodexCliResponse:
    """Minimal response shape consumed by ``campaignlib.api.call_api``."""

    stop_reason = "end_turn"

    def __init__(self, text: str):
        self.content = [_CodexTextBlock(text)]


def _user_text(messages) -> str:
    if not isinstance(messages, list) or len(messages) != 1:
        raise CodexCliError(
            "codex-cli accepts exactly one text-only user message; "
            "multi-turn conversations are unsupported"
        )
    message = messages[0]
    if not isinstance(message, dict) or message.get("role") != "user":
        raise CodexCliError("codex-cli accepts exactly one user-role message")
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                raise CodexCliError(
                    "codex-cli accepts text-only content; images, tools, and "
                    "unknown content blocks are unsupported"
                )
            parts.append(block["text"])
        text = "".join(parts)
    else:
        raise CodexCliError(
            "codex-cli accepts text-only content; images and tools are unsupported"
        )
    if not text.strip():
        raise CodexCliError("codex-cli user content must not be empty")
    return text


def _system_text(system) -> str:
    """Normalize a string or ordered text-block system prompt.

    Anthropic's ``cache_control`` metadata is intentionally ignored: it is a
    provider hint, not prompt content.  Other block shapes remain unsupported
    so a caller cannot accidentally turn an image or tool block into text.
    """
    if isinstance(system, str):
        text = system
    elif isinstance(system, list):
        parts: list[str] = []
        for block in system:
            if not (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                raise CodexCliError(
                    "codex-cli system instructions accept text-only blocks"
                )
            parts.append(block["text"])
        text = "".join(parts)
    else:
        raise CodexCliError(
            "codex-cli system instructions must be a string or ordered text blocks"
        )
    if not text.strip():
        raise CodexCliError("codex-cli system instructions must not be empty")
    return text


def _selected_model(explicit: str | None) -> str | None:
    candidate = explicit
    if candidate is None or (isinstance(candidate, str) and not candidate.strip()):
        candidate = os.environ.get("CG_CODEX_MODEL")
    if candidate is None:
        return None
    if not isinstance(candidate, str):
        raise CodexCliError("codex-cli model must be a string when supplied")
    candidate = candidate.strip()
    if not candidate:
        return None
    if candidate.lower().startswith("claude-"):
        raise CodexCliError(
            f"codex-cli model is incompatible with Claude model {candidate!r}; "
            "choose a model supported by Codex or omit --model"
        )
    return candidate


def _field(value, name: str, default=_MISSING):
    """Read a field from either an SDK object or a plain mapping."""
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _reject_extra_fields(value, allowed: set[str], *, where: str) -> None:
    if not isinstance(value, Mapping):
        return
    extras = set(value) - allowed
    if extras:
        names = ", ".join(sorted(str(name) for name in extras))
        raise CodexCliError(
            f"codex-cli brokered {where} contains unsupported fields: {names}"
        )


def _text_block(block, *, where: str) -> dict:
    _reject_extra_fields(block, {"type", "text"}, where=where)
    if _field(block, "type") != "text":
        raise CodexCliError(
            f"codex-cli brokered {where} contains an unsupported block"
        )
    text = _field(block, "text")
    if not isinstance(text, str) or not text.strip():
        raise CodexCliError(
            f"codex-cli brokered {where} text must be a non-empty string"
        )
    return {"type": "text", "text": text}


def _tool_use_block(block, *, where: str) -> dict:
    _reject_extra_fields(block, {"type", "id", "name", "input"}, where=where)
    if _field(block, "type") != "tool_use":
        raise CodexCliError(
            f"codex-cli brokered {where} contains an unsupported block"
        )
    tool_id = _field(block, "id")
    name = _field(block, "name")
    arguments = _field(block, "input")
    if not isinstance(tool_id, str) or not tool_id.strip():
        raise CodexCliError("codex-cli brokered tool_use id must be non-empty")
    if not isinstance(name, str) or not name.strip():
        raise CodexCliError("codex-cli brokered tool_use name must be non-empty")
    if not isinstance(arguments, Mapping):
        raise CodexCliError(
            f"codex-cli brokered {where} tool_use input must be an object"
        )
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": name,
        "input": dict(arguments),
    }


def _tool_result_block(block, *, where: str) -> dict:
    _reject_extra_fields(
        block,
        {"type", "tool_use_id", "content", "is_error"},
        where=where,
    )
    if _field(block, "type") != "tool_result":
        raise CodexCliError(
            f"codex-cli brokered {where} contains an unsupported block"
        )
    tool_id = _field(block, "tool_use_id")
    content = _field(block, "content")
    is_error = _field(block, "is_error")
    if not isinstance(tool_id, str) or not tool_id.strip():
        raise CodexCliError("codex-cli brokered tool_result id must be non-empty")
    if not isinstance(content, str):
        raise CodexCliError("codex-cli brokered tool_result content must be text")
    if is_error is _MISSING or not isinstance(is_error, bool):
        raise CodexCliError(
            "codex-cli brokered tool_result is_error must be boolean"
        )
    return {
        "type": "tool_result",
        "tool_use_id": tool_id,
        "content": content,
        "is_error": is_error,
    }


def _broker_transcript(messages) -> str:
    """Normalize and validate the complete typed broker history.

    Anthropic SDK response blocks and the dictionaries produced by the parent
    polish loop are both accepted. Tool requests must be made by an assistant,
    and each result must resolve exactly one outstanding request in order.
    """
    if not isinstance(messages, list) or not messages:
        raise CodexCliError("codex-cli brokered history must not be empty")

    normalized = []
    requested: dict[str, None] = {}
    resolved: set[str] = set()
    for message_index, message in enumerate(messages):
        _reject_extra_fields(message, {"role", "content"}, where="message")
        role = _field(message, "role")
        if role not in ("user", "assistant"):
            raise CodexCliError(
                "codex-cli brokered history accepts only user and assistant roles"
            )
        content = _field(message, "content")
        if isinstance(content, str):
            blocks = [_text_block({"type": "text", "text": content}, where="history")]
        elif isinstance(content, list) and content:
            blocks = []
            for block in content:
                block_type = _field(block, "type")
                where = f"message {message_index + 1}"
                if block_type == "text":
                    blocks.append(_text_block(block, where=where))
                elif block_type == "tool_use" and role == "assistant":
                    normalized_block = _tool_use_block(block, where=where)
                    tool_id = normalized_block["id"]
                    if tool_id in requested or tool_id in resolved:
                        raise CodexCliError(
                            f"codex-cli brokered duplicate tool_use id {tool_id!r}"
                        )
                    requested[tool_id] = None
                    blocks.append(normalized_block)
                elif block_type == "tool_result" and role == "user":
                    normalized_block = _tool_result_block(block, where=where)
                    tool_id = normalized_block["tool_use_id"]
                    if tool_id in resolved:
                        raise CodexCliError(
                            f"codex-cli brokered duplicate tool_result for {tool_id!r}"
                        )
                    if tool_id not in requested:
                        raise CodexCliError(
                            f"codex-cli brokered tool_result references unknown tool_use id {tool_id!r}"
                        )
                    del requested[tool_id]
                    resolved.add(tool_id)
                    blocks.append(normalized_block)
                else:
                    raise CodexCliError(
                        f"codex-cli brokered {role} message contains an unsupported block"
                    )
        else:
            raise CodexCliError(
                "codex-cli brokered history messages require non-empty content"
            )
        normalized.append({"role": role, "blocks": blocks})

    if requested:
        unresolved = ", ".join(sorted(requested))
        raise CodexCliError(
            f"codex-cli brokered history has unresolved tool_use ids: {unresolved}"
        )
    return json.dumps(
        {"version": "codex-brokered-v1", "messages": normalized},
        ensure_ascii=False,
    )


def _broker_developer_instructions(system: str, tools) -> str:
    """Keep campaign instructions separate from the fixed broker protocol."""
    try:
        schemas = json.dumps(tools, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise CodexCliError("codex-cli brokered tool schemas are not JSON data") from exc
    return (
        "Campaign system instructions (highest priority):\n"
        f"{system}\n\n"
        f"{_BROKER_PROTOCOL}\n"
        "Declared host tool schemas (descriptive only; never execute tools):\n"
        f"{schemas}"
    )


def _brokered_response(raw: str):
    """Convert a validated structured child envelope to Anthropic-shaped blocks."""
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CodexCliError("codex-cli brokered result is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise CodexCliError("codex-cli brokered result must be a JSON object")
    if set(payload) - {"text", "tool_calls"}:
        raise CodexCliError("codex-cli brokered result contains unknown fields")
    text = payload.get("text")
    calls = payload.get("tool_calls")
    if not isinstance(text, str) or not isinstance(calls, list):
        raise CodexCliError(
            "codex-cli brokered result requires string text and tool_calls array"
        )
    if not text.strip() and not calls:
        raise CodexCliError("codex-cli brokered result is empty")
    content = []
    if text:
        content.append(_CodexTextBlock(text))
    for call in calls:
        if not isinstance(call, dict) or set(call) != {"name", "arguments_json"}:
            raise CodexCliError("codex-cli brokered tool call has an invalid shape")
        name = call["name"]
        arguments_json = call["arguments_json"]
        if not isinstance(name, str) or not name.strip():
            raise CodexCliError("codex-cli brokered tool call name must not be empty")
        if not isinstance(arguments_json, str) or len(arguments_json) < 2:
            raise CodexCliError("codex-cli brokered tool arguments are invalid JSON")
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as exc:
            raise CodexCliError(
                f"codex-cli brokered arguments for {name!r} are invalid JSON"
            ) from exc
        if not isinstance(arguments, dict):
            raise CodexCliError(
                f"codex-cli brokered arguments for {name!r} must be an object"
            )
        content.append(
            _CodexToolUseBlock(
                tool_id=f"codex_{uuid.uuid4().hex}",
                name=name,
                input=arguments,
            )
        )
    if not content:
        raise CodexCliError("codex-cli brokered result is empty")
    response = type("_CodexBrokeredResponse", (), {})()
    response.content = content
    response.stop_reason = "tool_use" if calls else "end_turn"
    response.usage = _CodexUsage()
    return response


def _timeout_seconds() -> float:
    raw = os.environ.get("CG_CODEX_TIMEOUT", str(int(DEFAULT_CODEX_TIMEOUT)))
    try:
        timeout = float(raw)
    except (TypeError, ValueError) as exc:
        raise CodexCliError(
            "CG_CODEX_TIMEOUT must be a positive finite number of seconds"
        ) from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise CodexCliError(
            "CG_CODEX_TIMEOUT must be a positive finite number of seconds"
        )
    return timeout


def _bounded_diagnostic(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value or "").strip()
    if not text:
        return "no diagnostic output"
    if len(text) > _MAX_DIAGNOSTIC_CHARS:
        return text[:_MAX_DIAGNOSTIC_CHARS] + "…"
    return text


def _command(*, system: str, temp_dir: Path, result_path: Path,
             model: str | None, output_schema_path: Path | None = None) -> list[str]:
    cmd = [
        CODEX_CLI,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--cd",
        str(temp_dir),
        "--color",
        "never",
        "-c",
        'approval_policy="never"',
        "-c",
        'forced_login_method="chatgpt"',
        "-c",
        'web_search="disabled"',
        "-c",
        "tools.web_search=false",
        "-c",
        "apps._default.enabled=false",
        "-c",
        "agents.enabled=false",
        "-c",
        "project_doc_max_bytes=0",
    ]
    for feature in _DISABLED_FEATURES:
        cmd.extend(("--disable", feature))
    cmd.extend((
        "-c",
        f"developer_instructions={json.dumps(system, ensure_ascii=False)}",
        "--output-last-message",
        str(result_path),
    ))
    if output_schema_path is not None:
        cmd.extend(("--output-schema", str(output_schema_path)))
    if model is not None:
        cmd.extend(("--model", model))
    cmd.append("-")
    return cmd


def _codex_cli_generate(*, system, user: str, model: str | None,
                        output_schema: dict | None = None) -> str:
    system_text = _system_text(system)
    selected_model = _selected_model(model)
    timeout = _timeout_seconds()
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)

    with tempfile.TemporaryDirectory(prefix="cg_codex_cli_") as temp_name:
        temp_dir = Path(temp_name)
        result_path = temp_dir / "final-message.md"
        output_schema_path = None
        if output_schema is not None:
            output_schema_path = temp_dir / "brokered-turn.schema.json"
            output_schema_path.write_text(
                json.dumps(output_schema, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        cmd = _command(
            system=system_text,
            temp_dir=temp_dir,
            result_path=result_path,
            model=selected_model,
            output_schema_path=output_schema_path,
        )
        try:
            proc = subprocess.run(
                cmd,
                input=user,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(temp_dir),
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise CodexCliError(
                "codex executable not found; install Codex CLI and run `codex login`"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexCliError(
                f"codex-cli timed out after {timeout:g} seconds "
                f"(CG_CODEX_TIMEOUT); {_bounded_diagnostic(exc.stderr)}"
            ) from exc

        if proc.returncode != 0:
            diagnostic = _bounded_diagnostic(proc.stderr or proc.stdout)
            if any(marker in diagnostic.lower() for marker in _AUTH_FAILURE_MARKERS):
                raise CodexCliError(
                    "codex-cli authentication failed; run `codex login` with a "
                    f"ChatGPT subscription. Codex said: {diagnostic}"
                )
            raise CodexCliError(
                f"codex-cli exited {proc.returncode}: {diagnostic}"
            )

        if not result_path.exists():
            raise CodexCliError(
                "codex-cli succeeded but its final result file is missing"
            )
        result = result_path.read_text(encoding="utf-8")
        if not result.strip():
            raise CodexCliError(
                "codex-cli succeeded but returned an empty final result"
            )
        return result


class _CodexCliStream:
    """One-chunk context manager matching the Anthropic stream surface."""

    def __init__(self, *, system, user: str, model: str | None):
        self._system = system
        self._user = user
        self._model = model
        self._text = ""

    def __enter__(self):
        self._text = _codex_cli_generate(
            system=self._system,
            user=self._user,
            model=self._model,
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def text_stream(self):
        def _iter():
            if self._text:
                yield self._text

        return _iter()


class _CodexCliMessages:
    def __init__(self, client: "_CodexCliClient"):
        self._client = client

    def _request(self, *, model, system, messages, tools=None):
        if tools:
            raise CodexCliError(
                "tool use is not supported on the codex-cli backend"
            )
        return (
            _system_text(system),
            _user_text(messages),
            self._client.model_override
            if self._client.model_override is not None
            else model,
        )

    def create(self, *, model, max_tokens, system, messages, tools=None,
               **_unsupported):
        del max_tokens  # codex exec exposes no output-token limit flag
        system_text, user, selected_model = self._request(
            model=model, system=system, messages=messages, tools=tools
        )
        text = _codex_cli_generate(
            system=system_text, user=user, model=selected_model
        )
        return _CodexCliResponse(text)

    def stream(self, *, model, max_tokens, system, messages, tools=None,
               **_unsupported):
        del max_tokens
        system_text, user, selected_model = self._request(
            model=model, system=system, messages=messages, tools=tools
        )
        return _CodexCliStream(
            system=system_text, user=user, model=selected_model
        )


class _CodexCliBrokeredMessages:
    """Structured host-brokered resource for the polish interaction shape."""

    def __init__(self, client: "_CodexCliClient"):
        self._client = client

    def create(self, *, model, max_tokens, system, messages, tools, **_unsupported):
        del max_tokens  # codex exec exposes no output-token limit flag
        system_text = _system_text(system)
        transcript = _broker_transcript(messages)
        developer_instructions = _broker_developer_instructions(system_text, tools)
        selected_model = (
            self._client.model_override
            if self._client.model_override is not None
            else model
        )
        raw = _codex_cli_generate(
            system=developer_instructions,
            user=transcript,
            model=selected_model,
            output_schema=_BROKER_RESULT_SCHEMA,
        )
        return _brokered_response(raw)


class _CodexCliClient:
    """Small Anthropic-shaped facade over ``codex exec`` subscription use."""

    def __init__(self, model_override: str | None = None):
        self.model_override = model_override
        self.messages = _CodexCliMessages(self)
        self.brokered_messages = _CodexCliBrokeredMessages(self)


__all__ = ["CodexCliError", "_CodexCliClient"]
