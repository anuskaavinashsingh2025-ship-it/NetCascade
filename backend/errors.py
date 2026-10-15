"""Consistent JSON responses and error handling.

Success: ``{"success": true, "data": ...}``
Error:   ``{"success": false, "error": {"code": ..., "message": ..., "status": ...}}``
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from netcascade import ValidationError


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str | None = None, details: Any = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code or _CODES.get(status, "error")
        self.details = details


_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    415: "unsupported_media_type",
    422: "validation_error",
    500: "internal_error",
}


def ok(data: Any = None, status: int = 200):
    return jsonify({"success": True, "data": data}), status


def error_response(message: str, status: int, code: str | None = None, details: Any = None):
    body: dict[str, Any] = {"code": code or _CODES.get(status, "error"), "message": message, "status": status}
    if details is not None:
        body["details"] = details
    return jsonify({"success": False, "error": body}), status


def status_for_validation_error(message: str) -> int:
    """Map engine ValidationError messages to HTTP status codes."""
    if message.startswith("Unknown device type"):
        return 422
    if message.startswith(("Unknown device", "Unknown topology")) or "does not exist" in message:
        return 404
    if "already exists" in message or "already assigned" in message:
        return 409
    return 422


def json_body() -> dict[str, Any]:
    """Parsed JSON object body, or a 400 for missing/malformed/non-object JSON."""
    if not request.content_length:
        return {}
    if not request.is_json:
        raise ApiError("Content-Type must be application/json", 415)
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("Malformed JSON in request body", 400)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object", 400)
    return data


def require_fields(data: dict[str, Any], *fields: str) -> None:
    missing = [f for f in fields if f not in data or data[f] is None]
    if missing:
        raise ApiError(f"Missing required field(s): {', '.join(missing)}", 400)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return error_response(exc.message, exc.status, exc.code, exc.details)

    @app.errorhandler(ValidationError)
    def _validation_error(exc: ValidationError):
        msg = str(exc)
        return error_response(msg, status_for_validation_error(msg))

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        return error_response(exc.description or exc.name, exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        app.logger.exception("Unhandled error")
        return error_response("Internal server error", 500)
