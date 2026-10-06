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
