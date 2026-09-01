"""Clipboard and timestamped-log helpers."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    """Durably replace *path* with exact bytes using a sibling temporary file.

    The temporary file is private to this writer, flushed before replacement,
    and removed after every failed write.  Keeping it beside the destination
    makes :func:`os.replace` atomic on the destination filesystem.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Retain the established PID-suffixed sibling name: speculative workers
    # run in separate processes, and existing callers/tests rely on this
    # observable cleanup convention.
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        handle = os.fdopen(fd, "wb")
    except BaseException:
        os.close(fd)
        tmp.unlink(missing_ok=True)
        raise
    # From here the wrapper owns fd and closes it exactly once.  Closing the
    # raw number again after a failed os.replace() would reach whatever the
    # runtime has since reissued it to -- another open file or socket in this
    # same process, since the server runs these writes in a threadpool.
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Directory fsync is unavailable on a few supported filesystems.
            pass
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    """Write text to path atomically (FR-014: no partial file at the trusted path).

    Writes to a temp file in the same directory as `path`, then renames via
    os.replace — a POSIX atomic rename on the same filesystem. A SIGKILL during
    write leaves at most a discardable tmp file; the destination is always either
    the complete new content or the previous version, never a partial write.

    The tmp name carries the writer's PID because two processes can race on the
    same destination: the ensemble's speculative re-execution runs a duplicate
    of the same unit in another process sharing the cache dir and terminates
    the loser. A fixed tmp name would let those two interleave writes into the
    *same* tmp file before either rename; a per-writer name confines the race
    to the atomic rename, where last-writer-wins is harmless (both wrote the
    same content).
    """
    atomic_write_bytes(path, text.encode(encoding))


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
