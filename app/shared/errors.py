from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    UNAUTHORIZED = "unauthorized"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    INVALID_JSON = "invalid_json"
    INVALID_DIFF = "invalid_diff"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    INTERNAL = "internal"


class ApiError(Exception):
    def __init__(self, code: ErrorCode, message: str, status_code: int | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code or self._status_for_code(code)
        super().__init__(message)

    @staticmethod
    def _status_for_code(code: ErrorCode) -> int:
        mapping = {
            ErrorCode.UNAUTHORIZED: 401,
            ErrorCode.PAYLOAD_TOO_LARGE: 413,
            ErrorCode.INVALID_JSON: 400,
            ErrorCode.INVALID_DIFF: 422,
            ErrorCode.IDEMPOTENCY_CONFLICT: 409,
            ErrorCode.NOT_FOUND: 404,
            ErrorCode.RATE_LIMITED: 429,
            ErrorCode.INTERNAL: 500,
        }
        return mapping[code]
