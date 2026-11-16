from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from mapi.models.domain import Parameter, ParameterRef, ServiceData
from mapi.registry.discovery import DiscoveryService, RegistryManager
from mapi.registry.loader import DiskLoader

FORMAT_VERSION = 3
log = logging.getLogger("mapi.tools.validate")

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT_DIR / "src" / "mapi" / "data"
DEFAULT_REGISTRY_PATH = ROOT_DIR / "src" / "mapi" / "services.json"


def validate_operations_and_refs(data: ServiceData, service_name: str) -> list[str]:
    errors: list[str] = []
    operations = data.operations
    components = data.components.parameters

    if not operations:
        errors.append("No 'operations' block found.")

    for op_id, op_data in operations.items():
        if not all([op_data.service, op_data.path, op_data.method, op_data.parameters is not None]):
            errors.append(f"Operation '{op_id}' is missing required fields.")

        for param in op_data.parameters:
            if isinstance(param, ParameterRef):
                if param.component_name not in components:
                    errors.append(f"Operation '{op_id}' has a broken $ref: '{param.ref}'")
            elif isinstance(param, Parameter) and not all(
                [param.name, param.in_, param.schema_ is not None]
            ):
                errors.append(f"Inline parameter in '{op_id}' is missing required fields.")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate generated service data files.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--registry-path", type=Path, default=DEFAULT_REGISTRY_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    log.info("Starting validation of service data...")

    loader = DiskLoader(data_dir=args.data_dir, registry_path=args.registry_path)
    rm = RegistryManager(loader)
    discovery = DiscoveryService(rm, loader)

    try:
        providers = discovery.list_providers()
    except Exception as e:
        log.warning("No service registry found at %s: %s", args.registry_path, e)
        return

    failures = 0
    total = 0

    for provider in providers:
        for api in discovery.list_apis(provider):
            info = discovery.get_api_info(provider, api)
            for source in info.sources:
                total += 1
                service_name = f"{provider}/{api}/{source}"
                service_dir = loader.service_dir(provider, api, source)

                try:
                    # 1. metadata.yml check
                    meta_path = service_dir / "metadata.yml"
                    if not meta_path.exists():
                        raise ValueError("Missing metadata.yml")

                    meta = yaml.safe_load(meta_path.read_text())
                    if meta.get("format_version") != FORMAT_VERSION:
                        raise ValueError(f"Incorrect format_version (expected {FORMAT_VERSION})")

                    # 2. utilize data check
                    service_data = loader.load_service(provider, api, source)
                    errors = validate_operations_and_refs(service_data, service_name)
                    if errors:
                        raise ValueError(", ".join(errors))

                    log.info("PASS: %s (%d operations)", service_name, len(service_data.operations))
                except Exception as e:
                    log.error("FAIL: %s - %s", service_name, e)
                    failures += 1

    log.info("Validation complete. Validated: %d, Failures: %d", total, failures)
    if failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
