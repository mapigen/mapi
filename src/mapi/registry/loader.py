from __future__ import annotations

import logging
import os
from pathlib import Path

import msgspec
import zstandard as zstd

from ..constants import (
    DEFAULT_DATA_DIR_NAME,
    ENV_MAPI_DATA_DIR,
    ENV_MAPI_REGISTRY_PATH,
    EXT_DB,
    MAPI_EXT_JSON,
    MAPI_EXT_MSGPACK,
    MAPI_EXT_MSGPACK_ZST,
    MAPI_EXT_ZST,
    PRIMARY_REGISTRY_FILENAME,
)
from ..exceptions import ConfigurationError, ServiceNotFoundError
from ..models.domain import Operation, ServiceData
from ..models.registry import ServiceRegistry
from .packfile import PackfileLoader

log = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DATA_DIR = _PACKAGE_DIR / DEFAULT_DATA_DIR_NAME
_PRIMARY_REGISTRY = _PACKAGE_DIR / PRIMARY_REGISTRY_FILENAME


def _default_data_dir() -> Path:
    env = os.environ.get(ENV_MAPI_DATA_DIR)
    return Path(env) if env else _DEFAULT_DATA_DIR


def _default_registry_path() -> Path:
    env = os.environ.get(ENV_MAPI_REGISTRY_PATH)
    if env:
        return Path(env)
    return _PRIMARY_REGISTRY


class DiskLoader:
    """
    Single abstraction over all filesystem access for mapi service data.

    Directory layout:
      data_dir / provider / source / api / {api}.mapi.json[.zst]
    """

    def __init__(
        self,
        data_dir: Path | None = None,
        registry_path: Path | None = None,
        packfile_path: Path | None = None,
    ) -> None:
        self.data_dir = data_dir or _default_data_dir()
        self.registry_path = registry_path or _default_registry_path()
        self.packfile_path = packfile_path
        self._packfile: PackfileLoader | None = None
        if self.packfile_path is not None and self.packfile_path.exists():
            self._packfile = PackfileLoader(self.packfile_path)
        elif self.registry_path.suffix == EXT_DB and self.registry_path.exists():
            self._packfile = PackfileLoader(self.registry_path)

        self._dctx = zstd.ZstdDecompressor()
        self._service_decoder = msgspec.json.Decoder(ServiceData)
        self._service_msgpack_decoder = msgspec.msgpack.Decoder(ServiceData)
        self._registry_decoder = msgspec.json.Decoder(ServiceRegistry)
        self._path_cache: dict[tuple[str, str, str], tuple[Path, bool, bool]] = {}

    def load_registry(self) -> ServiceRegistry:
        """Load and decode mapi-registry.json into a typed ServiceRegistry."""
        if self._packfile is not None:
            return self._packfile.load_registry()

        if not self.registry_path.exists():
            raise ConfigurationError(
                f"Service registry not found at {self.registry_path}. "
                "Ensure data is populated or set MAPI_REGISTRY_PATH.",
            )
        log.debug("Loading registry from %s", self.registry_path)
        return self._registry_decoder.decode(self.registry_path.read_bytes())

    def load_service(self, provider: str, api: str, source: str) -> ServiceData:
        """Load mapi.json, mapi.msgpack, or .zst for a service."""
        if self._packfile is not None:
            return self._packfile.load_service(provider, api, source)

        key = (provider, api, source)
        if key in self._path_cache:
            path, is_compressed, is_msgpack = self._path_cache[key]
            raw = path.read_bytes()
            content = self._dctx.decompress(raw) if is_compressed else raw
            if is_msgpack:
                return self._service_msgpack_decoder.decode(content)
            return self._service_decoder.decode(content)

        service_dir = self.service_dir(provider, api, source)
        candidates = (
            (service_dir / f"{api}{MAPI_EXT_MSGPACK_ZST}", True, True),
            (service_dir / f"{api}{MAPI_EXT_MSGPACK}", False, True),
            (service_dir / f"{api}{MAPI_EXT_ZST}", True, False),
            (service_dir / f"{api}{MAPI_EXT_JSON}", False, False),
        )
        for path, is_compressed, is_msgpack in candidates:
            if path.exists():
                self._path_cache[key] = (path, is_compressed, is_msgpack)
                log.debug(
                    "Loading %s %s/%s/%s",
                    "compressed" if is_compressed else "uncompressed",
                    provider,
                    api,
                    source,
                )
                raw = path.read_bytes()
                content = self._dctx.decompress(raw) if is_compressed else raw
                if is_msgpack:
                    return self._service_msgpack_decoder.decode(content)
                return self._service_decoder.decode(content)

        raise ServiceNotFoundError(
            f"Service data for '{provider}/{api}/{source}' not found. Expected at {service_dir}",
            service=f"{provider}/{api}/{source}",
        )

    def load_operation(
        self, provider: str, api: str, source: str, operation_id: str
    ) -> Operation | None:
        """Load single operation from packfile if available, otherwise return None."""
        if self._packfile is not None:
            return self._packfile.load_operation(provider, api, source, operation_id)
        return None

    def clear_cache(self) -> None:
        """Clear resolved service path cache."""
        self._path_cache.clear()

    def service_dir(self, provider: str, api: str, source: str) -> Path:
        """Return the directory path for a given service."""
        return self.data_dir / provider / source / api
