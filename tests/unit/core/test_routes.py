import json

import httpx
import pytest

from ksef2._core import routes


def test_route_constant_is_its_path_string() -> None:
    query = routes.CollectiveIdentifierRoutes.QUERY

    assert query == "/collective-identifiers/query"
    assert f"{query}" == "/collective-identifiers/query"
    assert json.dumps({"path": query}) == '{"path": "/collective-identifiers/query"}'


def test_route_constant_carries_its_http_method() -> None:
    send = routes.InvoiceRoutes.SEND

    assert send.method == routes.HttpMethod.POST
    assert send.path == "/sessions/online/{referenceNumber}/invoices"


def test_two_methods_on_one_path_stay_separate_routes() -> None:
    generate = routes.TokenRoutes.GENERATE_TOKEN
    listing = routes.TokenRoutes.LIST_TOKENS

    assert generate.path == "/tokens"
    assert listing.path == "/tokens"
    assert generate.method == routes.HttpMethod.POST
    assert listing.method == routes.HttpMethod.GET


def test_every_registered_route_is_a_distinct_method_and_path() -> None:
    pairs = [(route.method, route.path) for route in routes.ALL_ROUTES]

    assert len(pairs) == len(set(pairs))


def test_retryable_post_paths_lookup_by_plain_path_string() -> None:
    assert "/auth/challenge" in routes.RETRYABLE_POST_PATHS
    assert "/auth/sessions" not in routes.RETRYABLE_POST_PATHS


def test_path_identifiers_cannot_redirect_authenticated_requests() -> None:
    affected_routes = (
        (
            routes.AuthRoutes.TERMINATE_AUTH_SESSION,
            "referenceNumber",
            "/auth/sessions/",
        ),
        (
            routes.TestDataRoutes.UPDATE_CERTIFICATE,
            "serialNumber",
            "/testdata/certificates/",
        ),
        (
            routes.CollectiveIdentifierRoutes.QUERY_BY_KSEF_NUMBER,
            "ksefNumber",
            "/collective-identifiers/ksef/",
        ),
    )
    identifiers = (
        ("../target", "..%2Ftarget"),
        ("%2e%2e%2ftarget", "%252e%252e%252ftarget"),
        ("target?query#fragment", "target%3Fquery%23fragment"),
        ("target\\child", "target%5Cchild"),
        (
            "1234567890-20250625-ABC123-DEF456-07",
            "1234567890-20250625-ABC123-DEF456-07",
        ),
    )
    with httpx.Client(base_url="https://example.invalid/v2/") as client:
        for route, parameter, prefix in affected_routes:
            for identifier, expected in identifiers:
                request = client.build_request(
                    route.method,
                    route.format(**{parameter: identifier}),
                    headers={"Authorization": "Bearer placeholder"},
                )
                assert request.url.raw_path == f"/v2{prefix}{expected}".encode()
                assert request.headers["Authorization"] == "Bearer placeholder"
            for identifier in ("", ".", ".."):
                with pytest.raises(ValueError, match="path identifier"):
                    _ = route.format(**{parameter: identifier})
