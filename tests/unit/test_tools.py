# tests/unit/test_tools.py
from __future__ import annotations

from pathlib import Path

import pytest

from tools import pipeline, utils

from .. import helpers


def test_compress_decompress_zstd():
    """Tests zstd roundtrip compression and decompression."""
    data = b"Hello, MAPI compression!" * 20
    compressed = utils.compress_zstd(data)
    assert len(compressed) < len(data)
    decompressed = utils.decompress_zstd(compressed)
    assert decompressed == data


def test_load_spec_unsupported_file_type(tmp_path: Path):
    """Tests that load_spec raises a ValueError for an unsupported file type."""
    unsupported_file = helpers.create_unsupported_file(tmp_path, "unsupported")
    with pytest.raises(ValueError):
        utils.load_spec(unsupported_file)


def test_resolve_ref_broken_ref():
    """Tests that _resolve_ref handles a broken $ref gracefully."""
    spec = helpers.create_mock_spec_with_broken_ref()
    broken_ref = "#/components/parameters/param2"
    assert utils._resolve_ref(spec, broken_ref) == {}


def test_batcher():
    """Tests that batcher slices iterables into batches."""
    items = list(range(10))
    batches = list(pipeline.batcher(items, 3))
    assert len(batches) == 4
    assert batches[0] == [0, 1, 2]
    assert batches[-1] == [9]


def test_process_single_service_failure(tmp_path: Path):
    """Tests that process_single_service handles corrupted spec file gracefully."""
    service_name = "corrupted_service"
    service_data_dir = tmp_path / "data" / service_name
    service_data_dir.mkdir(parents=True)
    spec_path = service_data_dir / f"{service_name}.openapi.json.zst"
    spec_path.write_bytes(b"not a valid zstd stream")

    service_info = {
        "provider": "corrupted_service",
        "api": "corrupted_service",
        "source": "custom",
        "url": "http://localhost/corrupted.json",
    }
    result = pipeline.process_single_service(
        service_info, tmp_path / "data", no_compress_utilize=True
    )
    assert result["status"] == "failure"
