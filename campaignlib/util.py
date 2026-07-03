"""Clipboard and timestamped-log helpers."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    """Write text to path atomically (FR-014: no partial file at the trusted path).

    Writes to a temp file in the same directory as `path`, then renames via
    os.replace — a POSIX atomic rename on the same filesystem. A SIGKILL during
    write leaves at most a discardable .tmp file; the destination is always either
    the complete new content or the previous version, never a partial write.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path | str, obj: Any, indent: int = 2) -> None:
    """Write obj as JSON to path atomically (FR-014).

    Serialises as json.dumps(obj, indent=indent) + "\\n" to match the existing
    ensemble_merge.py output format exactly, then delegates to atomic_write_text.
    """
    atomic_write_text(path, json.dumps(obj, indent=indent) + "\n")


def copy_to_clipboard(text: str) -> None:
    try:
        import pyperclip
        pyperclip.copy(text)
        print(f"Copied to clipboard ({len(text):,} chars).")
    except ImportError:
        print("pyperclip not installed. Run: pip install pyperclip", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Clipboard error: {e}", file=sys.stderr)
        print("On WSL you may need: sudo apt install xclip", file=sys.stderr)
        sys.exit(1)


# ── Logging ───────────────────────────────────────────────────────────────────

def save_log(log_dir: str, sections: list[tuple[str, str]], stem: str = "session") -> Path:
    """Save a markdown log file.

    sections — list of (heading, content) tuples
    stem     — filename prefix (timestamp is prepended automatically)
    """
    log_path = Path(log_dir).expanduser()
    log_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = log_path / f"{timestamp}_{stem}.md"
    lines = [f"# Session Log — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    for heading, content in sections:
        lines += ["", "---", "", f"## {heading}", "", content.strip()]
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_file
