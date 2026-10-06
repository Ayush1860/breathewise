from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.schemas import Verdict
from backend.scripts.export_openapi import OPENAPI_PATH, render

client = TestClient(app)


@pytest.mark.parametrize(
    "path",
    ["/stations", "/aqi/current", "/aqi/forecast", "/scoreboard", "/metrics", "/health"],
)
def test_read_endpoints_return_payload(path):
    response = client.get(path)
    assert response.status_code == 200
    assert "generated_at" in response.json()


def test_mock_scenario_header_selects_stale_variant():
    response = client.get("/aqi/current", headers={"X-Mock-Scenario": "stale"})
    assert response.json()["stale"] is True


def test_unknown_scenario_falls_back_to_default():
    response = client.get("/aqi/current", headers={"X-Mock-Scenario": "nonsense"})
    assert response.status_code == 200
    assert response.json()["stale"] is False


def test_advice_returns_verdict():
    body = {"profile": "respiratory", "activity": "walk", "duration_h": 2}
    response = client.post("/advice", json=body)
    assert response.status_code == 200
    assert response.json()["verdict"] in {v.value for v in Verdict}


@pytest.mark.parametrize(
    "scenario,verdict",
    [
        ("go", "GO"),
        ("go_with_n95", "GO_WITH_N95"),
        ("avoid", "AVOID"),
        ("reduce_exposure", "REDUCE_EXPOSURE"),
    ],
)
def test_advice_scenario_header_selects_verdict(scenario, verdict):
    body = {"profile": "healthy_adult", "activity": "walk", "duration_h": 1}
    response = client.post("/advice", json=body, headers={"X-Mock-Scenario": scenario})
    assert response.json()["verdict"] == verdict


def test_advice_rejects_duration_over_12h():
    body = {"profile": "respiratory", "activity": "walk", "duration_h": 13}
    assert client.post("/advice", json=body).status_code == 422


def test_refresh_accepted_returns_202():
    assert client.post("/refresh").status_code == 202


def test_refresh_rate_limited_returns_429_with_retry_after():
    response = client.post("/refresh", headers={"X-Mock-Scenario": "rate_limited"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(response.json()["retry_after_s"])


def test_cors_allows_local_frontend():
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_openapi_file_is_current():
    expected = render()
    assert (
        Path(OPENAPI_PATH).read_text(encoding="utf-8") == expected
    ), "docs/openapi.json is stale; run: uv run python -m backend.scripts.export_openapi"


def test_openapi_marks_always_sent_fields_required():
    schemas = app.openapi()["components"]["schemas"]
    assert "params" in schemas["Message"]["required"]
    assert "basis" in schemas["ForecastResponse"]["required"]
    assert "hourly_index" in schemas["CurrentAqiResponse"]["required"]


def test_errors_use_error_response_shape():
    response = client.get("/no-such-route")
    assert response.status_code == 404
    assert set(response.json()) == {"error", "message"}


def test_openapi_declares_404_for_station_endpoints():
    paths = app.openapi()["paths"]
    for path in ("/aqi/current", "/aqi/forecast", "/scoreboard"):
        assert "404" in paths[path]["get"]["responses"], path
    assert "404" in paths["/advice"]["post"]["responses"]


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/stations", "public, max-age=300"),
        ("/metrics", "public, max-age=300"),
        ("/aqi/current", "public, max-age=60"),
        ("/aqi/forecast", "public, max-age=60"),
        ("/scoreboard", "public, max-age=300"),
        ("/health", "no-store"),
    ],
)
def test_cache_control_per_endpoint(path, expected):
    assert client.get(path).headers["cache-control"] == expected


def test_post_endpoints_are_not_cached():
    assert client.post("/refresh").headers["cache-control"] == "no-store"


def test_lambda_handler_ignores_warmup_ping():
    from backend.lambda_api import handler

    assert handler({"warmup": True}, None) == {"warmup": "ok"}
