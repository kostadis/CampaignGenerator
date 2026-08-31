"""Process-backed fake codex executable for adapter contract tests.

Mocking subprocess.run cannot prove the child receives the isolated cwd,
sanitized environment, stdin transcript, and exact command line. FakeCodexCli
installs a tiny executable in a temporary directory and records those values
as JSON lines while returning a configured direct or structured response.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import textwrap
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union


_SCRIPT = textwrap.dedent(
    r"""
    #!/usr/bin/env python3
    import json
    import os
    from pathlib import Path
    import sys
    import time

    config_path = Path(
        os.environ.get("CG_FAKE_CODEX_CONFIG", __CG_FAKE_CONFIG_PATH__)
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    record_path = Path(config["record_path"])
    index_path = Path(config["index_path"])
    try:
        index = int(index_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        index = 0
    index_path.write_text(str(index + 1), encoding="utf-8")

    args = sys.argv[1:]
    stdin = sys.stdin.read()
    result_arg = None
    if "--output-last-message" in args:
        position = args.index("--output-last-message") + 1
        if position < len(args):
            result_arg = args[position]

    responses = config.get("responses") or [{}]
    response = responses[min(index, len(responses) - 1)]
    if not isinstance(response, dict):
        response = {"text": str(response)}
    record = {
        "argv": args,
        "cwd": os.getcwd(),
        "stdin": stdin,
        "env": dict(os.environ),
        "output_last_message": result_arg,
        "structured": "--output-schema" in args,
        "response_index": index,
    }
    with record_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    delay = response.get("delay_seconds", config.get("delay_seconds", 0))
    if delay:
        time.sleep(float(delay))

    if response.get("write_result", True) and result_arg is not None:
        result_path = Path(result_arg)
        if response.get("raw_result") is not None:
            output = str(response["raw_result"])
        elif "payload" in response or "tool_calls" in response:
            payload = response.get("payload")
            if payload is None:
                payload = {
                    "text": response.get("text", ""),
                    "tool_calls": response.get("tool_calls", []),
                }
            output = json.dumps(payload, ensure_ascii=False)
        else:
            output = str(response.get("text", ""))
        result_path.write_text(output, encoding="utf-8")

    stdout = response.get("stdout", config.get("stdout", ""))
    stderr = response.get("stderr", config.get("stderr", ""))
    if stdout:
        sys.stdout.write(str(stdout))
    if stderr:
        sys.stderr.write(str(stderr))
    sys.exit(int(response.get("returncode", config.get("returncode", 0))))
    """
).lstrip()


@dataclass(frozen=True)
class CodexInvocation:
    """One invocation captured from the fake child process."""

    argv: List[str]
    cwd: Path
    stdin: str
    env: Dict[str, str]
    output_last_message: Optional[Path]
    structured: bool
    response_index: int

    @property
    def command(self) -> List[str]:
        return self.argv

    @property
    def input(self) -> str:
        return self.stdin

    @property
    def config_values(self) -> List[str]:
        """Return each separated ``-c`` value in child argv order."""
        return [
            self.argv[index + 1]
            for index, value in enumerate(self.argv[:-1])
            if value == "-c"
        ]

    def config_value(self, key: str) -> Optional[str]:
        """Return one config value by key, rejecting duplicate overrides."""
        prefix = f"{key}="
        matches = [
            value[len(prefix):]
            for value in self.config_values
            if value.startswith(prefix)
        ]
        if len(matches) > 1:
            raise AssertionError(f"duplicate Codex config override for {key!r}")
        return matches[0] if matches else None

    @property
    def reasoning_effort(self) -> Optional[str]:
        """Return the raw TOML value sent for ``model_reasoning_effort``."""
        return self.config_value("model_reasoning_effort")


Response = Union[str, Mapping[str, Any]]


class FakeCodexCli:
    """Create and manage an executable fake codex command.

    Responses are consumed in order, one per child process. If more processes
    are started than configured responses, the last response is repeated. A
    response can be a direct string, a mapping from direct/structured, or a
    custom mapping with returncode, stderr, delay_seconds, write_result, and
    raw_result fields for failure-path tests.
    """

    config_variable = "CG_FAKE_CODEX_CONFIG"

    def __init__(
        self,
        tmp_path: Union[str, os.PathLike[str]],
        *,
        responses: Optional[Iterable[Response]] = None,
        response: Optional[Response] = None,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        delay_seconds: float = 0,
        executable_name: str = "codex",
    ) -> None:
        base = Path(tmp_path)
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="fake_codex_", dir=str(base)))
        self.executable = self.root / executable_name
        self.record_path = self.root / "invocations.jsonl"
        self.index_path = self.root / "response-index"
        self.config_path = self.root / "config.json"
        self._previous_path: Optional[str] = None
        self._previous_config: Optional[str] = None

        if responses is None:
            responses = [
                response if response is not None else self.direct("fake codex response")
            ]
        normalized: List[Dict[str, Any]] = []
        for item in responses:
            if isinstance(item, str):
                normalized.append(dict(self.direct(item)))
            elif isinstance(item, Mapping):
                normalized.append(dict(item))
            else:
                raise TypeError("fake Codex responses must be strings or mappings")
        if not normalized:
            normalized = [dict(self.direct("fake codex response"))]

        self.config_path.write_text(
            json.dumps(
                {
                    "record_path": str(self.record_path),
                    "index_path": str(self.index_path),
                    "responses": normalized,
                    "returncode": returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "delay_seconds": delay_seconds,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        script = _SCRIPT.replace("__CG_FAKE_CONFIG_PATH__", repr(str(self.config_path)))
        self.executable.write_text(script, encoding="utf-8")
        self.executable.chmod(
            self.executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )

    @staticmethod
    def direct(text: str = "fake codex response", **overrides: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {"text": text}
        result.update(overrides)
        return result

    @staticmethod
    def structured(
        text: str = "",
        *,
        tool_calls: Optional[Sequence[Mapping[str, Any]]] = None,
        payload: Optional[Mapping[str, Any]] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {"text": text, "tool_calls": list(tool_calls or [])}
        if payload is not None:
            result["payload"] = dict(payload)
        result.update(overrides)
        return result

    @staticmethod
    def rejected(
        stderr: str = "unsupported model/reasoning effort combination",
        *,
        returncode: int = 2,
        **overrides: Any,
    ) -> Dict[str, Any]:
        """Build a response that rejects before producing a result artifact."""
        result: Dict[str, Any] = {
            "returncode": returncode,
            "stderr": stderr,
            "write_result": False,
        }
        result.update(overrides)
        return result

    @property
    def path(self) -> Path:
        return self.root

    def environment(self, base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
        """Return an environment resolving codex to this fake."""

        env = dict(os.environ if base is None else base)
        env[self.config_variable] = str(self.config_path)
        env["PATH"] = str(self.root) + os.pathsep + env.get("PATH", "")
        return env

    def install(self, monkeypatch: Any = None) -> "FakeCodexCli":
        """Expose the fake through PATH, optionally using pytest monkeypatch."""

        env = self.environment()
        if monkeypatch is None:
            self._previous_path = os.environ.get("PATH")
            self._previous_config = os.environ.get(self.config_variable)
            os.environ.update(env)
        else:
            monkeypatch.setenv("PATH", env["PATH"])
            monkeypatch.setenv(self.config_variable, env[self.config_variable])
        return self

    def __enter__(self) -> "FakeCodexCli":
        self.install()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if self._previous_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._previous_path
        if self._previous_config is None:
            os.environ.pop(self.config_variable, None)
        else:
            os.environ[self.config_variable] = self._previous_config
        return False

    @property
    def calls(self) -> List[CodexInvocation]:
        """Read captured child invocations in execution order."""

        if not self.record_path.exists():
            return []
        calls: List[CodexInvocation] = []
        for line in self.record_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            output = item.get("output_last_message")
            calls.append(
                CodexInvocation(
                    argv=list(item["argv"]),
                    cwd=Path(item["cwd"]),
                    stdin=item["stdin"],
                    env=dict(item["env"]),
                    output_last_message=Path(output) if output else None,
                    structured=bool(item["structured"]),
                    response_index=int(item["response_index"]),
                )
            )
        return calls

    @property
    def invocations(self) -> List[CodexInvocation]:
        return self.calls

    @property
    def call_count(self) -> int:
        """Number of child processes observed so far."""
        return len(self.calls)

    @property
    def last_call(self) -> Optional[CodexInvocation]:
        return self.calls[-1] if self.calls else None

    def wait_for_calls(self, count: int, timeout: float = 5.0) -> List[CodexInvocation]:
        """Wait briefly for asynchronous code to launch count children."""

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            calls = self.calls
            if len(calls) >= count:
                return calls
            time.sleep(0.01)
        return self.calls

    def clear(self) -> None:
        self.record_path.unlink(missing_ok=True)
        self.index_path.unlink(missing_ok=True)


def fake_codex_cli(
    tmp_path: Union[str, os.PathLike[str]], **kwargs: Any
) -> FakeCodexCli:
    return FakeCodexCli(tmp_path, **kwargs)


__all__ = ["CodexInvocation", "FakeCodexCli", "fake_codex_cli"]
