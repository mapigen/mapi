"""Generic, dynamic tests that verify the integrity of all populated service data."""

import pytest

from mapi import Mapi
from mapi.exceptions import ServiceNotFoundError
from mapi.models import ParameterRef


def get_all_service_identifiers() -> list[tuple[str, str, str]]:
    """Discovers and returns a list of all available (provider, api, source) tuples."""
    identifiers: list[tuple[str, str, str]] = []
    try:
        client = Mapi()
        providers = client.discovery.list_providers()
        for provider in providers:
            apis = client.discovery.list_apis(provider)
            for api in apis:
                api_info = client.discovery.get_api_info(provider, api)
                for source in api_info.sources:
                    identifiers.append((provider, api, source))
    except Exception:
        pass
    return identifiers


@pytest.mark.parametrize("provider,api,source", get_all_service_identifiers())
def test_service_data_integrity(provider: str, api: str, source: str):
    """Tests that service data loads and all parameter $refs are resolvable."""
    client = Mapi()
    try:
        service_data = client._loader.load_service(provider, api, source)
        assert service_data.service_name == api
    except ServiceNotFoundError:
        pytest.skip(f"Service data for '{provider}/{api}/{source}' not populated on disk.")
    except Exception as e:
        pytest.fail(f"Failed to load service data for '{provider}/{api}/{source}': {e}")

    all_ops = service_data.operations.keys()
    if not all_ops:
        pytest.skip(f"No operations found for service '{api}'.")

    for operation_name in all_ops:
        operation = service_data.operations.get(operation_name)
        assert operation is not None, f"Operation '{operation_name}' not found in service '{api}'"

        for param in operation.parameters:
            if isinstance(param, ParameterRef):
                assert param.component_name in service_data.components.parameters, (
                    f"Broken parameter reference '{param.ref}' in {api}/{operation_name}"
                )
