import io
import urllib.error

import pytest

from ingest.http import SourceError, get_json


class FakeOpener:
    """Returns queued outcomes in order: bytes -> response body, Exception -> raised."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b""))


def test_returns_parsed_json_and_encodes_params():
    opener = FakeOpener(b'{"ok": 1}')
    assert get_json("https://x/api", {"a": 1, "b": "z"}, opener=opener, sleep=lambda s: None) == {
        "ok": 1
    }
    request, timeout = opener.requests[0]
    assert request.full_url == "https://x/api?a=1&b=z"
    assert timeout == 10.0


def test_sends_headers():
    opener = FakeOpener(b"{}")
    get_json("https://x", headers={"X-API-Key": "k"}, opener=opener, sleep=lambda s: None)
    assert opener.requests[0][0].get_header("X-api-key") == "k"


def test_retries_transient_failures_then_succeeds():
    opener = FakeOpener(urllib.error.URLError("down"), _http_error(503), b"[1]")
    sleeps = []
    assert get_json("https://x", opener=opener, sleep=sleeps.append) == [1]
    assert len(sleeps) == 2
    assert 1.0 <= sleeps[0] < 2.0 <= sleeps[1] < 3.0  # exponential backoff + jitter


def test_gives_up_after_three_attempts():
    opener = FakeOpener(*[_http_error(502)] * 3)
    with pytest.raises(SourceError) as info:
        get_json("https://x", opener=opener, sleep=lambda s: None)
    assert info.value.status == 502
    assert len(opener.requests) == 3


def test_does_not_retry_client_errors():
    opener = FakeOpener(_http_error(401))
    with pytest.raises(SourceError) as info:
        get_json("https://x", opener=opener, sleep=lambda s: None)
    assert info.value.status == 401
    assert len(opener.requests) == 1


def test_retries_rate_limit():
    opener = FakeOpener(_http_error(429), b"{}")
    assert get_json("https://x", opener=opener, sleep=lambda s: None) == {}


def test_invalid_json_is_source_error():
    with pytest.raises(SourceError):
        get_json("https://x", opener=FakeOpener(b"<html>"), sleep=lambda s: None)
