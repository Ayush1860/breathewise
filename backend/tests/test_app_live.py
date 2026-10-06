from datetime import UTC, datetime, timedelta

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from backend import app as app_module
from backend.schemas import Pollutant, Source
from backend.store import Observation, Store, create_table
from ingest.openmeteo import CamsHour
from ml.baseline import baseline_forecast

NOW = datetime.now(UTC).replace(second=0, microsecond=0)
LAST = NOW.replace(minute=0) - timedelta(hours=1)


@pytest.fixture
def live(monkeypatch):
    with mock_aws():
        table = create_table(boto3.resource("dynamodb", region_name="ap-south-1"), "live")
        monkeypatch.setenv("TABLE_NAME", "live")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
        app_module.store.cache_clear()
        store = Store(table)
        yield TestClient(app_module.app), store
        app_module.store.cache_clear()


def seed(store):
    for h in range(24):
        o = Observation(
            "dl-rohini",
            LAST - timedelta(hours=h),
            Source.CPCB,
            {Pollutant.PM25: 150.0, Pollutant.PM10: 260.0, Pollutant.NO2: 50.0},
        )
        store.put_observation(o)
        store.update_latest(o)
    issued = LAST + timedelta(hours=1)
    cams = [
        CamsHour(issued + timedelta(hours=h), 120.0, 200.0, None, None, None, None)
        for h in range(-2, 13)
    ]
    store.put_forecast(baseline_forecast("dl-rohini", issued, [], cams))


def test_live_current_and_forecast(live):
    client, store = live
    seed(store)
    current = client.get("/aqi/current").json()
    assert current["source"] == "cpcb" and current["aqi"]["status"] == "ok"
    assert current["station"]["station_id"] == "dl-rohini"
    forecast = client.get("/aqi/forecast?station_id=dl-rohini").json()
    assert forecast["model_version"] == "baseline-camsbias-v0" and len(forecast["hours"]) == 12


def test_live_mock_header_is_ignored(live):
    client, store = live
    seed(store)
    assert client.get("/aqi/current", headers={"X-Mock-Scenario": "stale"}).json()["stale"] is False


def test_unknown_station_is_404_error_shape(live):
    client, _ = live
    response = client.get("/aqi/current?station_id=nowhere")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_no_data_yet_is_503_error_shape(live):
    client, _ = live
    response = client.get("/aqi/forecast")
    assert response.status_code == 503
    assert response.json()["error"] == "no_data"


def test_live_scoreboard_and_health(live):
    client, store = live
    seed(store)
    assert client.get("/scoreboard").json()["model_version"] == "baseline-camsbias-v0"
    assert client.get("/health").json()["status"] == "ok"


def test_live_refresh_is_rate_limited(live, monkeypatch):
    client, _ = live
    invoked = []
    monkeypatch.setattr(app_module, "trigger_ingest", lambda: invoked.append(True))
    assert client.post("/refresh").status_code == 202
    second = client.post("/refresh")
    assert second.status_code == 429 and int(second.headers["Retry-After"]) > 0
    assert invoked == [True]


def test_live_stations_include_distance(live):
    client, _ = live
    stations = client.get("/stations?lat=28.7499&lon=77.1183").json()["stations"]
    assert stations[0]["station_id"] == "dl-rohini"
    assert stations[0]["distance_km"] < 3


def test_live_advice_without_engine_is_503(live, monkeypatch):
    client, store = live
    seed(store)
    monkeypatch.setattr(app_module, "advise", None)
    body = {"profile": "respiratory", "activity": "walk", "duration_h": 2}
    response = client.post("/advice", json=body)
    assert response.status_code == 503
    assert response.json()["error"] == "advisory_unavailable"
