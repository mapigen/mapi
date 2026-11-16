from __future__ import annotations
import json
import traceback
from pathlib import Path
from typing import Any, Callable, List, Dict
from dataclasses import asdict

from mapi import Mapi, MapiError
from .helpers import result_reporter, VALID_CALL_4XX

# This dictionary is the single source of truth for which credentials
# are needed for each integration test.
REQUIRED_CREDS: Dict[str, List[str]] = {
    "discord": ["DISCORD_BOT_TOKEN", "TEST_CHANNEL_ID", "DISCORD_MESSAGE_ID"],
    "github": ["GITHUB_TOKEN", "TEST_GITHUB_USER"],
    "pokeapi": [],  # No specific credentials required for basic PokeAPI tests
}

# This dictionary controls which services will have their payloads saved to tmp/.
SAVE_PAYLOAD_TOGGLE: Dict[str, bool] = {
    "discord": True,
    "github": True,
    "pokeapi": True,
}

def _save_payload_if_enabled(provider_name: str, api_name: str, op_name: str, response_wrapper: Any) -> str | None:
    """Checks the toggle and saves the full response payload if enabled."""
    if SAVE_PAYLOAD_TOGGLE.get(api_name, False):
        tmp_dir = Path(__file__).resolve().parent.parent / "tmp"
        tmp_dir.mkdir(exist_ok=True)

        # Sanitize op_name for filename
        safe_op_name = op_name.replace("/", "_")
        file_path = tmp_dir / f"{provider_name}_{api_name}_{safe_op_name}_response.json"

        # Prepare data for serialization
        data_to_save: Dict[str, Any] = {}
        if hasattr(response_wrapper, "metadata"):
            meta = response_wrapper.metadata
            data_to_save["metadata"] = asdict(meta) if hasattr(meta, "__dataclass_fields__") else meta.__dict__ if hasattr(meta, "__dict__") else str(meta)
        if hasattr(response_wrapper, "data"):
            data_to_save["data"] = response_wrapper.data
        elif isinstance(response_wrapper, dict):
            data_to_save = response_wrapper

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2, default=str)
        return str(file_path)
    return None

def run_test_operation(
    client: Mapi,
    provider_name: str,
    api_name: str,
    op_name: str,
    operations_checked: List[str],
    assertion_callback: Callable[[Any], None],
    **kwargs: Any,
):
    """A helper function to run a single integration test operation and report the result."""
    service_key = f"{provider_name}/{api_name}"
    try:
        provider_proxy = getattr(client, provider_name)
        if hasattr(provider_proxy, api_name):
            api_proxy = getattr(provider_proxy, api_name)
        else:
            available = client.discovery.list_apis(provider_name)
            if available:
                api_proxy = getattr(provider_proxy, available[0])
            else:
                api_proxy = getattr(provider_proxy, api_name)

        response_wrapper = api_proxy(op_name, **kwargs)
        metadata = getattr(response_wrapper, "metadata", None)
        data = getattr(response_wrapper, "data", None)

        if metadata and getattr(metadata, "status", None) == "success":
            assertion_callback(data)
            result_reporter.add_passed(service_key, op_name, getattr(metadata, "duration_ms", 0))
        elif (metadata and getattr(metadata, "http_status", None) in VALID_CALL_4XX) or (metadata and getattr(metadata, "error_type", None) == "validation"):
            error = MapiError(
                f"Expected client error: {getattr(metadata, 'http_status', None) or getattr(metadata, 'error_type', None)}", 
                service=service_key, 
                operation=op_name,
            )
            result_reporter.add_http_validated_call(service_key, op_name, error)
        else:
            error_type = getattr(metadata, 'error_type', 'Unknown') if metadata else 'Unknown'
            error = MapiError(
                f"Unexpected error: {error_type}", 
                service=service_key, 
                operation=op_name,
            )
            result_reporter.add_failed(service_key, op_name, error)

    except MapiError as e:
        result_reporter.add_failed(service_key, op_name, e)
    except Exception as e:
        print(f"--- UNHANDLED EXCEPTION IN {service_key}/{op_name} ---")
        traceback.print_exc()
        error = MapiError(f"Unhandled exception: {e}", service=service_key, operation=op_name)
        result_reporter.add_failed(service_key, op_name, error)
    
    operations_checked.append(op_name)