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
from .models.config import ClientConfig
from .models.request import BatchRequest
from .models.response import MapiResult, ResponseMetadata

__version__ = "0.1.0"

__all__ = [
    "ApiKeyAuth",
    "BatchRequest",
    "BearerAuth",
    "ClientConfig",
    "ClientError",
    "ConfigurationError",
    "Mapi",
    "MapiError",
    "MapiResult",
    "RateLimitError",
    "ResponseMetadata",
    "ServerError",
    "ServiceNotFoundError",
    "TransportError",
    "ValidationError",
]
