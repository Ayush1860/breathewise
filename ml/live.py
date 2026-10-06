"""Live inference: store observations + live Open-Meteo data -> LightGBM forecast document.

Live mapping matches training (docs/sources.md):
- wx_* at hours <= t from the forecast API's recent hours (best-match analysis);
- fc_* at t+h from the live forecast valid at t+h (training used day-ahead runs);
- CAMS at t only (later hours are NaN, as in training).
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

import numpy as np

from backend.naqi import hourly_pm_index
from backend.schemas import (
    DriverGroup,
    ForecastHour,
    ForecastResponse,
    IndexQuantiles,
    Message,
    Pollutant,
    Quantiles,
    band_for_index,
)
from backend.store import Observation
from backend.text import message
from ingest.openmeteo import CamsHour, WeatherHour
from ml.features import HISTORY_HOURS, StationSeries, impute_short_gaps, wind_uv
from ml.model import ForecastModel

HORIZON = 12


def _hours(issued_at: datetime) -> list[datetime]:
    first = issued_at - timedelta(hours=HISTORY_HOURS - 1)
    return [first + timedelta(hours=i) for i in range(HISTORY_HOURS + HORIZON)]


def build_series(
    station_code: int,
    issued_at: datetime,
    observations: Sequence[Observation],
    weather: Sequence[WeatherHour],
    cams: Sequence[CamsHour],
) -> tuple[StationSeries, int]:
    hours = _hours(issued_at)
    t = HISTORY_HOURS - 1
    obs = {o.time: o.values for o in observations}
    wx = {w.time: w for w in weather}
    cm = {c.time: c for c in cams if c.time <= issued_at}

    def pm(p: Pollutant) -> np.ndarray:
        raw = [obs.get(h, {}).get(p) for h in hours]
        arr = np.array([np.nan if v is None else v for v in raw], dtype=float)
        arr[t + 1 :] = np.nan  # never let a stray future reading in
        return impute_short_gaps(arr)

    def field(name: str, before_issue_only: bool) -> np.ndarray:
        values = []
        for i, h in enumerate(hours):
            w = wx.get(h)
            value = getattr(w, name) if w else None
            values.append(np.nan if value is None or (before_issue_only and i > t) else value)
        return np.array(values, dtype=float)

    speed, direction = field("wind_speed_ms", False), field("wind_dir_deg", False)
    u, v = wind_uv(speed, direction)
    past = np.arange(len(hours)) <= t
    weather_t = {
        "u": np.where(past, u, np.nan),
        "v": np.where(past, v, np.nan),
        "blh": field("blh_m", True),
        "temp": field("temperature_c", True),
        "rh": field("rh_pct", True),
        "precip": field("precip_mm", True),
        "pressure": field("pressure_hpa", True),
    }
    weather_fc = {
        "u": u,
        "v": v,
        "temp": field("temperature_c", False),
        "rh": field("rh_pct", False),
        "precip": field("precip_mm", False),
    }
    series = StationSeries(
        station_code=station_code,
        time=np.array([np.datetime64(h.replace(tzinfo=None), "h") for h in hours]),
        pm25=pm(Pollutant.PM25),
        pm10=pm(Pollutant.PM10),
        weather=weather_t,
        weather_forecast=weather_fc,
        cams_pm25=np.array([cm[h].pm25 if h in cm else np.nan for h in hours], dtype=float),
        cams_pm10=np.array([cm[h].pm10 if h in cm else np.nan for h in hours], dtype=float),
    )
    return series, t


def _explanation_key(delta: float, drivers: dict[str, float]) -> str:
    direction = "rising" if delta > 0 else "falling"
    aligned = {g: v for g, v in drivers.items() if (v > 0) == (delta > 0)}
    main = max(aligned or drivers, key=lambda g: abs(drivers[g]))
    return f"explain.{direction}.{main}"


def hours_from_model(
    model: ForecastModel, series: StationSeries, t: int, issued_at: datetime
) -> tuple[list[ForecastHour], Message]:
    """12 forecast hours (bands, drivers, explanations) and the summary message."""
    predictions = model.predict(series, t)
    current = series.pm25[t]
    hours = []
    for h in range(1, HORIZON + 1):
        (a10, a50, a90), (b10, b50, b90) = predictions[h]["pm25"], predictions[h]["pm10"]
        index = IndexQuantiles(
            q10=hourly_pm_index(a10, b10),
            q50=hourly_pm_index(a50, b50),
            q90=hourly_pm_index(a90, b90),
        )
        groups, _ = model.drivers(series, t, h)
        delta = a50 - current if not np.isnan(current) else 0.0
        hours.append(
            ForecastHour(
                target_time=issued_at + timedelta(hours=h),
                horizon_h=h,
                pm25=Quantiles(q10=a10, q50=a50, q90=a90),
                pm10=Quantiles(q10=b10, q50=b50, q90=b90),
                index=index,
                band=band_for_index(index.q50),
                drivers={DriverGroup(g): round(v, 1) for g, v in groups.items()},
                explanation=message(_explanation_key(delta, groups), pollutant="PM2.5"),
            )
        )
    reference = current if not np.isnan(current) else 0.0
    peak = max(hours, key=lambda x: abs(x.pm25.q50 - reference))
    return hours, peak.explanation


def model_forecast(
    model: ForecastModel,
    station_id: str,
    station_code: int,
    issued_at: datetime,
    observations: Sequence[Observation],
    weather: Sequence[WeatherHour],
    cams: Sequence[CamsHour],
) -> ForecastResponse:
    series, t = build_series(station_code, issued_at, observations, weather, cams)
    if np.isnan(series.weather_forecast["u"][t + HORIZON]):
        raise ValueError("live weather forecast does not reach t+12")
    hours, summary = hours_from_model(model, series, t, issued_at)
    return ForecastResponse(
        generated_at=issued_at,
        station_id=station_id,
        issued_at=issued_at,
        model_version=model.model_version,
        stale=False,
        age_minutes=0,
        summary=summary,
        hours=hours,
    )
