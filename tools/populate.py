from __future__ import annotations
import argparse
from datetime import datetime, timezone
import logging
import multiprocessing as mp
from pathlib import Path
import time
from typing import Any, Dict, List

import msgspec

from .fetcher import fetch_specs_concurrently
from .pipeline import run_processing_pipeline
from .registry_builder import RegistryBuilder
from .reporting import generate_auth_notice, generate_performance_report
from .utils import compress_zstd

FORMAT_VERSION = 3
log = logging.getLogger("mapi.tools.populate")

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src" / "mapi"
DATA_DIR = SRC_DIR / "data"
REGISTRY_DIR = ROOT_DIR / "registry"
OVERRIDES_PATH = REGISTRY_DIR / "overrides.json"
POPULARITY_PATH = REGISTRY_DIR / "popularity.json"
SERVICES_JSON_PATH = SRC_DIR / "services.json"


def get_rank(service: str) -> int:
    if POPULARITY_PATH.exists():
        try:
            ranks = msgspec.json.decode(POPULARITY_PATH.read_bytes())
            return ranks.get(service, 999)
        except Exception:
            pass
    return 999


def load_configuration() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_sources: list[dict[str, Any]] = []
    source_files = {
        "github": REGISTRY_DIR / "github_sources.yaml",
        "custom": REGISTRY_DIR / "custom_sources.yaml",
        "postman": REGISTRY_DIR / "postman_sources.yaml",
    }
    for source, path in source_files.items():
        if path.exists():
            try:
                entries = msgspec.yaml.decode(path.read_bytes(), type=List[Dict[str, Any]])
                for entry in entries:
                    entry["source"] = source
                    all_sources.append(entry)
            except Exception as e:
                log.error("Failed to parse %s: %s", path, e)
    overrides: dict[str, Any] = {}
    if OVERRIDES_PATH.exists():
        try:
            overrides = msgspec.json.decode(OVERRIDES_PATH.read_bytes())
        except Exception:
            pass
    return all_sources, overrides


def write_metadata(result: dict[str, Any], overrides: dict[str, Any], data_dir: Path) -> None:
    provider, api, source = result["provider"], result["api"], result["source"]
    service_data_dir = data_dir / provider / source / api
    service_data_dir.mkdir(parents=True, exist_ok=True)
    metadata_yml_path = service_data_dir / "metadata.yml"

    first_accessed_time = datetime.now(timezone.utc).isoformat()
    if metadata_yml_path.exists():
        try:
            existing = msgspec.yaml.decode(metadata_yml_path.read_text(), type=Dict[str, Any])
            first_accessed_time = existing.get("first_accessed", first_accessed_time)
        except Exception:
            pass

    final_auth_info = result["auth_info"].copy()
    if api in overrides and "auth" in overrides[api]:
        final_auth_info.update(overrides[api]["auth"])

    metadata_content = {
        "format_version": FORMAT_VERSION,
        "first_accessed": first_accessed_time,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "api_reference": result.get("url", ""),
        "status": result["status"],
        "operation_count": result.get("processed_op_count", 0),
        "reusable_parameter_count": result.get("reusable_param_count", 0),
        "coverage": result.get("coverage", "N/A"),
        "auth_types": final_auth_info.get("auth_types", []),
        "primary_auth": final_auth_info.get("primary_auth", "none"),
        "popularity_rank": get_rank(api),
    }
    metadata_yml_path.write_bytes(msgspec.yaml.encode(metadata_content))


def handle_utilize_compression(utilize_path: Path, no_compress: bool = False) -> None:
    if not no_compress and utilize_path.exists():
        compressed_data = compress_zstd(utilize_path.read_bytes())
        compressed_path = utilize_path.with_suffix(".json.zst")
        compressed_path.write_bytes(compressed_data)
        utilize_path.unlink()


def main():
    parser = argparse.ArgumentParser(description="Fetch and process API specifications.")
    parser.add_argument("--batch-size", type=int, default=25, help="Batch size for processing.")
    parser.add_argument("--download-workers", type=int, default=15, help="Download concurrency.")
    parser.add_argument("--process-workers", type=int, default=mp.cpu_count(), help="Process concurrency.")
    parser.add_argument("--skip-download", action="store_true", help="Skip downloading new specs.")
    parser.add_argument("--force-reprocess", action="store_true", help="Reprocess all cached specs.")
    parser.add_argument("--no-compress-utilize", action="store_true", help="Do not compress utilize.json.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="Destination data directory.")
    args = parser.parse_args()

    overall_start = time.perf_counter()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    all_sources, overrides = load_configuration()
    if not all_sources:
        log.warning("No sources configured.")
        return

    # 1. Fetch Phase
    download_results = []
    if not args.skip_download:
        download_results = fetch_specs_concurrently(
            all_sources,
            batch_size=50,
            data_dir=args.data_dir,
            download_workers=args.download_workers,
            force_reprocess=args.force_reprocess,
        )

    # 2. Process Phase
    services_to_process = [r for r in download_results if r.get("status") == "success"]
    if args.force_reprocess:
        services_to_process = all_sources

    processing_results = run_processing_pipeline(
        services_to_process,
        data_dir=args.data_dir,
        process_workers=args.process_workers,
        batch_size=args.batch_size,
        no_compress_utilize=args.no_compress_utilize,
    )

    # 3. Metadata and Registry Generation
    for result in processing_results:
        if result.get("status") == "success":
            write_metadata(result, overrides, args.data_dir)
            if "utilize_path" in result:
                handle_utilize_compression(result["utilize_path"], args.no_compress_utilize)

    builder = RegistryBuilder(data_dir=args.data_dir, registry_path=SERVICES_JSON_PATH)
    registry = builder.build_registry()
    builder.save_registry(registry)

    # Mirror to top-level services.json
    top_level_services = ROOT_DIR / "services.json"
    if SERVICES_JSON_PATH.exists():
        top_level_services.write_bytes(SERVICES_JSON_PATH.read_bytes())

    total_duration = time.perf_counter() - overall_start
    generate_performance_report(download_results, processing_results, total_duration)
    log.info("Data population complete.")


if __name__ == "__main__":
    main()
