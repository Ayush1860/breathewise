from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from backend import service
from backend.naqi import averaged, hourly_pm_index, sub_index
from backend.schemas import Band, Pollutant, Source
from backend.store import Observation, Store, create_table
from ingest.stations import load_stations

P = Pollutant
NOW = datetime(2026, 10, 6, 9, 20, tzinfo=UTC)
LAST = datetime(2026, 10, 6, 8, 0, tzinfo=UTC)
STATIONS = load_stations()
VENUE = STATIONS[0]


@pytest.fixture
def store():
    with mock_aws():
        table = create_table(boto3.resource("dynamodb", region_name="ap-south-1"), "t")
        yield Store(table, now=lambda: NOW)


def fill(store, hours=24, last=LAST, values=None, source=Source.CPCB):
    values = values or {P.PM25: 150.0, P.PM10: 260.0, P.NO2: 60.0, P.O3: 40.0}
    for h in range(hours):
        o = Observation(VENUE.station_id, last - timedelta(hours=h), source, dict(values))
        store.put_observation(o)
        store.update_latest(o)


def test_resolve_station_by_id_and_nearest_location():
    assert service.resolve_station(STATIONS, "dl-bawana", None, None).station_id == "dl-bawana"
    nearest = service.resolve_station(STATIONS, None, 28.75, 77.118)
    assert nearest.station_id == VENUE.station_id
    assert service.resolve_station(STATIONS, None, None, None).is_venue_default


def test_resolve_unknown_station_raises_not_found():
    with pytest.raises(service.NotFound):
        service.resolve_station(STATIONS, "nowhere", None, None)


def test_current_aqi_uses_cpcb_averaging(store):
    fill(store)
    current = service.current_aqi(store, VENUE, NOW, user_location=None)
    assert current.aqi.status == "ok"
    assert current.aqi.aqi == max(sub_index(P.PM25, 150.0), sub_index(P.PM10, 260.0))
    assert current.aqi.dominant_pollutant is P.PM25
    assert current.hourly_index == hourly_pm_index(150.0, 260.0)
    assert current.hourly_band is Band.VERY_POOR
    assert current.source is Source.CPCB
    assert current.observed_at == LAST + timedelta(hours=1)
    assert (current.stale, current.age_minutes) == (False, 20)


def test_current_aqi_insufficient_with_short_history(store):
    fill(store, hours=10)
    current = service.current_aqi(store, VENUE, NOW, user_location=None)
    assert current.aqi.status == "insufficient_data"
    assert current.hourly_index is not None


def test_current_aqi_stale_after_three_hours(store):
    fill(store, last=LAST - timedelta(hours=3))
    current = service.current_aqi(store, VENUE, NOW, user_location=None)
    assert current.stale is True
    assert current.age_minutes == 200


def test_current_aqi_reports_distance_to_user(store):
    fill(store)
    current = service.current_aqi(store, VENUE, NOW, user_location=(28.7499, 77.1183))
    assert current.station.distance_km == pytest.approx(1.9, abs=0.3)


def test_current_aqi_none_when_station_has_no_data(store):
    assert service.current_aqi(store, VENUE, NOW, user_location=None) is None


def test_current_aqi_reports_cams_source(store):
    fill(store, source=Source.CAMS_MODEL)
    assert service.current_aqi(store, VENUE, NOW, None).source is Source.CAMS_MODEL


def test_averaging_window_aligns_on_latest_hour(store):
    fill(store, hours=24, values={P.PM25: 100.0, P.PM10: 100.0, P.NO2: 10.0})
    fill(
        store,
        hours=1,
        last=LAST - timedelta(hours=30),
        values={P.PM25: 900.0, P.PM10: 900.0, P.NO2: 10.0},
    )
    current = service.current_aqi(store, VENUE, NOW, None)
    assert current.aqi.aqi == sub_index(P.PM25, averaged(P.PM25, [100.0] * 24))  # 900s excluded


def _forecast(issued, mv="baseline-camsbias-v0"):
    from ingest.openmeteo import CamsHour
    from ml.baseline import baseline_forecast

    cams = [
        CamsHour(issued + timedelta(hours=h), 100.0, 170.0, None, None, None, None)
        for h in range(-2, 13)
    ]
    doc = baseline_forecast(VENUE.station_id, issued, [], cams)
    return doc.model_copy(update={"model_version": mv})


def test_forecast_view_fresh_and_stale(store):
    store.put_forecast(_forecast(LAST + timedelta(hours=1)))
    fresh = service.forecast_view(store, VENUE, NOW)
    assert (fresh.stale, fresh.age_minutes, fresh.generated_at) == (False, 20, NOW)
    later = service.forecast_view(store, VENUE, NOW + timedelta(hours=2))
    assert later.stale is True


def test_forecast_view_none_without_forecast(store):
    assert service.forecast_view(store, VENUE, NOW) is None


def test_scoreboard_pairs_forecasts_with_actuals(store):
    issued = LAST - timedelta(hours=12)
    store.put_forecast(_forecast(issued))
    fill(store, hours=12, values={P.PM25: 110.0, P.PM10: 200.0})
    board = service.scoreboard(store, VENUE, None, "pm25", NOW)
    assert board.model_version == "baseline-camsbias-v0"
    h1 = [p for p in board.points if p.horizon_h == 1]
    assert h1 and h1[0].actual == 110.0
    score = {s.horizon_h: s for s in board.per_horizon}
    assert score[1].mae == pytest.approx(10.0) and score[1].n == 1


def test_scoreboard_never_mixes_model_versions(store):
    store.put_forecast(_forecast(LAST - timedelta(hours=5), "baseline-camsbias-v0"))
    store.put_forecast(_forecast(LAST - timedelta(hours=4), "lgbm-v1-x"))
    board = service.scoreboard(store, VENUE, "baseline-camsbias-v0", "pm25", NOW)
    assert {p.issued_at for p in board.points} == {LAST - timedelta(hours=5)}


def test_scoreboard_defaults_to_current_model_version(store):
    store.put_forecast(_forecast(LAST - timedelta(hours=5), "baseline-camsbias-v0"))
    store.put_forecast(_forecast(LAST - timedelta(hours=4), "lgbm-v1-x"))
    assert service.scoreboard(store, VENUE, None, "pm25", NOW).model_version == "lgbm-v1-x"


def test_refresh_lock_is_global_and_expires(store):
    assert service.try_refresh(store, NOW) is None
    retry = service.try_refresh(store, NOW + timedelta(minutes=1))
    assert retry == 240
    assert service.try_refresh(store, NOW + timedelta(minutes=5)) is None


def test_health_reports_degraded_when_data_stale(store):
    fill(store, last=LAST - timedelta(hours=4))
    store.record_health(Source.CPCB, ok=False, error="HTTP 503")
    health = service.health(store, STATIONS, NOW)
    assert health.status == "degraded"
    assert any(s.source is Source.CPCB for s in health.sources)
    venue = next(s for s in health.stations if s.station_id == VENUE.station_id)
    assert venue.last_source is Source.CPCB


def test_health_ok_when_fresh(store):
    fill(store)
    store.put_forecast(_forecast(LAST + timedelta(hours=1)))
    health = service.health(store, STATIONS, NOW)
    assert health.status == "ok"
    assert health.model_version == "baseline-camsbias-v0"


def test_health_down_without_any_data(store):
    assert service.health(store, STATIONS, NOW).status == "down"
