"""Process-backed fake `claude` executable for claude-code adapter tests.

Mocking ``subprocess.run`` cannot prove the child receives the exact argv, the
sanitized environment (no ``ANTHROPIC_API_KEY``), or the thinking/output-token
variables. This installs a tiny executable in a temp directory, records what it
was handed as JSON lines, and emits a valid ``stream-json`` transcript so
``_claude_code_generate`` parses it the way it parses the real CLI.

Mirrors ``tests/helpers/fake_codex_cli.py``; feature 021.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SCRIPT = textwrap.dedent(
    r"""
    #!/usr/bin/env python3
    import json
    import os
    import sys
    from pathlib import Path

    record_path = Path(os.environ["CG_FAKE_CLAUDE_RECORD"])
    args = sys.argv[1:]

    # The system-prompt file is a per-run temp path; record the flag but
    # normalize the value so argv comparisons stay stable across runs.
    argv = []
    skip = False
    for arg in args:
        if skip:
            argv.append("<SYSPROMPT>")
            skip = False
            continue
        argv.append(arg)
        if arg == "--system-prompt-file":
            skip = True

    stdin = sys.stdin.read()
    with record_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "argv": argv,
            "stdin": stdin,
            "env": {
                "MAX_THINKING_TOKENS": os.environ.get("MAX_THINKING_TOKENS"),
                "CLAUDE_CODE_MAX_OUTPUT_TOKENS": os.environ.get(
                    "CLAUDE_CODE_MAX_OUTPUT_TOKENS"
                ),
                "ANTHROPIC_API_KEY_present": "ANTHROPIC_API_KEY" in os.environ,
            },
        }, sort_keys=True) + "\n")

    text = os.environ.get("CG_FAKE_CLAUDE_TEXT", "ok")
    print(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }))
    print(json.dumps({
        "type": "result", "result": text, "is_error": False, "num_turns": 1,
    }))
    """
).strip()


@dataclass
class Invocation:
    """One recorded `claude -p` child process."""

    argv: list[str]
    stdin: str
    env: dict[str, Any]

    def effort(self) -> str | None:
        """The value passed as ``--effort``, or None when the flag is absent.

        Absence is the interesting case: it means CampaignGenerator sent no
        override and the child resolved the operator's own settings.json.
        """
        if "--effort" not in self.argv:
            return None
        return self.argv[self.argv.index("--effort") + 1]

    def has_effort_flag(self) -> bool:
        return "--effort" in self.argv


class FakeClaudeCli:
    """Installs a fake `claude` and records every invocation.

    Usage::

        with FakeClaudeCli() as fake:
            # CLAUDE_CODE_CLI is resolved from CG_CLAUDE_CLI at import time,
            # so patch the module attribute rather than the environment.
            monkeypatch.setattr(backends, "CLAUDE_CODE_CLI", fake.path)
            ...
            assert fake.invocations[0].effort() == "high"
    """

    def __init__(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="cg_fake_claude_")
        root = Path(self._dir.name)
        self._record = root / "invocations.jsonl"
        self._record.touch()
        self.path = str(root / "claude")
        Path(self.path).write_text(_SCRIPT, encoding="utf-8")
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IEXEC | stat.S_IXGRP)

    def __enter__(self) -> "FakeClaudeCli":
        os.environ["CG_FAKE_CLAUDE_RECORD"] = str(self._record)
        return self

    def __exit__(self, *exc: object) -> bool:
        os.environ.pop("CG_FAKE_CLAUDE_RECORD", None)
        self._dir.cleanup()
        return False

    @property
    def invocations(self) -> list[Invocation]:
        lines = self._record.read_text(encoding="utf-8").splitlines()
        return [
            Invocation(argv=d["argv"], stdin=d["stdin"], env=d["env"])
            for d in (json.loads(line) for line in lines if line.strip())
        ]

    @property
    def spawned(self) -> int:
        """How many children actually started.

        The refusal tests assert this is zero — 'before any model work starts'
        means before the child process exists, and this is how that is proved
        rather than asserted.
        """
        return len(self.invocations)
