"""Hourly forecast run: per station, build the forecast and store it + the forecast log.

Uses the LightGBM model when one is deployed; any failure on that path (missing live
inputs, model error) falls back to the CAMS-bias baseline for that station, and if even
that fails the previous forecast is kept (served as stale by the API).
"""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from backend.schemas import ForecastResponse
from backend.store import Store
from ingest.openmeteo import CamsHour, WeatherHour, fetch_cams, fetch_weather
from ingest.run import floor_hour
from ingest.stations import StationConfig
from ml.baseline import BIAS_WINDOW, baseline_forecast
from ml.live import model_forecast

log = logging.getLogger(__name__)


def _default_cams(lat: float, lon: float) -> list[CamsHour]:
    return fetch_cams(lat, lon, past_days=4, forecast_days=2)


def _default_weather(lat: float, lon: float) -> list[WeatherHour]:
    return fetch_weather(lat, lon, past_days=2, forecast_days=2)


def _forecast_station(
    station: StationConfig,
    issued_at: datetime,
    store: Store,
    cams_for: Callable[[float, float], list[CamsHour]],
    weather_for: Callable[[float, float], list[WeatherHour]],
    model,
) -> ForecastResponse:
    since = issued_at - BIAS_WINDOW - timedelta(hours=1)
    observations = store.observations(station.station_id, since=since)
    cams = cams_for(station.lat, station.lon)
    if model is not None and station.station_id in model.station_codes:
        try:
            return model_forecast(
                model,
                station.station_id,
                model.station_codes[station.station_id],
                issued_at,
                observations,
                weather_for(station.lat, station.lon),
                cams,
            )
        except Exception:
            log.exception("model forecast failed for %s; using baseline", station.station_id)
    return baseline_forecast(station.station_id, issued_at, observations, cams)


def run_forecast(
    now: datetime,
    stations: Sequence[StationConfig],
    store: Store,
    cams_for: Callable[[float, float], list[CamsHour]] = _default_cams,
    weather_for: Callable[[float, float], list[WeatherHour]] = _default_weather,
    model=None,
) -> dict[str, str | None]:
    issued_at = floor_hour(now)
    summary: dict[str, str | None] = {}
    for station in stations:
        try:
            doc = _forecast_station(station, issued_at, store, cams_for, weather_for, model)
            store.put_forecast(doc)
            summary[station.station_id] = doc.model_version
        except Exception:  # keep the previous forecast; the API serves it as stale
            log.exception("forecast failed for %s", station.station_id)
            summary[station.station_id] = None
    return summary
