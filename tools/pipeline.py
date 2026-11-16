from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import islice
from pathlib import Path
from typing import Any

from .converter import normalize_spec
from .extractor import extract_operations_and_components, save_metadata
from .utils import extract_auth_info

log = logging.getLogger(__name__)
FORMAT_VERSION = 3


def batcher(iterable: Iterable, batch_size: int) -> Iterator[list]:
    iterator = iter(iterable)
    while chunk := list(islice(iterator, batch_size)):
        yield chunk


def process_single_service(
    service_info: dict[str, Any], data_dir: Path, no_compress_utilize: bool = False
) -> dict[str, Any]:
    provider = service_info["provider"]
    api = service_info["api"]
    source = service_info["source"]
    url = service_info.get("url", "")

    metrics: dict[str, Any] = {"provider": provider, "api": api, "source": source, "url": url}
    try:
        service_data_dir = data_dir / provider / source / api
        t_parse_start = time.perf_counter()
        compressed_spec_path = service_data_dir / f"{api}.openapi.json.zst"
        compressed_content = compressed_spec_path.read_bytes()
        raw_spec = dict(normalize_spec(compressed_content=compressed_content))
        metrics["parse_duration"] = time.perf_counter() - t_parse_start

        t_extract_start = time.perf_counter()
        processed_data = extract_operations_and_components(api, raw_spec)
        metrics["extract_duration"] = time.perf_counter() - t_extract_start

        processed_data["servers"] = raw_spec.get("servers", [])
        processed_data["format_version"] = FORMAT_VERSION
        processed_data["service_name"] = api

        utilize_path = save_metadata(api, processed_data, service_data_dir)

        metrics.update(
            {
                "status": "success",
                "auth_info": extract_auth_info(raw_spec),
                "processed_op_count": len(processed_data["operations"]),
                "reusable_param_count": len(
                    processed_data.get("components", {}).get("parameters", {})
                ),
                "utilize_path": utilize_path,
                "no_compress_utilize": no_compress_utilize,
            }
        )
        return metrics
    except Exception as e:
        log.error("Failed to process service %s from %s: %s", api, source, e)
        metrics["status"] = "failure"
        return metrics


def run_processing_pipeline(
    services_to_process: list[dict[str, Any]],
    data_dir: Path,
    process_workers: int = 4,
    batch_size: int = 25,
    no_compress_utilize: bool = False,
) -> list[dict[str, Any]]:
    if not services_to_process:
        return []

    batches = list(batcher(services_to_process, batch_size))
    log.info("Processing %d services in %d batches...", len(services_to_process), len(batches))
    results: list[dict[str, Any]] = []

    for batch in batches:
        with ProcessPoolExecutor(max_workers=process_workers) as executor:
            futures = {
                executor.submit(
                    process_single_service, service, data_dir, no_compress_utilize
                ): service["api"]
                for service in batch
            }
            for future in as_completed(futures):
                results.append(future.result())
    return results
