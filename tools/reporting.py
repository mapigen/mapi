from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def generate_auth_notice(
    services_requiring_fix: list[str],
    services_with_override: list[str],
    output_path: Path,
) -> None:
    content = """# Authentication Override Notice

This document tracks which API specifications have had their authentication information manually overridden.
"""
    content += "\n## Services with Active Overrides\n\n"
    if services_with_override:
        content += (
            "The following services are using authentication details from `overrides.json`:\n"
        )
        for service in sorted(services_with_override):
            content += f"- `{service}`\n"
    else:
        content += "No services are currently using an authentication override.\n"

    content += "\n## Services Requiring Attention\n\n"
    if services_requiring_fix:
        content += "The following services have no declared authentication types after processing and may require an override in `overrides.json`:\n"
        for service in sorted(services_requiring_fix):
            content += f"- `{service}`\n"
    else:
        content += "No services appear to require an authentication override at this time.\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)


def generate_performance_report(
    download_results: list[dict[str, Any]],
    processing_results: list[dict[str, Any]],
    total_duration: float,
) -> None:
    successful_downloads = [r for r in download_results if r.get("status") == "success"]
    successful_processing = [r for r in processing_results if r.get("status") == "success"]

    print("\n--- Performance Report ---")
    print(f"Total execution time: {total_duration:.2f}s")

    if download_results:
        print(f"\nDownload Phase: {len(download_results)} services")
        print(
            f"  Success: {len(successful_downloads)}, Failures: {len(download_results) - len(successful_downloads)}"
        )

    if processing_results:
        print(f"\nProcessing Phase: {len(processing_results)} services")
        print(
            f"  Success: {len(successful_processing)}, Failures: {len(processing_results) - len(successful_processing)}"
        )

    print("-------------------------")
