from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.core.config import Settings
from app.services.product_actions import ProductActionError
from app.services.queries import ReadNotFound

Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[int | None, Query(gt=0)]


def engine(request: Request) -> Engine:
    return request.app.state.db_engine


def settings(request: Request) -> Settings:
    return request.app.state.settings


Database = Annotated[Engine, Depends(engine)]
Configuration = Annotated[Settings, Depends(settings)]


def error(status: int, code: str, message: str):
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}
    )


ACTION_ERRORS = {
    "analysis_not_comparable": (
        409,
        "A supported completed analysis and valid company profile are required",
    ),
    "ai_configuration_missing": (503, "AI configuration is unavailable"),
    "document_not_indexed": (
        409,
        "This document is not fully indexed for the configured model",
    ),
    "answer_validation_failed": (502, "The answer or its citations failed validation"),
    "provider_unavailable": (503, "The answer provider is unavailable"),
    "pipeline_eager_disabled": (
        503,
        "Background pipeline delivery is unavailable in eager mode",
    ),
    "pipeline_unavailable": (
        503,
        "Pipeline delivery is unavailable; inspect operational history",
    ),
}


def install_errors(app):
    @app.exception_handler(ReadNotFound)
    async def missing(request, exc):
        return error(
            404,
            exc.resource + "_not_found",
            exc.resource.replace("_", " ").capitalize() + " does not exist",
        )

    @app.exception_handler(ProductActionError)
    async def action(request, exc):
        status, message = ACTION_ERRORS.get(
            exc.code, (409, "Action could not be completed")
        )
        return error(status, exc.code, message)

    @app.exception_handler(RequestValidationError)
    async def validation(request, exc):
        return error(
            422,
            "invalid_request",
            "Request validation failed; check field formats and bounds",
        )

    @app.exception_handler(ValidationError)
    async def stored_validation(request, exc):
        return error(500, "invalid_stored_data", "Stored data could not be represented")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return error(503, "database_unavailable", "Data is temporarily unavailable")

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(
            exc.status_code,
            "not_found" if exc.status_code == 404 else "request_failed",
            "Resource does not exist"
            if exc.status_code == 404
            else "Request could not be completed",
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return error(500, "internal_error", "The request could not be completed")


class ProductCORS(CORSMiddleware):
    def preflight_response(self, request_headers):
        response = super().preflight_response(request_headers)
        if response.status_code == 400:
            rejected = error(
                400, "cors_rejected", "Browser origin or method is not allowed"
            )
            for key, value in response.headers.items():
                if key.startswith("access-control-") or key == "vary":
                    rejected.headers[key] = value
            return rejected
        return response


class ProductBoundary:
    """Explicit origins and bounded bodies, including chunked requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        origins = scope["app"].state.settings.cors_allowed_origins
        cors = ProductCORS(
            self.bounded,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
        )
        return await cors(scope, receive, send)

    async def bounded(self, scope, receive, send):
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 262144:
                return await error(
                    413, "request_too_large", "Request body exceeds 256 KiB"
                )(scope, receive, send)
            if not message.get("more_body"):
                break
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)
