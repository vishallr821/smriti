"""Common API schemas used across routes."""

from __future__ import annotations

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int


class RequestID(BaseModel):
    request_id: str
