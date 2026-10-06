"""Read-side logic for the live API: station resolution, current AQI, freshness."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from backend.naqi import UNITS, averaged, hourly_pm_index, overall, sub_index
from backend.schemas import (
    CurrentAqiResponse,
    ForecastResponse,
    HealthResponse,
    HorizonScore,
    Pollutant,
    ScoreboardPoint,
    ScoreboardResponse,
    Station,
    StationHealth,
    SubIndex,
    band_for_index,
)
from backend.store import Store
from ingest.stations import StationConfig

OBS_STALE_AFTER = timedelta(hours=3)
FORECAST_STALE_AFTER = timedelta(hours=2)
HOUR = timedelta(hours=1)


class NotFound(Exception):
    """Unknown station id."""


def resolve_station(
    stations: Sequence[StationConfig], station_id: str | None, lat: float | None, lon: float | None
) -> StationConfig:
    if station_id is not None:
        for station in stations:
            if station.station_id == station_id:
                return station
        raise NotFound(f"unknown station_id {station_id!r}")
    if lat is not None and lon is not None:
        return min(stations, key=lambda s: s.distance_to(lat, lon))
    return next(s for s in stations if s.is_venue_default)


def station_view(station: StationConfig, user_location: tuple[float, float] | None) -> Station:
    distance = round(station.distance_to(*user_location), 1) if user_location else None
    return Station(
        station_id=station.station_id,
        name=station.name,
        lat=station.lat,
        lon=station.lon,
        distance_km=distance,
        is_venue_default=station.is_venue_default,
    )


def age_minutes(now: datetime, then: datetime) -> int:
    return max(int((now - then).total_seconds() // 60), 0)


def current_aqi(
    store: Store,
    station: StationConfig,
    now: datetime,
    user_location: tuple[float, float] | None,
) -> CurrentAqiResponse | None:
    latest = store.latest(station.station_id)
    if latest is None:
        return None
    first = latest.time - 23 * HOUR
    by_time = {o.time: o for o in store.observations(station.station_id, since=first)}
    hours = [first + i * HOUR for i in range(24)]
    sub_indices: dict[Pollutant, int] = {}
    concentrations: dict[Pollutant, float] = {}
    for pollutant in Pollutant:
        series = [by_time[t].values.get(pollutant) if t in by_time else None for t in hours]
        value = averaged(pollutant, series)
        if value is not None:
            concentrations[pollutant] = round(value, 2)
            sub_indices[pollutant] = sub_index(pollutant, value)
    hourly = hourly_pm_index(latest.values.get(Pollutant.PM25), latest.values.get(Pollutant.PM10))
    observed_at = latest.time + HOUR  # readings are hourly means ending at this time
    age = age_minutes(now, observed_at)
    return CurrentAqiResponse(
        generated_at=now,
        station=station_view(station, user_location),
        observed_at=observed_at,
        source=latest.source,
        stale=now - observed_at > OBS_STALE_AFTER,
        age_minutes=age,
        aqi=overall(sub_indices),
        hourly_index=hourly,
        hourly_band=band_for_index(hourly) if hourly is not None else None,
        sub_indices=[
            SubIndex(
                pollutant=p,
                concentration=concentrations[p],
                unit=UNITS[p],
                sub_index=sub_indices[p],
            )
            for p in sub_indices
        ],
    )


def forecast_view(store: Store, station: StationConfig, now: datetime) -> ForecastResponse | None:
    doc = store.current_forecast(station.station_id)
    if doc is None:
        return None
    return doc.model_copy(
        update={
            "generated_at": now,
            "stale": now - doc.issued_at > FORECAST_STALE_AFTER,
            "age_minutes": age_minutes(now, doc.issued_at),
        }
    )


SCOREBOARD_WINDOW = timedelta(days=7)
SCOREBOARD_POINTS_WINDOW = timedelta(hours=48)


def scoreboard(
    store: Store,
    station: StationConfig,
    model_version: str | None,
    pollutant: Literal["pm25", "pm10"],
    now: datetime,
) -> ScoreboardResponse:
    if model_version is None:
        current = store.current_forecast(station.station_id)
        model_version = current.model_version if current else "none"
    since = now - SCOREBOARD_WINDOW
    entries = [
        e
        for e in store.forecast_log(station.station_id, model_version, since)
        if e.hour.target_time <= now
    ]
    actuals = {
        o.time: o.values.get(Pollutant(pollutant))
        for o in store.observations(station.station_id, since=since)
    }
    points = [
        ScoreboardPoint(
            target_time=e.hour.target_time,
            issued_at=e.issued_at,
            horizon_h=e.horizon_h,
            predicted=getattr(e.hour, pollutant),
            actual=actuals.get(e.hour.target_time),
        )
        for e in entries
    ]
    per_horizon = []
    for h in range(1, 13):
        errors = [
            abs(p.predicted.q50 - p.actual)
            for p in points
            if p.horizon_h == h and p.actual is not None
        ]
        mae = round(sum(errors) / len(errors), 1) if errors else None
        per_horizon.append(HorizonScore(horizon_h=h, mae=mae, n=len(errors)))
    recent = [p for p in points if p.target_time > now - SCOREBOARD_POINTS_WINDOW]
    return ScoreboardResponse(
        generated_at=now,
        station_id=station.station_id,
        model_version=model_version,
        pollutant=pollutant,
        since=min((e.issued_at for e in entries), default=since),
        points=recent,
        per_horizon=per_horizon,
    )


REFRESH_INTERVAL = timedelta(minutes=5)


def try_refresh(store: Store, now: datetime) -> int | None:
    """None if this caller may refresh now; else seconds to wait (global 5-min limit)."""
    return store.acquire_lock("refresh", REFRESH_INTERVAL, now)


def health(store: Store, stations: Sequence[StationConfig], now: datetime) -> HealthResponse:
    station_health = []
    fresh_obs = False
    for station in stations:
        latest = store.latest(station.station_id)
        observed_at = latest.time + HOUR if latest else None
        fresh_obs |= observed_at is not None and now - observed_at <= OBS_STALE_AFTER
        station_health.append(
            StationHealth(
                station_id=station.station_id,
                last_observation_at=observed_at,
                last_source=latest.source if latest else None,
            )
        )
    venue = next(s for s in stations if s.is_venue_default)
    forecast = store.current_forecast(venue.station_id)
    fresh_forecast = forecast is not None and now - forecast.issued_at <= FORECAST_STALE_AFTER
    any_data = forecast is not None or any(s.last_observation_at for s in station_health)
    status = "ok" if fresh_obs and fresh_forecast else ("degraded" if any_data else "down")
    return HealthResponse(
        generated_at=now,
        status=status,
        model_version=forecast.model_version if forecast else None,
        last_forecast_at=forecast.issued_at if forecast else None,
        sources=store.health(),
        stations=station_health,
    )
