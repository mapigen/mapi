"""mapi — Universal API client SDK."""
from .client import Mapi
from .models.response import MapiResult, ResponseMetadata
from .auth import ApiKeyAuth, BearerAuth
from .exceptions import (
    MapiError,
    ConfigurationError,
    ServiceNotFoundError,
    ValidationError,
    TransportError,
    RateLimitError,
    ServerError,
    ClientError,
)

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
