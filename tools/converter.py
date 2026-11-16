from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping, Optional

import msgspec

from .utils import decompress_zstd


def normalize_spec(
    path: Optional[Path] = None,
    compressed_content: Optional[bytes] = None,
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
