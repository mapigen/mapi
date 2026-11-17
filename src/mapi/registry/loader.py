from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

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
from .spec_compiler import compile_spec

log = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DATA_DIR = _PACKAGE_DIR / DEFAULT_DATA_DIR_NAME
_PRIMARY_REGISTRY = _PACKAGE_DIR / PRIMARY_REGISTRY_FILENAME


def _default_data_dir() -> Path:
    env = os.environ.get(ENV_MAPI_DATA_DIR)
    if env:
        return Path(env)
    # Check workspace data dir (prefer dedicated data/ outside of package src)
    current = Path.cwd().resolve()
    for parent in [current, *current.parents[:4]]:
        data_sub = parent / DEFAULT_DATA_DIR_NAME
        if data_sub.is_dir() and "src/mapi" not in str(data_sub):
            return data_sub
    # Check XDG / system user data dir
    xdg_data = os.environ.get("XDG_DATA_HOME")
    user_data = (Path(xdg_data) if xdg_data else Path.home() / ".local/share") / "mapi" / DEFAULT_DATA_DIR_NAME
    if user_data.is_dir():
        return user_data
    return _DEFAULT_DATA_DIR


def _default_registry_path(data_dir: Path | None = None) -> Path:
    env = os.environ.get(ENV_MAPI_REGISTRY_PATH)
    if env:
        return Path(env)
    target_data = data_dir or _default_data_dir()
    reg_in_data = target_data / PRIMARY_REGISTRY_FILENAME
    if reg_in_data.exists():
        return reg_in_data
    return _PRIMARY_REGISTRY


class DiskLoader:
    """Loads service definitions and registry metadata from disk."""

    def __init__(
        self,
        data_dir: Path | None = None,
        registry_path: Path | None = None,
        packfile_path: Path | None = None,
        online: bool = False,
    ) -> None:
        self.data_dir = data_dir or _default_data_dir()
        self.registry_path = registry_path or _default_registry_path(self.data_dir)
        self.packfile_path = packfile_path
        self.online = online or os.environ.get("MAPI_ONLINE") == "1"
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

    def load_service_metadata(
        self, provider: str, api: str, source: str
    ) -> dict[str, Any] | None:
        """Load metadata.yml for a service if present."""
        service_dir = self.service_dir(provider, api, source)
        meta_candidates = [
            service_dir / "metadata.yml",
            service_dir / "metadata.yaml",
        ]
        if self.data_dir.resolve() != _DEFAULT_DATA_DIR.resolve() and _DEFAULT_DATA_DIR.exists():
            pkg_service_dir = _DEFAULT_DATA_DIR / provider / source / api
            meta_candidates.extend([
                pkg_service_dir / "metadata.yml",
                pkg_service_dir / "metadata.yaml",
            ])

        for meta_path in meta_candidates:
            if meta_path.is_file():
                try:
                    import yaml
                    data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        return data
                except ImportError:
                    result: dict[str, Any] = {}
                    for line in meta_path.read_text(encoding="utf-8").splitlines():
                        if ":" in line and not line.strip().startswith("-"):
                            k, v = line.split(":", 1)
                            k, v = k.strip(), v.strip()
                            if v.isdigit():
                                result[k] = int(v)
                            else:
                                result[k] = v
                    return result
                except Exception:
                    pass
        return None

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
        candidates = [
            (service_dir / f"{api}{MAPI_EXT_MSGPACK_ZST}", True, True),
            (service_dir / f"{api}{MAPI_EXT_MSGPACK}", False, True),
            (service_dir / f"{api}{MAPI_EXT_ZST}", True, False),
            (service_dir / f"{api}{MAPI_EXT_JSON}", False, False),
        ]
        if self.data_dir.resolve() != _DEFAULT_DATA_DIR.resolve() and _DEFAULT_DATA_DIR.exists():
            pkg_service_dir = _DEFAULT_DATA_DIR / provider / source / api
            candidates.extend([
                (pkg_service_dir / f"{api}{MAPI_EXT_MSGPACK_ZST}", True, True),
                (pkg_service_dir / f"{api}{MAPI_EXT_MSGPACK}", False, True),
                (pkg_service_dir / f"{api}{MAPI_EXT_ZST}", True, False),
                (pkg_service_dir / f"{api}{MAPI_EXT_JSON}", False, False),
            ])
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

        # Pull-through online spec fetching if declared in registry and online mode is enabled
        if self.online and os.environ.get("MAPI_OFFLINE") != "1":
            online_data = self._fetch_and_compile_service(provider, api, source)
            if online_data is not None:
                return online_data

        raise ServiceNotFoundError(
            f"Service data for '{provider}/{api}/{source}' not found. Expected at {service_dir}",
            service=f"{provider}/{api}/{source}",
        )

    def _fetch_and_compile_service(
        self, provider: str, api: str, source: str
    ) -> ServiceData | None:
        if os.environ.get("MAPI_OFFLINE") == "1":
            return None

        try:
            reg = self.load_registry()
            api_info = reg.providers.get(provider, {}).get(api)
            if not api_info or not getattr(api_info, "spec_url", None):
                return None

            spec_url = api_info.spec_url
            if not spec_url:
                return None

            import niquests

            resp = niquests.get(spec_url, timeout=15.0)
            if resp.status_code != 200:
                return None

            raw_bytes = resp.content or b""
            import json

            import yaml

            try:
                spec_dict = json.loads(raw_bytes)
            except Exception:
                spec_dict = yaml.safe_load(raw_bytes)

            service_data = compile_spec(spec_dict, service_name=api)

            # Atomically save to disk cache
            service_dir = self.service_dir(provider, api, source)
            service_dir.mkdir(parents=True, exist_ok=True)
            target_path = service_dir / f"{api}{MAPI_EXT_ZST}"
            tmp_path = service_dir / f".{api}.tmp"
            compressed = zstd.ZstdCompressor(level=3).compress(msgspec.json.encode(service_data))
            tmp_path.write_bytes(compressed)
            tmp_path.replace(target_path)

            self._path_cache[(provider, api, source)] = (target_path, True, False)
            return service_data
        except Exception as e:
            log.warning("Pull-through online spec fetch failed for %s/%s: %s", provider, api, e)
            return None

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
