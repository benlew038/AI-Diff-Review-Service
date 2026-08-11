from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.shared.errors import ApiError, ErrorCode
from app.infrastructure.rate_limiter import RateLimitExceeded


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code.value, "message": exc.message}},
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        # Return 429 with Retry-After header and error envelope
        headers = {"Retry-After": str(exc.retry_after)}
        return JSONResponse(
            status_code=429,
            content={"error": {"code": ErrorCode.RATE_LIMITED.value, "message": "rate limit exceeded"}},
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": {"code": ErrorCode.INVALID_JSON.value, "message": "invalid request"}})

    @app.exception_handler(Exception)
    async def internal_error_handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": ErrorCode.INTERNAL.value, "message": "internal server error"}},
        )
