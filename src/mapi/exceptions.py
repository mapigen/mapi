# src/mapi/exceptions.py
from __future__ import annotations


class MapiError(Exception):
    """Base exception for all mapi errors."""

    def __init__(
        self,
        message: str,
        *,
        service: str | None = None,
        operation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.service = service
        self.operation = operation


class ConfigurationError(MapiError):
    """Raised for bad configuration or missing data directory / registry."""


class ServiceNotFoundError(MapiError):
    """Raised when provider/api/operation does not exist in registry or on disk."""


class ValidationError(MapiError):
    """Raised when call parameters fail schema validation."""


class TransportError(MapiError):
    """Raised for network or HTTP-level errors."""

    def __init__(
        self,
        message: str,
        *,
        service: str | None = None,
        operation: str | None = None,
        http_status: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, service=service, operation=operation)
        self.http_status = http_status
        if cause is not None:
            self.__cause__ = cause


class RateLimitError(TransportError):
    """Raised on HTTP 429 Too Many Requests."""


class ServerError(TransportError):
    """Raised on HTTP 5xx Server Error."""


class ClientError(TransportError):
    """Raised on HTTP 4xx Client Error (non-429)."""
