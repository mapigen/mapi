from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Optional

import msgspec
import zstandard as zstd

from ..models.domain import ServiceData
from ..models.registry import ServiceRegistry
from ..exceptions import ConfigurationError, ServiceNotFoundError

log = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DATA_DIR = _PACKAGE_DIR / "data"
_DEFAULT_REGISTRY = _PACKAGE_DIR / "services.json"


def _default_data_dir() -> Path:
    env = os.environ.get("MAPI_DATA_DIR")
    return Path(env) if env else _DEFAULT_DATA_DIR


def _default_registry_path() -> Path:
    env = os.environ.get("MAPI_REGISTRY_PATH")
    return Path(env) if env else _DEFAULT_REGISTRY


class DiskLoader:
    """
    Single abstraction over all filesystem access for mapi service data.

    Directory layout:
      data_dir / provider / source / api / {api}.utilize.json[.zst]
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        registry_path: Optional[Path] = None,
    ) -> None:
        self.data_dir = data_dir or _default_data_dir()
        self.registry_path = registry_path or _default_registry_path()
        self._dctx = zstd.ZstdDecompressor()
        self._service_decoder = msgspec.json.Decoder(ServiceData)
        self._registry_decoder = msgspec.json.Decoder(ServiceRegistry)

    def load_registry(self) -> ServiceRegistry:
        """Load and decode services.json into a typed ServiceRegistry."""
        if not self.registry_path.exists():
            raise ConfigurationError(
                f"Service registry not found at {self.registry_path}. "
                "Ensure data is populated or set MAPI_REGISTRY_PATH.",
            )
        log.debug("Loading registry from %s", self.registry_path)
        return self._registry_decoder.decode(self.registry_path.read_bytes())

    def load_service(self, provider: str, api: str, source: str) -> ServiceData:
        """Load utilize.json or utilize.json.zst for a service."""
        service_dir = self.service_dir(provider, api, source)
        uncompressed = service_dir / f"{api}.utilize.json"
        compressed = service_dir / f"{api}.utilize.json.zst"

        if uncompressed.exists():
            log.debug("Loading uncompressed %s/%s/%s", provider, api, source)
            return self._service_decoder.decode(uncompressed.read_bytes())

        if compressed.exists():
            log.debug("Loading compressed %s/%s/%s", provider, api, source)
            return self._service_decoder.decode(self._dctx.decompress(compressed.read_bytes()))

        raise ServiceNotFoundError(
            f"Service data for '{provider}/{api}/{source}' not found. "
            f"Expected at {service_dir}",
            service=f"{provider}/{api}/{source}",
        )

    def service_dir(self, provider: str, api: str, source: str) -> Path:
        """Return the directory path for a given service."""
        return self.data_dir / provider / source / api
