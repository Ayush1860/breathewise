from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from backend.schemas import DriverGroup, Pollutant, Source
from backend.store import Observation
from ingest.openmeteo import CamsHour, WeatherHour
from ml.live import build_series, model_forecast
from ml.model import train
from ml.tests.test_model import synthetic

ISSUED = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def weather(hours_back=48, hours_ahead=13):
    return [
        WeatherHour(ISSUED + timedelta(hours=h), 25.0, 50.0, 3.0, 270.0, 400.0, 0.0, 990.0)
        for h in range(-hours_back, hours_ahead)
    ]


def cams(hours_back=48, hours_ahead=13):
    return [
        CamsHour(ISSUED + timedelta(hours=h), 120.0, 200.0, None, None, None, None)
        for h in range(-hours_back, hours_ahead)
    ]


def observations(hours=30):
    return [
        Observation(
            "dl-rohini",
            ISSUED - timedelta(hours=h),
            Source.CPCB,
            {Pollutant.PM25: 150.0 + h, Pollutant.PM10: 250.0},
        )
        for h in range(hours)
    ]


@pytest.fixture(scope="module")
def model():
    return train([synthetic()], horizons=tuple(range(1, 13)), model_version="lgbm-test", rounds=40)


def test_build_series_aligns_hours_and_issue_index():
    s, t = build_series(0, ISSUED, observations(), weather(), cams())
    assert s.time[t] == np.datetime64("2026-10-06T09", "h")
    assert s.pm25[t] == 150.0 and s.pm25[t - 5] == 155.0
    assert s.weather["u"][t] == pytest.approx(3.0)  # wind from west blows east
    assert s.weather_forecast["u"][t + 12] == pytest.approx(3.0)
    assert np.isnan(s.cams_pm25[t + 1])  # CAMS used at issue time only


def test_model_forecast_contract(model):
    doc = model_forecast(model, "dl-rohini", 0, ISSUED, observations(), weather(), cams())
    assert doc.model_version == "lgbm-test"
    assert [h.horizon_h for h in doc.hours] == list(range(1, 13))
    hour = doc.hours[0]
    assert set(hour.drivers) == {
        DriverGroup.VENTILATION,
        DriverGroup.RECENT_BUILDUP,
        DriverGroup.REGIONAL_POLLUTION,
        DriverGroup.TIME_OF_DAY,
    }
    assert hour.explanation.key.startswith(("explain.rising.", "explain.falling."))
    assert hour.pm25.q10 <= hour.pm25.q50 <= hour.pm25.q90


def test_model_forecast_needs_future_weather(model):
    with pytest.raises(ValueError, match="weather"):
        model_forecast(
            model, "dl-rohini", 0, ISSUED, observations(), weather(hours_ahead=6), cams()
        )
