from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import islice
from pathlib import Path
from typing import Any

import msgspec
import niquests

from .utils import compress_zstd

log = logging.getLogger(__name__)


def _sanitize_api_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^a-z0-9-]", "", name)
    return name


def fetch_single_spec(
    provider: str,
    api: str,
    source: str,
    url: str,
    session: niquests.Session,
    data_dir: Path,
    force_reprocess: bool = False,
    no_compress_original: bool = False,
) -> dict[str, Any]:
    service_data_dir = data_dir / provider / source / api
    spec_path_zst = service_data_dir / f"{api}.openapi.json.zst"

    if (
        not force_reprocess
        and (service_data_dir / "metadata.yml").exists()
        and spec_path_zst.exists()
    ):
        return {"status": "skipped", "provider": provider, "api": api, "source": source}

    headers = {"User-Agent": "mapi-builder/1.0"}
    t_start = time.perf_counter()
    try:
        resp = session.get(url, timeout=30, headers=headers)
        resp.raise_for_status()
        content = resp.content
        download_duration = time.perf_counter() - t_start

        if not content:
            return {
                "status": "failure",
                "provider": provider,
                "api": api,
                "source": source,
                "reason": "No content",
            }

        if url.endswith((".yaml", ".yml")):
            data = msgspec.yaml.decode(content)
            content = msgspec.json.encode(data)

        service_data_dir.mkdir(parents=True, exist_ok=True)
        spec_path_zst.write_bytes(compress_zstd(content))

        if no_compress_original:
            (service_data_dir / f"{api}.openapi.json").write_bytes(content)

        return {
            "status": "success",
            "provider": provider,
            "api": api,
            "source": source,
            "download_duration": download_duration,
            "url": url,
        }
    except Exception as e:
        log.error("Failed to download %s from %s: %s", api, source, e)
        return {
            "status": "failure",
            "provider": provider,
            "api": api,
            "source": source,
            "reason": str(e),
        }


def batcher(iterable: Iterable, batch_size: int) -> Iterator[list[Any]]:
    iterator = iter(iterable)
    while chunk := list(islice(iterator, batch_size)):
        yield chunk


def fetch_specs_concurrently(
    sources: list[dict[str, Any]],
    batch_size: int,
    data_dir: Path,
    download_workers: int = 25,
    force_reprocess: bool = False,
    no_compress_original: bool = False,
) -> list[dict[str, Any]]:
    if not sources:
        return []
    log.info("Downloading %d specs in batches of %d...", len(sources), batch_size)
    all_results: list[dict[str, Any]] = []

    for batch in batcher(sources, batch_size):
        with (
            niquests.Session() as session,
            ThreadPoolExecutor(max_workers=download_workers) as executor,
        ):
            futures = {
                executor.submit(
                    fetch_single_spec,
                    entry["provider"],
                    entry["api"],
                    entry["source"],
                    entry["url"],
                    session,
                    data_dir,
                    force_reprocess,
                    no_compress_original,
                ): entry["api"]
                for entry in batch
            }
            for future in as_completed(futures):
                all_results.append(future.result())
    return all_results
