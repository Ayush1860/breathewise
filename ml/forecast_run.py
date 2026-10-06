"""Hourly forecast run: per station, build the forecast and store it + the forecast log."""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from backend.store import Store
from ingest.openmeteo import CamsHour, fetch_cams
from ingest.run import floor_hour
from ingest.stations import StationConfig
from ml.baseline import BIAS_WINDOW, baseline_forecast

log = logging.getLogger(__name__)


def _default_cams(lat: float, lon: float) -> list[CamsHour]:
    return fetch_cams(lat, lon, past_days=4, forecast_days=2)


def run_forecast(
    now: datetime,
    stations: Sequence[StationConfig],
    store: Store,
    cams_for: Callable[[float, float], list[CamsHour]] = _default_cams,
) -> dict[str, str | None]:
    issued_at = floor_hour(now)
    summary: dict[str, str | None] = {}
    for station in stations:
        try:
            observations = store.observations(
                station.station_id, since=issued_at - BIAS_WINDOW - timedelta(hours=1)
            )
            doc = baseline_forecast(
                station.station_id, issued_at, observations, cams_for(station.lat, station.lon)
            )
            store.put_forecast(doc)
            summary[station.station_id] = doc.model_version
        except Exception:  # keep the previous forecast; the API serves it as stale
            log.exception("forecast failed for %s", station.station_id)
            summary[station.station_id] = None
    return summary
