# tests/unit/test_models.py
from __future__ import annotations
import os
import pytest
import msgspec

from mapi.models import (
    Parameter, ParameterRef, ParameterUnion,
    Server, Operation, Components, ServiceData,
    ClientConfig, RequestConfig,
    ResponseMetadata, MapiResult,
    ApiInfo, ServiceRegistry,
)
from mapi.exceptions import (
    MapiError, ConfigurationError, ServiceNotFoundError,
    ValidationError, TransportError, RateLimitError,
)


class TestParameter:
    def test_encode_decode_roundtrip(self):
        p = Parameter(name="user_id", in_="path", schema_={"type": "integer"}, required=True)
        encoded = msgspec.json.encode(p)
        decoded = msgspec.json.decode(encoded, type=Parameter)
        assert decoded == p

    def test_field_name_mapping(self):
        """'in' in JSON maps to 'in_' in Python."""
        raw = b'{"type":"inline","name":"q","in":"query","schema":{"type":"string"}}'
        p = msgspec.json.decode(raw, type=Parameter)
        assert p.in_ == "query"

    def test_frozen(self):
        p = Parameter(name="x", in_="query", schema_={})
        with pytest.raises(Exception):
            p.name = "y"  # type: ignore


class TestParameterRef:
    def test_component_name_extraction(self):
        ref = ParameterRef(ref="#/components/parameters/abc123")
        assert ref.component_name == "abc123"

    def test_encode_decode_roundtrip(self):
        ref = ParameterRef(ref="#/components/parameters/xyz")
        encoded = msgspec.json.encode(ref)
        decoded = msgspec.json.decode(encoded, type=ParameterRef)
        assert decoded == ref


class TestParameterUnion:
    def test_decode_inline_tag(self):
        raw = b'{"type":"inline","name":"q","in":"query","schema":{}}'
        result = msgspec.json.decode(raw, type=ParameterUnion)
        assert isinstance(result, Parameter)

    def test_decode_ref_tag(self):
        raw = b'{"type":"ref","$ref":"#/components/parameters/abc"}'
        result = msgspec.json.decode(raw, type=ParameterUnion)
        assert isinstance(result, ParameterRef)
        assert result.component_name == "abc"


class TestServiceData:
    def test_full_roundtrip(self, sample_service_data: ServiceData):
        encoded = msgspec.json.encode(sample_service_data)
        decoded = msgspec.json.decode(encoded, type=ServiceData)
        assert decoded.service_name == sample_service_data.service_name
        assert len(decoded.operations) == len(sample_service_data.operations)

    def test_format_version_constraint(self):
        """format_version must be >= 3."""
        raw = b'{"format_version":2,"service_name":"x","servers":[],"components":{"parameters":{},"schemas":{}},"operations":{}}'
        with pytest.raises(msgspec.ValidationError):
            msgspec.json.decode(raw, type=ServiceData)

    def test_operations_contain_mixed_params(self, sample_service_data: ServiceData):
        op = sample_service_data.operations["get_user"]
        types = {type(p) for p in op.parameters}
        assert Parameter in types
        assert ParameterRef in types


class TestClientConfig:
    def test_defaults(self):
        cfg = ClientConfig()
        assert cfg.default_timeout == 30.0
        assert cfg.validate_on_execute is True
        assert cfg.pinned_services == ()
        assert cfg.cache_maxsize == 64

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("MAPI_CACHE_MAXSIZE", "128")
        monkeypatch.setenv("MAPI_PINNED_SERVICES", "pokeapi:rest:openapi,github:rest:openapi")
        cfg = ClientConfig.from_env()
        assert cfg.cache_maxsize == 128
        assert len(cfg.pinned_services) == 2

    def test_frozen(self):
        cfg = ClientConfig()
        with pytest.raises(Exception):
            cfg.cache_maxsize = 999  # type: ignore


class TestRequestConfig:
    def test_defaults(self):
        rc = RequestConfig(method="GET", url="https://example.com")
        assert rc.params == {}
        assert rc.headers == {}
        assert rc.json_body is None
        assert rc.timeout == 30.0


class TestResponseMetadata:
    def test_valid_status_literals(self):
        m = ResponseMetadata(service="svc", operation="op", duration_ms=42, status="success")
        assert m.status == "success"
        assert m.network_duration_ms is None

    def test_network_duration_field(self):
        m = ResponseMetadata(service="svc", operation="op", duration_ms=50,
                             network_duration_ms=42, status="success")
        assert m.duration_ms == 50
        assert m.network_duration_ms == 42
        decoded = msgspec.json.decode(msgspec.json.encode(m), type=ResponseMetadata)
        assert decoded.network_duration_ms == 42

    def test_encode_decode(self):
        m = ResponseMetadata(service="svc", operation="op", duration_ms=42,
                             network_duration_ms=30, status="error",
                             http_status=500, error_type="server_error")
        decoded = msgspec.json.decode(msgspec.json.encode(m), type=ResponseMetadata)
        assert decoded == m


class TestMapiResult:
    def test_frozen(self):
        meta = ResponseMetadata(service="s", operation="o", duration_ms=1, status="success")
        result = MapiResult(data={"id": 1}, metadata=meta)
        with pytest.raises(Exception):
            result.data = {}  # type: ignore

    def test_none_data_allowed(self):
        meta = ResponseMetadata(service="s", operation="o", duration_ms=1, status="error")
        result = MapiResult(data=None, metadata=meta)
        assert result.data is None


class TestExceptions:
    def test_mapi_error_attrs(self):
        e = MapiError("test", service="svc", operation="op")
        assert str(e) == "test"
        assert e.service == "svc"
        assert e.operation == "op"

    def test_transport_error_has_http_status(self):
        e = TransportError("bad", http_status=503)
        assert e.http_status == 503

    def test_rate_limit_is_transport_error(self):
        e = RateLimitError("429", http_status=429)
        assert isinstance(e, TransportError)
        assert isinstance(e, MapiError)

    def test_exception_chaining(self):
        cause = ValueError("original")
        e = TransportError("wrapped", cause=cause)
        assert e.__cause__ is cause
