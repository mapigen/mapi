"""mapi — Universal API client SDK."""

from .auth import ApiKeyAuth, BearerAuth
from .client import Mapi
from .exceptions import (
    ClientError,
    ConfigurationError,
    MapiError,
    RateLimitError,
    ServerError,
    ServiceNotFoundError,
    TransportError,
    ValidationError,
)
from .models.response import MapiResult, ResponseMetadata

__version__ = "0.1.0"

__all__ = [
    "Mapi",
    "MapiResult",
    "ResponseMetadata",
    "ApiKeyAuth",
    "BearerAuth",
    "MapiError",
    "ConfigurationError",
    "ServiceNotFoundError",
    "ValidationError",
    "TransportError",
    "RateLimitError",
    "ServerError",
    "ClientError",
]
