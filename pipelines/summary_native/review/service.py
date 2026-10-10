"""CLI-owned lifecycle for the dedicated private review service."""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

from campaignlib.review_config import ReviewConfig, load_campaign_review_config
from pipelines.summary_native.review.store import ReviewStoreError, read_snapshot


_OWNED_PROCESSES: dict[tuple[str, str], subprocess.Popen] = {}


def _runtime_dir(root: Path) -> Path:
    return root / ".review-runtime"


def handle_path(root: Path, review_id: str) -> Path:
    if not review_id or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for char in review_id
    ):
        raise ReviewStoreError("REVIEW_ID: invalid opaque review id")
    runtime = _runtime_dir(Path(root).resolve())
    if runtime.is_symlink():
        raise ReviewStoreError("REVIEW_SERVICE_INVALID: runtime directory cannot be a symlink")
    handle = runtime / f"{review_id}.json"
    if handle.is_symlink():
        raise ReviewStoreError("REVIEW_SERVICE_INVALID: runtime handle cannot be a symlink")
    return handle


def _runtime_fd(root: Path, *, create: bool) -> int | None:
    """Open the private runtime directory without following a symlink.

    Path prechecks alone leave a check/use window before chmod, replace, read,
    or unlink.  All runtime mutations therefore use this descriptor as their
    filesystem anchor.
    """

    root = Path(root).resolve()
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    root_fd = os.open(root, directory_flags)
    try:
        if create:
            try:
                os.mkdir(".review-runtime", 0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
        try:
            runtime_fd = os.open(
                ".review-runtime",
                directory_flags | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ReviewStoreError(
                "REVIEW_SERVICE_INVALID: runtime directory must be a private real directory"
            ) from exc
    finally:
        os.close(root_fd)
    if not stat.S_ISDIR(os.fstat(runtime_fd).st_mode):
        os.close(runtime_fd)
        raise ReviewStoreError("REVIEW_SERVICE_INVALID: runtime path is not a directory")
    os.fchmod(runtime_fd, 0o700)
    return runtime_fd


def _handle_parts(path: Path) -> tuple[Path, str]:
    path = Path(path)
    root = path.parent.parent.resolve()
    if path.parent != root / ".review-runtime" or not path.name.endswith(".json"):
        raise ReviewStoreError("REVIEW_SERVICE_INVALID: handle path is not campaign-local")
    review_id = path.name.removesuffix(".json")
    expected = handle_path(root, review_id)
    if expected != path:
        raise ReviewStoreError("REVIEW_SERVICE_INVALID: handle path is invalid")
    return root, path.name


def _process_identity(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        remainder = stat[stat.rfind(")") + 2 :].split()
        if remainder[0] == "Z":
            return None
        start_ticks = remainder[19]
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        return f"{boot_id}:{start_ticks}"
    except (OSError, IndexError, ValueError):
        return None


def _write_handle(path: Path, value: dict) -> None:
    root, name = _handle_parts(path)
    runtime_fd = _runtime_fd(root, create=True)
    assert runtime_fd is not None
    temporary = f".{name}.{secrets.token_hex(8)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600, dir_fd=runtime_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            existing = os.stat(name, dir_fd=runtime_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and stat.S_ISLNK(existing.st_mode):
            raise ReviewStoreError("REVIEW_SERVICE_INVALID: runtime handle cannot be a symlink")
        os.replace(
            temporary,
            name,
            src_dir_fd=runtime_fd,
            dst_dir_fd=runtime_fd,
        )
        handle_fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=runtime_fd,
        )
        try:
            os.fchmod(handle_fd, 0o600)
        finally:
            os.close(handle_fd)
        os.fsync(runtime_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=runtime_fd)
        except FileNotFoundError:
            pass
        os.close(runtime_fd)


def _read_handle(root: Path, review_id: str) -> dict | None:
    path = handle_path(root, review_id)
    runtime_fd = _runtime_fd(Path(root).resolve(), create=False)
    if runtime_fd is None:
        return None
    try:
        try:
            fd = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=runtime_fd,
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ReviewStoreError(
                "REVIEW_SERVICE_INVALID: runtime handle must be a private real file"
            ) from exc
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (UnicodeError, json.JSONDecodeError):
        return None
    finally:
        os.close(runtime_fd)
    return value if isinstance(value, dict) else None


def _unlink_handle(root: Path, review_id: str) -> bool:
    path = handle_path(root, review_id)
    runtime_fd = _runtime_fd(Path(root).resolve(), create=False)
    if runtime_fd is None:
        return False
    try:
        try:
            existing = os.stat(path.name, dir_fd=runtime_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(existing.st_mode):
            raise ReviewStoreError("REVIEW_SERVICE_INVALID: runtime handle cannot be a symlink")
        os.unlink(path.name, dir_fd=runtime_fd)
        os.fsync(runtime_fd)
        return True
    finally:
        os.close(runtime_fd)


def _is_live(handle: dict) -> bool:
    pid = handle.get("pid")
    identity = handle.get("process_identity")
    return type(pid) is int and isinstance(identity, str) and _process_identity(pid) == identity


def _reap_owned(root: Path, review_id: str) -> subprocess.Popen | None:
    key = (str(root), review_id)
    process = _OWNED_PROCESSES.get(key)
    if process is not None and process.poll() is not None:
        process.wait()
        _OWNED_PROCESSES.pop(key, None)
        return None
    return process


def _endpoint_config(root: Path, *, host: str, port: int, origin: str) -> ReviewConfig:
    base = load_campaign_review_config(root)
    try:
        return ReviewConfig.model_validate(
            {**base.model_dump(), "bind_host": host, "port": port, "origin": origin}
        )
    except ValueError as exc:
        raise ReviewStoreError(f"REVIEW_SERVICE_INVALID: {exc}") from exc


def _tls(cert: str | None, key: str | None) -> tuple[str | None, str | None]:
    if (cert is None) != (key is None):
        raise ReviewStoreError("REVIEW_SERVICE_INVALID: --tls-cert and --tls-key are required together")
    if cert is None:
        return None, None
    cert_path, key_path = Path(cert).expanduser().resolve(), Path(key).expanduser().resolve()
    if not cert_path.is_file() or not key_path.is_file():
        raise ReviewStoreError("REVIEW_SERVICE_INVALID: TLS certificate or key does not exist")
    return str(cert_path), str(key_path)


def serve_foreground(
    campaign_dir: Path,
    review_id: str,
    *,
    host: str,
    port: int,
    origin: str,
    tls_cert: str | None = None,
    tls_key: str | None = None,
    json_output: bool = False,
) -> int:
    """Run one foreground service. Uvicorn access logging stays disabled."""

    root = Path(campaign_dir).resolve()
    read_snapshot(root, review_id)
    config = _endpoint_config(root, host=host, port=port, origin=origin)
    cert, key = _tls(tls_cert, tls_key)
    current = _read_handle(root, review_id)
    if current is not None and _is_live(current) and current.get("pid") != os.getpid():
        raise ReviewStoreError("REVIEW_SERVICE_RUNNING: a service is already active for this review")

    from pipelines.summary_native.review.web.app import create_review_app

    app = create_review_app(root, review_id, config)
    nonce = secrets.token_urlsafe(24)
    handle = {
        "version": 1,
        "pid": os.getpid(),
        "process_identity": _process_identity(os.getpid()),
        "review_id": review_id,
        "host": config.bind_host,
        "port": config.port,
        "origin": config.origin,
        "readiness_nonce": nonce,
        "tls": cert is not None,
    }

    @app.on_event("startup")
    async def _ready() -> None:
        _write_handle(handle_path(root, review_id), handle)
        payload = {
            "ok": True,
            "code": "REVIEW_SERVICE_READY",
            "message": "Review service is ready.",
            "artifacts": [],
            "data": {key: handle[key] for key in ("review_id", "host", "port", "origin", "pid")},
        }
        print(
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
            if json_output
            else f"Review service ready at {config.origin}",
            flush=True,
        )

    import uvicorn

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((host, port))
        listener.listen(2048)
        listener.setblocking(False)
    except OSError as exc:
        listener.close()
        raise ReviewStoreError("REVIEW_SERVICE_BIND_FAILED: configured address is unavailable") from exc

    try:
        uvicorn_config = uvicorn.Config(
            app,
            host=config.bind_host,
            port=config.port,
            access_log=False,
            log_level="critical",
            ssl_certfile=cert,
            ssl_keyfile=key,
        )
        uvicorn.Server(uvicorn_config).run(sockets=[listener])
    finally:
        listener.close()
        latest = _read_handle(root, review_id)
        if latest is not None and latest.get("readiness_nonce") == nonce:
            _unlink_handle(root, review_id)
    return 0


def _serve_command(
    root: Path,
    review_id: str,
    *,
    host: str,
    port: int,
    origin: str,
    tls_cert: str | None,
    tls_key: str | None,
) -> list[str]:
    command = [
        sys.executable,
        "-c",
        "import sys; from pipelines.summary_native.cli import main; raise SystemExit(main(sys.argv[1:]))",
        "review",
        "serve",
        review_id,
        "--host",
        host,
        "--port",
        str(port),
        "--origin",
        origin,
        "--campaign-dir",
        str(root),
        "--json",
    ]
    if tls_cert is not None and tls_key is not None:
        command += ["--tls-cert", tls_cert, "--tls-key", tls_key]
    return command


def start_service(
    campaign_dir: Path,
    review_id: str,
    *,
    host: str,
    port: int,
    origin: str,
    tls_cert: str | None = None,
    tls_key: str | None = None,
) -> dict:
    root = Path(campaign_dir).resolve()
    read_snapshot(root, review_id)
    _endpoint_config(root, host=host, port=port, origin=origin)
    _tls(tls_cert, tls_key)
    existing = _read_handle(root, review_id)
    if existing is not None and _is_live(existing):
        raise ReviewStoreError("REVIEW_SERVICE_RUNNING: a service is already active for this review")
    process = subprocess.Popen(
        _serve_command(
            root,
            review_id,
            host=host,
            port=port,
            origin=origin,
            tls_cert=tls_cert,
            tls_key=tls_key,
        ),
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    _OWNED_PROCESSES[(str(root), review_id)] = process
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _reap_owned(root, review_id)
            raise ReviewStoreError("REVIEW_SERVICE_FAILED: service exited before readiness")
        handle = _read_handle(root, review_id)
        if handle is not None and handle.get("pid") == process.pid and _is_live(handle):
            try:
                with socket.create_connection((host, port), timeout=0.2):
                    return {key: handle[key] for key in ("review_id", "host", "port", "origin", "pid")}
            except OSError:
                pass
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    _reap_owned(root, review_id)
    raise ReviewStoreError("REVIEW_SERVICE_FAILED: readiness deadline expired")


def service_status(campaign_dir: Path, review_id: str) -> dict:
    root = Path(campaign_dir).resolve()
    _reap_owned(root, review_id)
    handle = _read_handle(root, review_id)
    if handle is None or not _is_live(handle):
        return {"review_id": review_id, "running": False}
    return {
        "review_id": review_id,
        "running": True,
        "host": handle.get("host"),
        "port": handle.get("port"),
        "origin": handle.get("origin"),
        "pid": handle.get("pid"),
    }


def stop_service(campaign_dir: Path, review_id: str) -> dict:
    root = Path(campaign_dir).resolve()
    owned = _reap_owned(root, review_id)
    handle = _read_handle(root, review_id)
    if handle is None or not _is_live(handle):
        _unlink_handle(root, review_id)
        return {"review_id": review_id, "running": False, "stopped": False}
    pid = int(handle["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if owned is not None and owned.pid == pid:
        try:
            owned.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        else:
            _OWNED_PROCESSES.pop((str(root), review_id), None)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _process_identity(pid) == handle.get("process_identity"):
        time.sleep(0.05)
    if _process_identity(pid) == handle.get("process_identity"):
        raise ReviewStoreError("REVIEW_SERVICE_STOP_FAILED: service did not stop")
    _unlink_handle(root, review_id)
    return {"review_id": review_id, "running": False, "stopped": True}
