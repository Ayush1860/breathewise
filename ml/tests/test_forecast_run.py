from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from backend.store import Store, create_table
from ingest.openmeteo import CamsHour
from ingest.stations import load_stations
from ml.baseline import MODEL_VERSION
from ml.forecast_run import run_forecast

NOW = datetime(2026, 10, 6, 9, 20, tzinfo=UTC)
ISSUED = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


@pytest.fixture
def store():
    with mock_aws():
        table = create_table(boto3.resource("dynamodb", region_name="ap-south-1"), "t")
        yield Store(table, now=lambda: NOW)


def cams(lat, lon):
    return [
        CamsHour(ISSUED + timedelta(hours=h), 100.0, 170.0, None, None, None, None)
        for h in range(-96, 25)
    ]


def test_forecast_written_for_every_station(store):
    stations = load_stations()
    summary = run_forecast(NOW, stations, store, cams_for=cams)
    assert summary == {s.station_id: MODEL_VERSION for s in stations}
    doc = store.current_forecast(stations[0].station_id)
    assert doc.issued_at == ISSUED
    assert len(store.forecast_log(stations[0].station_id, MODEL_VERSION, ISSUED)) == 12


def test_failing_station_keeps_previous_forecast(store):
    stations = load_stations()[:1]
    run_forecast(NOW, stations, store, cams_for=cams)

    def broken(lat, lon):
        raise ValueError("CAMS forecast missing")

    later = NOW + timedelta(hours=1)
    summary = run_forecast(later, stations, store, cams_for=broken)
    assert summary == {stations[0].station_id: None}
    assert store.current_forecast(stations[0].station_id).issued_at == ISSUED


def _weather(lat, lon):
    from ingest.openmeteo import WeatherHour

    return [
        WeatherHour(ISSUED + timedelta(hours=h), 25.0, 50.0, 3.0, 270.0, 400.0, 0.0, 990.0)
        for h in range(-48, 25)
    ]


class FakeModel:
    model_version = "lgbm-fake"
    station_codes = {s.station_id: i for i, s in enumerate(load_stations())}

    def __init__(self, fail=False):
        self.fail = fail


def test_model_used_when_available(store, monkeypatch):
    from ml import forecast_run

    def fake_model_forecast(model, station_id, code, issued, obs, weather, cams_hours):
        doc = forecast_run.baseline_forecast(station_id, issued, obs, cams_hours)
        return doc.model_copy(update={"model_version": model.model_version})

    monkeypatch.setattr(forecast_run, "model_forecast", fake_model_forecast)
    stations = load_stations()[:1]
    summary = run_forecast(
        NOW, stations, store, cams_for=cams, weather_for=_weather, model=FakeModel()
    )
    assert summary == {stations[0].station_id: "lgbm-fake"}


def test_model_failure_falls_back_to_baseline(store, monkeypatch):
    from ml import forecast_run

    def broken(*args, **kwargs):
        raise ValueError("live weather forecast does not reach t+12")

    monkeypatch.setattr(forecast_run, "model_forecast", broken)
    stations = load_stations()[:1]
    summary = run_forecast(
        NOW, stations, store, cams_for=cams, weather_for=_weather, model=FakeModel()
    )
    assert summary == {stations[0].station_id: MODEL_VERSION}
