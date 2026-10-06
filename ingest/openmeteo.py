"""Open-Meteo clients: weather forecast and CAMS air quality (no API key).

All requests use timezone=UTC; responses are validated and normalised to SI-ish units:
wind in m/s, CO in mg/m3 (CAMS reports ug/m3; NAQI uses mg/m3).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ingest.http import SourceError, get_json

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

WEATHER_VARS = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "boundary_layer_height",
    "precipitation",
    "surface_pressure",
)
CAMS_VARS = (
    "pm2_5",
    "pm10",
    "nitrogen_dioxide",
    "ozone",
    "carbon_monoxide",
    "sulphur_dioxide",
)

Getter = Callable[[str, Mapping[str, Any]], Any]


@dataclass(frozen=True)
class WeatherHour:
    time: datetime
    temperature_c: float | None
    rh_pct: float | None
    wind_speed_ms: float | None
    wind_dir_deg: float | None
    blh_m: float | None
    precip_mm: float | None
    pressure_hpa: float | None


@dataclass(frozen=True)
class CamsHour:
    time: datetime
    pm25: float | None
    pm10: float | None
    no2: float | None
    o3: float | None
    co_mg_m3: float | None
    so2: float | None


_WIND_TO_MS = {"km/h": 1 / 3.6, "m/s": 1.0}
_CO_TO_MG = {"μg/m³": 1 / 1000, "mg/m³": 1.0}


def _columns(payload: Mapping[str, Any], variables: tuple[str, ...]) -> dict[str, list]:
    if payload.get("utc_offset_seconds") != 0:
        raise SourceError("Open-Meteo response is not in UTC")
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict) or "time" not in hourly:
        raise SourceError("Open-Meteo response has no hourly block")
    missing = [v for v in variables if v not in hourly]
    if missing:
        raise SourceError(f"Open-Meteo response missing variables: {missing}")
    n = len(hourly["time"])
    if any(len(hourly[v]) != n for v in variables):
        raise SourceError("Open-Meteo hourly arrays have mismatched length")
    return hourly


def _scale(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _factor(payload: Mapping[str, Any], variable: str, table: dict[str, float]) -> float:
    unit = payload.get("hourly_units", {}).get(variable)
    if unit not in table:
        raise SourceError(f"unexpected unit {unit!r} for {variable}")
    return table[unit]


def _utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).replace(tzinfo=UTC)


def parse_weather(payload: Mapping[str, Any]) -> list[WeatherHour]:
    h = _columns(payload, WEATHER_VARS)
    wind = _factor(payload, "wind_speed_10m", _WIND_TO_MS)
    return [
        WeatherHour(
            time=_utc(t),
            temperature_c=h["temperature_2m"][i],
            rh_pct=h["relative_humidity_2m"][i],
            wind_speed_ms=_scale(h["wind_speed_10m"][i], wind),
            wind_dir_deg=h["wind_direction_10m"][i],
            blh_m=h["boundary_layer_height"][i],
            precip_mm=h["precipitation"][i],
            pressure_hpa=h["surface_pressure"][i],
        )
        for i, t in enumerate(h["time"])
    ]


def parse_cams(payload: Mapping[str, Any]) -> list[CamsHour]:
    h = _columns(payload, CAMS_VARS)
    co = _factor(payload, "carbon_monoxide", _CO_TO_MG)
    return [
        CamsHour(
            time=_utc(t),
            pm25=h["pm2_5"][i],
            pm10=h["pm10"][i],
            no2=h["nitrogen_dioxide"][i],
            o3=h["ozone"][i],
            co_mg_m3=_scale(h["carbon_monoxide"][i], co),
            so2=h["sulphur_dioxide"][i],
        )
        for i, t in enumerate(h["time"])
    ]


def request_params(
    lat: float, lon: float, variables: tuple[str, ...], past: int, ahead: int
) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(variables),
        "past_days": past,
        "forecast_days": ahead,
        "timezone": "UTC",
    }


def fetch_weather(
    lat: float, lon: float, *, past_days: int = 1, forecast_days: int = 1, get: Getter = get_json
) -> list[WeatherHour]:
    return parse_weather(
        get(WEATHER_URL, request_params(lat, lon, WEATHER_VARS, past_days, forecast_days))
    )


def fetch_cams(
    lat: float, lon: float, *, past_days: int = 1, forecast_days: int = 1, get: Getter = get_json
) -> list[CamsHour]:
    return parse_cams(
        get(AIR_QUALITY_URL, request_params(lat, lon, CAMS_VARS, past_days, forecast_days))
    )
