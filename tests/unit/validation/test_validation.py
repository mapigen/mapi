from __future__ import annotations

from unittest.mock import MagicMock

import msgspec
import pytest

from mapi.cache import ServiceCache
from mapi.exceptions import ServiceNotFoundError, ValidationError
from mapi.models.domain import ServiceData
from mapi.validation import ParameterValidator


class TestParameterValidator:
    def _create_validator(self, service_data):
        cache = MagicMock(spec=ServiceCache)
        cache.get.return_value = service_data
        return ParameterValidator(cache)

    def test_valid_parameters_pass(self, sample_service_data):
        v = self._create_validator(sample_service_data)
        # get_user requires user_id: integer
        v.validate("p", "a", "s", "get_user", {"user_id": 42})
        v.validate("p", "a", "s", "get_user", {"user_id": 42, "limit": 20})

    def test_missing_required_parameter_raises(self, sample_service_data):
        v = self._create_validator(sample_service_data)
        with pytest.raises(ValidationError, match="user_id"):
            v.validate("p", "a", "s", "get_user", {})

    def test_invalid_type_raises(self, sample_service_data):
        v = self._create_validator(sample_service_data)
        with pytest.raises(ValidationError):
            v.validate("p", "a", "s", "get_user", {"user_id": "not_an_int"})

    def test_unknown_operation_raises_service_not_found(self, sample_service_data):
        v = self._create_validator(sample_service_data)
        with pytest.raises(ServiceNotFoundError):
            v.validate("p", "a", "s", "nonexistent_op", {})

    def test_operation_with_no_parameters_passes(self):
        sd_dict = {
            "format_version": 3,
            "service_name": "simple",
            "servers": [{"url": "https://api.test.com"}],
            "components": {"parameters": {}, "schemas": {}},
            "operations": {
                "health_check": {
                    "service": "simple",
                    "path": "/health",
                    "method": "GET",
                    "parameters": [],
                }
            },
        }
        sd = msgspec.json.decode(msgspec.json.encode(sd_dict), type=ServiceData)
        v = self._create_validator(sd)
        v.validate("p", "a", "s", "health_check", {})
