"""mapi — Universal API client SDK."""

from .auth import ApiKeyAuth, BearerAuth
from .client import Mapi
from .constants import DEFAULT_VERSION
from .exceptions import (
    ClientError,
    ConfigurationError,
    MapiError,
    RateLimitError,
    ServerError,
    ServiceNotFoundError,
    SpecUpdateAvailableWarning,
    TransportError,
    ValidationError,
)
from .models.config import ClientConfig
from .models.request import BatchRequest, RequestConfig
from .models.response import HeadersDict, MapiResult, ResponseMetadata
from .models.spec import SpecDiffResult

__version__ = DEFAULT_VERSION

__all__ = [
    "ApiKeyAuth",
    "BatchRequest",
    "BearerAuth",
    "ClientConfig",
    "ClientError",
    "ConfigurationError",
    "HeadersDict",
    "Mapi",
    "MapiError",
    "MapiResult",
    "RateLimitError",
    "RequestConfig",
    "ResponseMetadata",
    "ServerError",
    "ServiceNotFoundError",
    "SpecDiffResult",
    "SpecUpdateAvailableWarning",
    "TransportError",
    "ValidationError",
]
