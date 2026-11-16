# src/mapi/registry/packfile.py
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import msgspec
import zstandard as zstd

from ..constants import PACKFILE_ZSTD_MAGIC
from ..exceptions import ConfigurationError, ServiceNotFoundError
from ..models.domain import Operation, ServiceData
from ..models.registry import ServiceRegistry

log = logging.getLogger(__name__)


class PackfileLoader:
    """
    High-performance, zero-dependency SQLite B-Tree packfile loader.

    Provides microsecond point lookups for both service metadata and
    granular single-operation payloads.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise ConfigurationError(f"Packfile not found at {self.db_path}")

        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.execute("PRAGMA query_only = ON;")
        self._conn.execute("PRAGMA mmap_size = 268435456;")  # 256 MB memory-mapped I/O
        self._conn.execute("PRAGMA cache_size = -8000;")  # 8 MB SQLite cache

        self._dctx = zstd.ZstdDecompressor()
        self._registry_decoder = msgspec.msgpack.Decoder(ServiceRegistry)
        self._service_decoder = msgspec.msgpack.Decoder(ServiceData)
        self._op_decoder = msgspec.msgpack.Decoder(Operation)

    def load_registry(self) -> ServiceRegistry:
        """Load and decode ServiceRegistry from packfile."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT payload FROM registry_entries WHERE key = 'meta:registry';")
        row = cursor.fetchone()
        if not row:
            raise ConfigurationError(f"Packfile at {self.db_path} is missing 'meta:registry'")
        payload: bytes = row[0]
        # Check if compressed
        if payload.startswith(PACKFILE_ZSTD_MAGIC):
            payload = self._dctx.decompress(payload)
        return self._registry_decoder.decode(payload)

    def load_service(self, provider: str, api: str, source: str) -> ServiceData:
        """Load entire ServiceData for a provider/api/source."""
        cursor = self._conn.cursor()
        key = f"svc:{provider}:{api}:{source}"
        cursor.execute("SELECT payload FROM registry_entries WHERE key = ?;", (key,))
        row = cursor.fetchone()
        if not row:
            raise ServiceNotFoundError(
                f"Service data for '{provider}/{api}/{source}' not found in packfile {self.db_path}",
                service=f"{provider}/{api}/{source}",
            )
        payload: bytes = row[0]
        if payload.startswith(PACKFILE_ZSTD_MAGIC):
            payload = self._dctx.decompress(payload)
        return self._service_decoder.decode(payload)

    def load_operation(
        self, provider: str, api: str, source: str, operation_id: str
    ) -> Operation | None:
        """Granular microsecond point lookup for a single Operation."""
        cursor = self._conn.cursor()
        key = f"op:{provider}:{api}:{source}:{operation_id}"
        cursor.execute("SELECT payload FROM registry_entries WHERE key = ?;", (key,))
        row = cursor.fetchone()
        if not row:
            return None
        payload: bytes = row[0]
        if payload.startswith(PACKFILE_ZSTD_MAGIC):
            payload = self._dctx.decompress(payload)
        return self._op_decoder.decode(payload)

    def list_operations(self, provider: str, api: str, source: str) -> list[str]:
        """Return list of operation IDs for a given service."""
        cursor = self._conn.cursor()
        key = f"idx:{provider}:{api}:{source}"
        cursor.execute("SELECT payload FROM registry_entries WHERE key = ?;", (key,))
        row = cursor.fetchone()
        if not row:
            return []
        payload: bytes = row[0]
        if payload.startswith(PACKFILE_ZSTD_MAGIC):
            payload = self._dctx.decompress(payload)
        return msgspec.msgpack.decode(payload, type=list[str])

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PackfileLoader:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class PackfileStorage:
    """Builder utility to pack registry and ServiceData into a single SQLite B-Tree file."""

    @staticmethod
    def create_packfile(
        db_path: Path | str,
        registry: ServiceRegistry,
        services: dict[tuple[str, str, str], ServiceData],
        compression_level: int = 3,
    ) -> Path:
        """Create a packed SQLite database file for production deployment."""
        target_path = Path(db_path)
        if target_path.exists():
            target_path.unlink()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        cctx = zstd.ZstdCompressor(level=compression_level)
        conn = sqlite3.connect(str(target_path))
        try:
            conn.execute("PRAGMA journal_mode = OFF;")
            conn.execute("PRAGMA synchronous = OFF;")
            conn.execute(
                """
                CREATE TABLE registry_entries (
                    key TEXT PRIMARY KEY,
                    payload BLOB NOT NULL
                ) WITHOUT ROWID;
                """
            )

            # Store metadata registry
            reg_bytes = msgspec.msgpack.encode(registry)
            reg_compressed = cctx.compress(reg_bytes)
            conn.execute(
                "INSERT INTO registry_entries (key, payload) VALUES (?, ?);",
                ("meta:registry", reg_compressed),
            )

            # Store each service
            for (provider, api, source), sdata in services.items():
                svc_key = f"svc:{provider}:{api}:{source}"
                svc_bytes = msgspec.msgpack.encode(sdata)
                svc_compressed = cctx.compress(svc_bytes)
                conn.execute(
                    "INSERT INTO registry_entries (key, payload) VALUES (?, ?);",
                    (svc_key, svc_compressed),
                )

                # Store operation index
                idx_key = f"idx:{provider}:{api}:{source}"
                op_ids = list(sdata.operations.keys())
                idx_bytes = msgspec.msgpack.encode(op_ids)
                conn.execute(
                    "INSERT INTO registry_entries (key, payload) VALUES (?, ?);",
                    (idx_key, idx_bytes),
                )

                # Store individual granular operations
                for op_id, op in sdata.operations.items():
                    op_key = f"op:{provider}:{api}:{source}:{op_id}"
                    op_bytes = msgspec.msgpack.encode(op)
                    op_compressed = cctx.compress(op_bytes)
                    conn.execute(
                        "INSERT INTO registry_entries (key, payload) VALUES (?, ?);",
                        (op_key, op_compressed),
                    )

            conn.commit()
            conn.execute("VACUUM;")
        finally:
            conn.close()

        return target_path
