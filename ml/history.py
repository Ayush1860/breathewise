"""Pull training history from Open-Meteo (no key) into data/openmeteo/<station>.parquet.

Per hour t:
- wx_*  analysis at t (Historical Forecast API: stitched short-lead forecasts),
- fc_*  forecast valid at t issued >= 24 h earlier (Previous Runs API `*_previous_day1`);
        used as the "forecast at t+h" feature, so it never leaks information after issue,
- cams_* CAMS PM at t (used at issue time only).

    uv run python -m ml.history --start 2024-02-01 --end 2026-10-05
"""

import argparse
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ingest.http import get_json
from ingest.stations import load_stations
from ml.features import wind_uv

HIST_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

ANALYSIS_VARS = (
    "wind_speed_10m",
    "wind_direction_10m",
    "boundary_layer_height",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "surface_pressure",
)
FORECAST_VARS = tuple(
    f"{v}_previous_day1"
    for v in (
        "wind_speed_10m",
        "wind_direction_10m",
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
    )
)
CAMS_VARS = ("pm2_5", "pm10")
OUT_DIR = Path("data/openmeteo")


def chunks(start: str, end: str, days: int = 90) -> Iterator[tuple[str, str]]:
    cursor, stop = date.fromisoformat(start), date.fromisoformat(end)
    while cursor <= stop:
        upper = min(cursor + timedelta(days=days - 1), stop)
        yield cursor.isoformat(), upper.isoformat()
        cursor = upper + timedelta(days=1)


def _frame(payload: dict, variables: tuple[str, ...]) -> pd.DataFrame:
    hourly = payload["hourly"]
    df = pd.DataFrame({v: pd.to_numeric(pd.Series(hourly[v]), errors="coerce") for v in variables})
    df.index = pd.to_datetime(hourly["time"]).tz_localize("UTC")
    return df


def merge_openmeteo(analysis: dict, forecast: dict, cams: dict) -> pd.DataFrame:
    a = _frame(analysis, ANALYSIS_VARS)
    f = _frame(forecast, FORECAST_VARS)
    c = _frame(cams, CAMS_VARS)
    out = pd.DataFrame(index=a.index.union(f.index).union(c.index))
    a, f, c = a.reindex(out.index), f.reindex(out.index), c.reindex(out.index)
    out["wx_u"], out["wx_v"] = wind_uv(
        a["wind_speed_10m"].to_numpy(), a["wind_direction_10m"].to_numpy()
    )
    out["wx_blh"] = a["boundary_layer_height"]
    out["wx_temp"] = a["temperature_2m"]
    out["wx_rh"] = a["relative_humidity_2m"]
    out["wx_precip"] = a["precipitation"]
    out["wx_pressure"] = a["surface_pressure"]
    out["fc_u"], out["fc_v"] = wind_uv(
        f["wind_speed_10m_previous_day1"].to_numpy(),
        f["wind_direction_10m_previous_day1"].to_numpy(),
    )
    out["fc_temp"] = f["temperature_2m_previous_day1"]
    out["fc_rh"] = f["relative_humidity_2m_previous_day1"]
    out["fc_precip"] = f["precipitation_previous_day1"]
    out["cams_pm25"], out["cams_pm10"] = c["pm2_5"], c["pm10"]
    out = out.astype(float).replace([np.inf, -np.inf], np.nan)
    return out.rename_axis("time").reset_index()


def _request(url: str, lat: float, lon: float, variables, start: str, end: str) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(variables),
        "start_date": start,
        "end_date": end,
        "timezone": "UTC",
    }
    if "air-quality" not in url:
        params["wind_speed_unit"] = "ms"
    return get_json(url, params, timeout=60.0)


def pull_station(lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    frames = []
    for lo, hi in chunks(start, end):
        frames.append(
            merge_openmeteo(
                _request(HIST_FORECAST_URL, lat, lon, ANALYSIS_VARS, lo, hi),
                _request(PREVIOUS_RUNS_URL, lat, lon, FORECAST_VARS, lo, hi),
                _request(AIR_QUALITY_URL, lat, lon, CAMS_VARS, lo, hi),
            )
        )
    return pd.concat(frames, ignore_index=True).drop_duplicates("time").sort_values("time")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-02-01")
    parser.add_argument("--end", default="2026-10-05")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for station in load_stations():
        df = pull_station(station.lat, station.lon, args.start, args.end)
        path = OUT_DIR / f"{station.station_id}.parquet"
        df.to_parquet(path, index=False)
        coverage = df.drop(columns="time").notna().mean().round(3).to_dict()
        print(f"{station.station_id}: {len(df)} rows -> {path}; coverage {coverage}")


if __name__ == "__main__":
    main()
