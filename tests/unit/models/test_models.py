# tests/unit/models/test_models.py
from __future__ import annotations

import msgspec
import pytest

from mapi.exceptions import (
    MapiError,
    RateLimitError,
    SpecUpdateAvailableWarning,
    TransportError,
)
from mapi.models import (
    ClientConfig,
    HeadersDict,
    MapiResult,
    Parameter,
    ParameterRef,
    ParameterUnion,
    RequestConfig,
    ResponseMetadata,
    ServiceData,
    SpecDiffResult,
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
        with pytest.raises((AttributeError, TypeError)):
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
        assert cfg.multiplexed is True
        assert cfg.retries == 0
        assert cfg.server_variables == {}
        assert cfg.default_headers == {"User-Agent": "mapi/0.1.0", "Accept": "application/json"}

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("MAPI_CACHE_MAXSIZE", "128")
        monkeypatch.setenv("MAPI_PINNED_SERVICES", "pokeapi:rest:openapi,github:rest:openapi")
        cfg = ClientConfig.from_env()
        assert cfg.cache_maxsize == 128
        assert len(cfg.pinned_services) == 2

    def test_frozen(self):
        cfg = ClientConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.cache_maxsize = 999  # type: ignore


class TestRequestConfig:
    def test_defaults(self):
        rc = RequestConfig(method="GET", url="https://example.com")
        assert rc.params == {}
        assert rc.headers == {}
        assert rc.json_body is None
        assert rc.timeout == 30.0

    def test_to_curl_basic_get(self):
        cfg = RequestConfig(method="GET", url="https://api.example.com/v1/users")
        curl_str = cfg.to_curl()
        assert curl_str == "curl -X GET 'https://api.example.com/v1/users'"

    def test_to_curl_with_query_params(self):
        cfg = RequestConfig(
            method="GET",
            url="https://api.example.com/search",
            params={"q": "ditto", "limit": 10},
        )
        curl_str = cfg.to_curl()
        assert "curl -X GET 'https://api.example.com/search?q=ditto&limit=10'" in curl_str

    def test_to_curl_redact_auth_default(self):
        cfg = RequestConfig(
            method="POST",
            url="https://api.example.com/data",
            headers={
                "Authorization": "Bearer secret_tok_123",
                "X-Api-Key": "my_secret_key",
                "Content-Type": "application/json",
            },
        )
        curl_str = cfg.to_curl()
        assert "-H 'Authorization: [REDACTED]'" in curl_str
        assert "-H 'X-Api-Key: [REDACTED]'" in curl_str
        assert "-H 'Content-Type: application/json'" in curl_str

    def test_to_curl_no_redact_auth(self):
        cfg = RequestConfig(
            method="POST",
            url="https://api.example.com/data",
            headers={"Authorization": "Bearer secret_tok_123"},
        )
        curl_str = cfg.to_curl(redact_auth=False)
        assert "-H 'Authorization: Bearer secret_tok_123'" in curl_str

    def test_to_curl_with_json_body_and_escaping(self):
        cfg = RequestConfig(
            method="POST",
            url="https://api.example.com/users",
            json_body={"name": "O'Connor", "age": 30},
        )
        curl_str = cfg.to_curl()
        assert "-X POST 'https://api.example.com/users'" in curl_str
        assert "-d '" in curl_str
        assert "O'\\''Connor" in curl_str


class TestResponseMetadata:
    def test_valid_status_literals(self):
        m = ResponseMetadata(service="svc", operation="op", duration_ms=42, status="success")
        assert m.status == "success"
        assert m.network_duration_ms is None

    def test_network_duration_field(self):
        m = ResponseMetadata(
            service="svc", operation="op", duration_ms=50, network_duration_ms=42, status="success"
        )
        assert m.duration_ms == 50
        assert m.network_duration_ms == 42
        decoded = msgspec.json.decode(msgspec.json.encode(m), type=ResponseMetadata)
        assert decoded.network_duration_ms == 42

    def test_encode_decode(self):
        m = ResponseMetadata(
            service="svc",
            operation="op",
            duration_ms=42,
            network_duration_ms=30,
            status="error",
            http_status=500,
            error_type="server_error",
        )
        decoded = msgspec.json.decode(msgspec.json.encode(m), type=ResponseMetadata)
        assert decoded == m

    def test_header_properties(self):
        headers = HeadersDict(
            {
                "Content-Type": "application/json",
                "ETag": "W/123",
                "Retry-After": "10.5",
                "X-RateLimit-Limit": "1000",
                "X-RateLimit-Remaining": "999",
                "X-RateLimit-Reset": "1700000000",
            }
        )
        m = ResponseMetadata(
            service="svc",
            operation="op",
            duration_ms=10,
            status="success",
            headers=headers,
        )
        assert m.content_type == "application/json"
        assert m.etag == "W/123"
        assert m.retry_after == 10.5
        assert m.rate_limit_limit == 1000
        assert m.rate_limit_remaining == 999
        assert m.rate_limit_reset == 1700000000


class TestMapiResult:
    def test_frozen(self):
        meta = ResponseMetadata(service="s", operation="o", duration_ms=1, status="success")
        result = MapiResult(data={"id": 1}, metadata=meta)
        with pytest.raises((AttributeError, TypeError)):
            result.data = {}  # type: ignore

    def test_none_data_allowed(self):
        meta = ResponseMetadata(service="s", operation="o", duration_ms=1, status="error")
        result = MapiResult(data=None, metadata=meta)
        assert result.data is None


class TestSpecDiffResult:
    def test_spec_diff_result_defaults(self):
        diff = SpecDiffResult(has_diff=True, provider="p", api="REST", added_operations=["op1"])
        assert diff.has_diff is True
        assert diff.added_operations == ["op1"]
        assert diff.removed_operations == []


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

    def test_spec_warning_inheritance(self):
        assert issubclass(SpecUpdateAvailableWarning, UserWarning)

    def test_exception_chaining(self):
        cause = ValueError("original")
        e = TransportError("wrapped", cause=cause)
        assert e.__cause__ is cause
