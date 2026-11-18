"""Bounded HTTP retry tests; all requests are mocked (no network)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from typing import Any
import urllib.error
import urllib.request

import pytest
import requests

from scripts import fetch_stats


@pytest.fixture(autouse=True)
def clear_retry_budget(monkeypatch: pytest.MonkeyPatch):
    fetch_stats._reset_retry_budget()
    monkeypatch.setattr(fetch_stats.random, "uniform", lambda _a, _b: 0.0)
    waits: list[float] = []
    monkeypatch.setattr(fetch_stats.time, "sleep", waits.append)
    yield waits
    fetch_stats._reset_retry_budget()


def test_one_transient_get_retry_preserves_success(clear_retry_budget, monkeypatch):
    calls = []
    responses: list[Any] = [
        fetch_stats.RetryableFetchError("HTTP 503 from example"),
        {"ok": True},
    ]

    def attempt(*args):
        calls.append(args)
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(fetch_stats, "_request_json_once", attempt)
    assert fetch_stats.request_json("https://one.example/info") == {"ok": True}
    assert len(calls) == 2
    assert clear_retry_budget == [0.5]
    assert fetch_stats._retry_used == 1


def test_only_one_retry_even_if_second_attempt_fails(clear_retry_budget, monkeypatch):
    calls = []

    def attempt(*args):
        calls.append(args)
        raise fetch_stats.RetryableFetchError("HTTP 503 from example")

    monkeypatch.setattr(fetch_stats, "_request_json_once", attempt)
    with pytest.raises(fetch_stats.FetchError, match="HTTP 503"):
        fetch_stats.request_json("https://one.example/info")
    assert len(calls) == 2
    assert len(clear_retry_budget) == 1


def test_no_retry_for_non_get_even_on_transient_marker(clear_retry_budget, monkeypatch):
    calls = []

    def attempt(*args):
        calls.append(args)
        raise fetch_stats.RetryableFetchError("HTTP 503 from example")

    monkeypatch.setattr(fetch_stats, "_request_json_once", attempt)
    with pytest.raises(fetch_stats.FetchError):
        fetch_stats.request_json("https://one.example/api/meta", method="POST", json_body={})
    assert len(calls) == 1
    assert clear_retry_budget == []


@pytest.mark.parametrize("message", [
    "HTTP 404 from https://test.example",
    "SSL certificate_verify_failed",
    "NameResolutionError: Failed to resolve",
    "redirected to different host: https://outside.example",
    "payload exceeded 2000000 bytes limit",
])
def test_permanent_errors_are_not_retried(clear_retry_budget, monkeypatch, message):
    calls = []

    def attempt(*args):
        calls.append(args)
        raise fetch_stats.FetchError(message)

    monkeypatch.setattr(fetch_stats, "_request_json_once", attempt)
    with pytest.raises(fetch_stats.FetchError, match=None):
        fetch_stats.request_json("https://one.example/info")
    assert len(calls) == 1
    assert clear_retry_budget == []


@pytest.mark.parametrize("retry_after,expected", [
    ("1.5", 1.5),
    ("0", 0.5),
    ("20", None),
    ("Infinity", None),
])
def test_retry_after_delta_is_bounded(clear_retry_budget, retry_after, expected):
    assert fetch_stats._bounded_retry_delay(retry_after) == expected


def test_http_date_retry_after_beyond_cap_skips(clear_retry_budget):
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    retry_after = format_datetime(future, usegmt=True)
    assert fetch_stats._bounded_retry_delay(retry_after) is None


def test_global_budget_prevents_retry_storm(clear_retry_budget, monkeypatch):
    monkeypatch.setattr(fetch_stats, "MAX_GET_RETRIES_PER_RUN", 1)
    fetch_stats._reset_retry_budget()
    calls = []

    def attempt(*args):
        calls.append(args)
        if len(calls) == 1:
            raise fetch_stats.RetryableFetchError("HTTP 502 from example")
        if len(calls) == 2:
            return {"ok": True}
        raise fetch_stats.RetryableFetchError("HTTP 502 from example")

    monkeypatch.setattr(fetch_stats, "_request_json_once", attempt)
    assert fetch_stats.request_json("https://one.example/info") == {"ok": True}
    with pytest.raises(fetch_stats.FetchError, match="HTTP 502"):
        fetch_stats.request_json("https://two.example/info")
    assert len(calls) == 3
    assert fetch_stats._retry_used == 1
    assert clear_retry_budget == [0.5]


class FakeResponse:
    def __init__(self, status: int, *, retry_after: str | None = None, stream_failure=None):
        self.status_code = status
        self.headers = {"Content-Type": "application/json"}
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after
        self.encoding = "utf-8"
        self.stream_failure = stream_failure
        self.closed = False

    def iter_content(self, chunk_size: int):
        if self.stream_failure:
            raise self.stream_failure
        yield b'{"ok": true}'

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.max_redirects = None

    def mount(self, prefix, adapter):
        return None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        return None


def test_requests_backend_retries_429_once_and_closes_responses(
    clear_retry_budget, monkeypatch,
):
    rejected = FakeResponse(429, retry_after="1")
    accepted = FakeResponse(200)
    session = FakeSession([rejected, accepted])
    monkeypatch.setattr(requests, "Session", lambda: session)

    result = fetch_stats.request_json("https://a.example/info", expected_host="a.example")
    assert result == {"ok": True}
    assert session.calls == [("GET", "https://a.example/info")] * 2
    assert rejected.closed and accepted.closed
    assert clear_retry_budget == [1.0]


@pytest.mark.parametrize("response_status", [400, 401, 403, 404, 501])
def test_requests_backend_does_not_retry_nontransient_status(
    clear_retry_budget, monkeypatch, response_status,
):
    rejected = FakeResponse(response_status)
    session = FakeSession([rejected])
    monkeypatch.setattr(requests, "Session", lambda: session)

    with pytest.raises(fetch_stats.FetchError, match=str(response_status)):
        fetch_stats.request_json("https://a.example/info", expected_host="a.example")
    assert len(session.calls) == 1
    assert rejected.closed
    assert clear_retry_budget == []


def test_requests_backend_retries_read_timeout(clear_retry_budget, monkeypatch):
    session = FakeSession([
        requests.exceptions.ReadTimeout("read timed out"),
        FakeResponse(200),
    ])
    monkeypatch.setattr(requests, "Session", lambda: session)
    assert fetch_stats.request_json("https://a.example/info", expected_host="a.example") == {
        "ok": True
    }
    assert len(session.calls) == 2


def test_requests_backend_does_not_retry_tls_or_dns(clear_retry_budget, monkeypatch):
    for error in (
        requests.exceptions.SSLError("certificate verify failed"),
        requests.exceptions.ConnectionError("Failed to resolve host"),
    ):
        session = FakeSession([error])
        monkeypatch.setattr(requests, "Session", lambda: session)
        with pytest.raises(fetch_stats.FetchError):
            fetch_stats.request_json("https://a.example/info", expected_host="a.example")
        assert len(session.calls) == 1
    assert clear_retry_budget == []


def test_requests_backend_retries_stream_read_timeout(clear_retry_budget, monkeypatch):
    session = FakeSession([
        FakeResponse(200, stream_failure=requests.exceptions.ConnectionError("Read timed out.")),
        FakeResponse(200),
    ])
    monkeypatch.setattr(requests, "Session", lambda: session)
    assert fetch_stats.request_json("https://a.example/info", expected_host="a.example") == {
        "ok": True
    }
    assert len(session.calls) == 2


class FakeUrlopenResponse:
    def __init__(self):
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self.bytes_left = b'{"ok": true}'

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _chunk_size):
        content, self.bytes_left = self.bytes_left, b""
        return content


def test_urllib_fallback_retries_http_error_with_cap(clear_retry_budget, monkeypatch):
    monkeypatch.setattr(fetch_stats, "requests", None)
    calls = []
    headers = Message()
    headers["Retry-After"] = "1"

    def urlopen(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "Too many requests", headers, None)
        return FakeUrlopenResponse()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert fetch_stats.request_json("https://a.example/info", expected_host="a.example") == {
        "ok": True
    }
    assert len(calls) == 2
    assert clear_retry_budget == [1.0]
