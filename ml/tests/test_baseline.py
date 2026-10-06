from datetime import UTC, datetime, timedelta

import pytest

from backend.schemas import DriverGroup, Pollutant, Source
from backend.store import Observation
from ingest.openmeteo import CamsHour
from ml.baseline import MODEL_VERSION, baseline_forecast

T = datetime(2026, 10, 6, 8, 0, tzinfo=UTC)
P = Pollutant


def cams(hours_back=96, hours_ahead=12, pm25=100.0, pm10=170.0):
    return [
        CamsHour(T + timedelta(hours=h), pm25, pm10, None, None, None, None)
        for h in range(-hours_back, hours_ahead + 1)
    ]


def observations(offset=0.0, hours=72, start_back=72):
    return [
        Observation(
            "s",
            T - timedelta(hours=h),
            Source.CPCB,
            {P.PM25: 100.0 + offset, P.PM10: 170.0 + offset},
        )
        for h in range(start_back - hours, start_back)
    ]


def test_without_observations_q50_is_raw_cams_with_minimum_spread():
    fc = baseline_forecast("s", T, [], cams())
    assert fc.model_version == MODEL_VERSION
    assert [h.horizon_h for h in fc.hours] == list(range(1, 13))
    assert fc.hours[0].target_time == T + timedelta(hours=1)
    h1 = fc.hours[0].pm25
    assert h1.q50 == 100.0
    assert h1.q10 <= 85.0 and h1.q90 >= 115.0


def test_constant_station_bias_is_added():
    fc = baseline_forecast("s", T, observations(offset=20.0), cams())
    assert fc.hours[0].pm25.q50 == pytest.approx(120.0)
    assert fc.hours[0].pm10.q50 == pytest.approx(190.0)


def test_bias_ignores_residuals_older_than_72h():
    old = observations(offset=500.0, hours=24, start_back=96)  # 72-96 h ago
    fc = baseline_forecast("s", T, old, cams())
    assert fc.hours[0].pm25.q50 == pytest.approx(100.0)


def test_quantiles_stay_ordered_and_non_negative_with_large_negative_bias():
    fc = baseline_forecast("s", T, observations(offset=-300.0), cams())
    for hour in fc.hours:
        assert 0 <= hour.pm25.q10 <= hour.pm25.q50 <= hour.pm25.q90


def test_missing_future_cams_hour_raises():
    with pytest.raises(ValueError, match="CAMS"):
        baseline_forecast("s", T, [], cams(hours_ahead=11))


def test_drivers_and_explanation_reflect_direction():
    rising = cams(pm25=100.0)
    rising = [
        c if c.time <= T else CamsHour(c.time, 150.0, c.pm10, None, None, None, None)
        for c in rising
    ]
    fc = baseline_forecast("s", T, observations(), rising)
    hour = fc.hours[0]
    assert hour.drivers[DriverGroup.REGIONAL_POLLUTION] == pytest.approx(50.0)
    assert hour.explanation.key == "explain.rising.regional_pollution"
    assert fc.summary.key == "explain.rising.regional_pollution"


def test_band_matches_index():
    fc = baseline_forecast("s", T, [], cams(pm25=185.0, pm10=300.0))
    assert fc.hours[0].band.value == "very_poor"
