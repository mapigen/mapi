from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import msgspec

from .utils import decompress_zstd


def normalize_spec(
    path: Path | None = None,
    compressed_content: bytes | None = None,
) -> Mapping[str, Any]:
    """Loads and parses an OpenAPI spec from a file path or compressed content."""
    if not path and not compressed_content:
        raise ValueError("Either 'path' or 'compressed_content' must be provided.")

    if compressed_content:
        decompressed = decompress_zstd(compressed_content)
        return msgspec.json.decode(decompressed)
    elif path:
        content = path.read_bytes()
        if path.suffix in (".yaml", ".yml"):
            return msgspec.yaml.decode(content)
        else:
            return msgspec.json.decode(content)
    return {}
