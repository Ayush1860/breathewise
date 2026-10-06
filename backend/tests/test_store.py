from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from backend.schemas import Pollutant, Source
from backend.store import Observation, Store, create_table

P = Pollutant
T0 = datetime(2026, 10, 6, 8, 0, tzinfo=UTC)


@pytest.fixture
def store():
    with mock_aws():
        table = create_table(boto3.resource("dynamodb", region_name="ap-south-1"), "test")
        yield Store(table, now=lambda: T0 + timedelta(minutes=20))


def obs(source, hour=0, pm25=100.0, station="dl-rohini"):
    return Observation(station, T0 + timedelta(hours=hour), source, {P.PM25: pm25, P.PM10: 180.0})


def test_round_trips_an_observation(store):
    assert store.put_observation(obs(Source.CPCB))
    [got] = store.observations("dl-rohini", since=T0 - timedelta(hours=1))
    assert got == obs(Source.CPCB)


def test_higher_priority_source_overwrites_lower(store):
    store.put_observation(obs(Source.CAMS_MODEL, pm25=50.0))
    assert store.put_observation(obs(Source.CPCB, pm25=120.0))
    [got] = store.observations("dl-rohini", since=T0)
    assert (got.source, got.values[P.PM25]) == (Source.CPCB, 120.0)


def test_lower_priority_source_never_overwrites_higher(store):
    store.put_observation(obs(Source.CPCB, pm25=120.0))
    assert not store.put_observation(obs(Source.OPENAQ, pm25=50.0))
    [got] = store.observations("dl-rohini", since=T0)
    assert got.source is Source.CPCB


def test_same_source_backfill_overwrites(store):
    store.put_observation(obs(Source.CPCB, pm25=120.0))
    assert store.put_observation(obs(Source.CPCB, pm25=125.0))
    assert store.observations("dl-rohini", since=T0)[0].values[P.PM25] == 125.0


def test_observations_are_sorted_and_filtered_by_since(store):
    for h in (2, 0, 1):
        store.put_observation(obs(Source.CPCB, hour=h))
    times = [o.time for o in store.observations("dl-rohini", since=T0 + timedelta(hours=1))]
    assert times == [T0 + timedelta(hours=1), T0 + timedelta(hours=2)]


def test_latest_only_moves_forward(store):
    store.update_latest(obs(Source.CPCB, hour=2))
    store.update_latest(obs(Source.CPCB, hour=1))
    assert store.latest("dl-rohini").time == T0 + timedelta(hours=2)


def test_latest_none_for_unknown_station(store):
    assert store.latest("nowhere") is None


def test_observation_items_carry_30_day_ttl(store):
    store.put_observation(obs(Source.CPCB))
    item = store.table.get_item(Key={"pk": "STATION#dl-rohini", "sk": f"OBS#{T0.isoformat()}"})
    assert item["Item"]["ttl"] == int((T0 + timedelta(minutes=20) + timedelta(days=30)).timestamp())


def test_health_records_success_and_failure(store):
    store.record_health(Source.CPCB, ok=False, error="HTTP 503")
    store.record_health(Source.OPENAQ, ok=True)
    health = {h.source: h for h in store.health()}
    assert health[Source.CPCB].last_error == "HTTP 503"
    assert health[Source.CPCB].last_success_at is None
    assert health[Source.OPENAQ].last_success_at == T0 + timedelta(minutes=20)


def test_success_keeps_previous_failure_time(store):
    store.record_health(Source.CPCB, ok=False, error="HTTP 503")
    store.record_health(Source.CPCB, ok=True)
    [h] = [h for h in store.health() if h.source is Source.CPCB]
    assert h.last_failure_at is not None and h.last_success_at is not None


def _forecast(model_version="baseline-camsbias-v0", issued=T0):
    from backend.scripts.make_fixtures import build_fixtures

    doc = build_fixtures()["aqi_forecast.json"]
    shift = issued - doc.issued_at
    hours = [h.model_copy(update={"target_time": h.target_time + shift}) for h in doc.hours]
    return doc.model_copy(
        update={"issued_at": issued, "model_version": model_version, "hours": hours}
    )


def test_current_forecast_round_trip(store):
    doc = _forecast()
    store.put_forecast(doc)
    assert store.current_forecast("dl-rohini") == doc


def test_current_forecast_none_when_missing(store):
    assert store.current_forecast("dl-rohini") is None


def test_forecast_log_filters_by_model_version(store):
    store.put_forecast(_forecast("baseline-camsbias-v0", T0))
    store.put_forecast(_forecast("lgbm-v1-abc", T0 + timedelta(hours=1)))
    entries = store.forecast_log("dl-rohini", "lgbm-v1-abc", since=T0 - timedelta(days=1))
    assert len(entries) == 12
    assert {e.model_version for e in entries} == {"lgbm-v1-abc"}
    first = entries[0]
    assert first.issued_at == T0 + timedelta(hours=1)
    assert first.horizon_h == 1
    assert first.pm25.q50 > 0


def test_forecast_log_since_filters_by_target_time(store):
    store.put_forecast(_forecast(issued=T0))
    entries = store.forecast_log("dl-rohini", "baseline-camsbias-v0", since=T0 + timedelta(hours=6))
    assert [e.horizon_h for e in entries] == list(range(6, 13))
