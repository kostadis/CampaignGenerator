"""Anthropic-shaped adapter over ``codex exec`` subscription authentication.

This module is the sole CampaignGenerator boundary to the Codex CLI.  It accepts
only the single-turn, text-only request used by consistency audits and launches
one fail-closed, ephemeral subprocess with no shell or provider fallback.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path


CODEX_CLI = "codex"
DEFAULT_CODEX_TIMEOUT = 600.0
_MAX_DIAGNOSTIC_CHARS = 1000

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


class CodexCliError(RuntimeError):
    """Actionable, non-retryable failure at the Codex subscription boundary."""


class _CodexTextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


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
    if not isinstance(system, str):
        raise CodexCliError(
            "codex-cli system instructions must be one text string"
        )
    if not system.strip():
        raise CodexCliError("codex-cli system instructions must not be empty")
    return system


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
             model: str | None) -> list[str]:
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
    if model is not None:
        cmd.extend(("--model", model))
    cmd.append("-")
    return cmd


def _codex_cli_generate(*, system, user: str, model: str | None) -> str:
    system_text = _system_text(system)
    selected_model = _selected_model(model)
    timeout = _timeout_seconds()
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)

    with tempfile.TemporaryDirectory(prefix="cg_codex_cli_") as temp_name:
        temp_dir = Path(temp_name)
        result_path = temp_dir / "final-message.md"
        cmd = _command(
            system=system_text,
            temp_dir=temp_dir,
            result_path=result_path,
            model=selected_model,
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


class _CodexCliClient:
    """Small Anthropic-shaped facade over ``codex exec`` subscription use."""

    def __init__(self, model_override: str | None = None):
        self.model_override = model_override
        self.messages = _CodexCliMessages(self)


__all__ = ["CodexCliError", "_CodexCliClient"]
