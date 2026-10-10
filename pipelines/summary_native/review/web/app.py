"""Capability-only HTTP adapter for the packaged review viewer."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from campaignlib.review_config import ReviewConfig
from pipelines.summary_native.review.access import authenticate_token
from pipelines.summary_native.review.models import AccessAction, AccessGrant, parse_json_strict
from pipelines.summary_native.review.store import ReviewStoreError
from server.subprocess_runner import BoundedJSONError, console_script, run_bounded_json


_ASSETS = {
    "viewer.js": ("text/javascript; charset=utf-8", "viewer.js"),
    "viewer.css": ("text/css; charset=utf-8", "viewer.css"),
}
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
    ),
}
_GENERIC_NOT_FOUND = {"ok": False, "code": "NOT_FOUND", "message": "Not found."}


def _not_found() -> JSONResponse:
    return JSONResponse(_GENERIC_NOT_FOUND, status_code=404)


def create_review_app(root: Path, review_id: str, config: ReviewConfig) -> FastAPI:
    root = Path(root).resolve()
    if config.origin is None:
        raise ReviewStoreError("REVIEW_SERVICE_INVALID: an explicit origin is required")
    expected_host = urlsplit(config.origin).netloc
    assets = Path(__file__).resolve().parent
    csrf_nonces: dict[str, tuple[str, float]] = {}
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def _boundary(request: Request, call_next):
        if request.headers.get("host") != expected_host:
            response: Response = _not_found()
        else:
            response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, _exc: StarletteHTTPException):
        return _not_found()

    @app.exception_handler(Exception)
    async def _safe_error(_request: Request, _exc: Exception):
        return JSONResponse(
            {"ok": False, "code": "REVIEW_SERVICE_ERROR", "message": "Review service failed safely."},
            status_code=503,
        )

    def authorized(capability: str, action: AccessAction) -> AccessGrant | None:
        return authenticate_token(root, review_id, capability, action=action)

    def safe_command_error(exc: BoundedJSONError) -> JSONResponse:
        payload = exc.payload if isinstance(exc.payload, dict) else {}
        supplied_code = payload.get("code")
        known_codes = {
            "REVIEW_UNKNOWN_ITEM",
            "REVIEW_PAGE_INVALID",
            "REVIEW_STALE_DECISION",
            "REVIEW_STALE_GENERATION",
            "REVIEW_STALE_CUSTODY",
            "REVIEW_REQUEST_ID_CONFLICT",
            "REVIEW_ACCESS_DENIED",
            "REVIEW_INVALID_BATCH",
            "REVIEW_RECOVERY_REQUIRED",
        }
        code = supplied_code if supplied_code in known_codes else "REVIEW_COMMAND_FAILED"
        if code in {"REVIEW_STALE_DECISION", "REVIEW_STALE_GENERATION", "REVIEW_STALE_CUSTODY", "REVIEW_REQUEST_ID_CONFLICT"}:
            status, message = 409, "Review state changed. Reload before trying again."
        elif code in {"REVIEW_ACCESS_DENIED", "REVIEW_UNKNOWN_ITEM"}:
            return _not_found()
        elif code in {"REVIEW_PAGE_INVALID", "REVIEW_INVALID_BATCH"}:
            status, message = 400, "Review request is invalid."
        else:
            status, message = 503, "Review command failed safely."
        return JSONResponse({"ok": False, "code": code, "message": message}, status_code=status)

    async def domain_json(*arguments: str) -> dict | JSONResponse:
        command = [
            console_script("summary_native"),
            "review",
            *arguments,
            "--campaign-dir",
            str(root),
            "--json",
        ]
        try:
            return await run_bounded_json(
                command,
                cwd=str(root),
                timeout_seconds=config.command_timeout_seconds,
                max_output_bytes=config.max_response_bytes,
                save_run_log=False,
            )
        except BoundedJSONError as exc:
            return safe_command_error(exc)

    def issue_csrf(grant: AccessGrant) -> str:
        now = time.monotonic()
        for digest, (_, expires) in tuple(csrf_nonces.items()):
            if expires <= now:
                csrf_nonces.pop(digest, None)
        nonce = secrets.token_urlsafe(32)
        csrf_nonces[hashlib.sha256(nonce.encode("ascii")).hexdigest()] = (
            grant.grant_id,
            now + 15 * 60,
        )
        return nonce

    def valid_csrf(grant: AccessGrant, nonce: str | None) -> bool:
        if not nonce:
            return False
        try:
            digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            return False
        stored = csrf_nonces.get(digest)
        return stored is not None and stored[0] == grant.grant_id and stored[1] > time.monotonic()

    @app.get("/r/{capability}/")
    async def shell(capability: str):
        grant = authorized(capability, AccessAction.READ_REVIEW)
        if grant is None:
            return _not_found()
        nonce = issue_csrf(grant)
        response = HTMLResponse((assets / "viewer.html").read_text(encoding="utf-8"))
        response.headers["X-Review-CSRF"] = nonce
        return response

    @app.get("/r/{capability}/assets/{name}")
    async def asset(capability: str, name: str):
        if authorized(capability, AccessAction.READ_REVIEW) is None:
            return _not_found()
        selected = _ASSETS.get(name)
        if selected is None:
            return _not_found()
        content_type, filename = selected
        return FileResponse(assets / filename, media_type=content_type)

    @app.get("/r/{capability}/review")
    async def review(capability: str, request: Request):
        if authorized(capability, AccessAction.READ_REVIEW) is None:
            return _not_found()
        cursor = request.query_params.get("cursor")
        limit_text = request.query_params.get("limit")
        if any(key not in {"cursor", "limit"} for key in request.query_params):
            return JSONResponse(
                {"ok": False, "code": "REVIEW_PAGE_INVALID", "message": "Review request is invalid."},
                status_code=400,
            )
        arguments = ["show", review_id]
        if cursor is not None:
            arguments += ["--cursor", cursor]
        if limit_text is not None:
            try:
                limit = int(limit_text)
            except ValueError:
                limit = 0
            if not 1 <= limit <= config.max_page_items:
                return JSONResponse(
                    {"ok": False, "code": "REVIEW_PAGE_INVALID", "message": "Review request is invalid."},
                    status_code=400,
                )
            arguments += ["--limit", str(limit)]
        result = await domain_json(*arguments)
        return result if isinstance(result, JSONResponse) else JSONResponse(result)

    @app.get("/r/{capability}/items/{item_id}")
    async def item(capability: str, item_id: str, request: Request):
        if authorized(capability, AccessAction.READ_REVIEW) is None:
            return _not_found()
        if any(key != "section_offset" for key in request.query_params):
            return JSONResponse({"ok": False, "code": "REVIEW_PAGE_INVALID", "message": "Review request is invalid."}, status_code=400)
        arguments = ["show", review_id, "--item", item_id]
        if "section_offset" in request.query_params:
            try:
                offset = int(request.query_params["section_offset"])
            except ValueError:
                offset = -1
            if offset < 0:
                return JSONResponse({"ok": False, "code": "REVIEW_PAGE_INVALID", "message": "Review request is invalid."}, status_code=400)
            arguments += ["--section-offset", str(offset)]
        result = await domain_json(*arguments)
        return result if isinstance(result, JSONResponse) else JSONResponse(result)

    @app.get("/r/{capability}/history/{item_id}")
    async def item_history(capability: str, item_id: str):
        if authorized(capability, AccessAction.READ_REVIEW) is None:
            return _not_found()
        # Authenticate first, then prove item membership through the bounded
        # show command before returning history from a second bounded command.
        exists = await domain_json("show", review_id, "--item", item_id)
        if isinstance(exists, JSONResponse):
            return exists
        result = await domain_json("history", review_id, "--item", item_id)
        return result if isinstance(result, JSONResponse) else JSONResponse(result)

    @app.post("/r/{capability}/decisions")
    async def decisions(capability: str, request: Request):
        grant = authorized(capability, AccessAction.SAVE_DECISION)
        if grant is None:
            return _not_found()
        if request.headers.get("origin") != config.origin:
            return JSONResponse(
                {"ok": False, "code": "REVIEW_ORIGIN_REQUIRED", "message": "Exact review origin required."},
                status_code=400,
            )
        if request.headers.get("sec-fetch-site") not in {None, "same-origin"}:
            return JSONResponse(
                {"ok": False, "code": "REVIEW_ORIGIN_REQUIRED", "message": "Same-origin browser request required."},
                status_code=400,
            )
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse(
                {"ok": False, "code": "REVIEW_JSON_REQUIRED", "message": "application/json required."},
                status_code=400,
            )
        if not valid_csrf(grant, request.headers.get("x-review-csrf")):
            return JSONResponse(
                {"ok": False, "code": "REVIEW_CSRF_REQUIRED", "message": "A current CSRF nonce is required."},
                status_code=400,
            )
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > config.max_request_bytes:
            return JSONResponse(
                {"ok": False, "code": "REVIEW_PAYLOAD_TOO_LARGE", "message": "Decision request is too large."},
                status_code=413,
            )
        chunks: list[bytes] = []
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > config.max_request_bytes:
                return JSONResponse(
                    {"ok": False, "code": "REVIEW_PAYLOAD_TOO_LARGE", "message": "Decision request is too large."},
                    status_code=413,
                )
            chunks.append(chunk)
        body = b"".join(chunks)
        try:
            value = parse_json_strict(body)
        except ValueError:
            value = None
        required_request = {"request_id", "review_generation", "reviewer", "decisions"}
        if (
            not isinstance(value, dict)
            or not required_request <= set(value) <= required_request | {"version"}
            or ("version" in value and value["version"] != 1)
        ):
            return JSONResponse(
                {"ok": False, "code": "REVIEW_INVALID_BATCH", "message": "Malformed decision request."},
                status_code=400,
            )
        members = value.get("decisions")
        if not isinstance(members, list) or not 1 <= len(members) <= config.max_batch_decisions:
            return JSONResponse(
                {"ok": False, "code": "REVIEW_INVALID_BATCH", "message": "Decision batch size is invalid."},
                status_code=400,
            )
        required = {
            "item_id", "item_revision", "review_digest", "expected_decision_revision",
            "verdict", "disposition", "note",
        }
        optional = {"proposal_id", "proposal_digest"}
        for member in members:
            if (
                not isinstance(member, dict)
                or not required <= set(member) <= required | optional
                or not isinstance(member.get("note"), str)
                or len(member["note"]) > config.max_note_chars
            ):
                return JSONResponse(
                    {"ok": False, "code": "REVIEW_INVALID_BATCH", "message": "Decision member is invalid."},
                    status_code=400,
                )
        value = {**value, "version": 1}
        command = [
            console_script("summary_native"),
            "review", "decide", review_id,
            "--decisions", "-",
            "--grant", grant.grant_id,
            "--campaign-dir", str(root),
            "--json",
        ]
        try:
            result = await run_bounded_json(
                command,
                cwd=str(root),
                env_extra={"REVIEW_CAPABILITY_TOKEN": capability},
                redact_env_keys={"REVIEW_CAPABILITY_TOKEN"},
                stdin_bytes=json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                timeout_seconds=config.command_timeout_seconds,
                max_output_bytes=config.max_response_bytes,
                save_run_log=False,
            )
            return JSONResponse(result, status_code=200)
        except BoundedJSONError as exc:
            return safe_command_error(exc)

    return app
