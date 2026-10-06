"""Feature engineering shared by training and the forecast Lambda (numpy only).

Row t holds the features available at issue time t for a target at t + horizon:
- recent build-up: target lags at t, t-1, t-2, t-5, t-11, t-23, the other PM at t, and
  rolling mean/std over the 3/6/24 hours ending at t;
- ventilation/weather: analysis at t (u, v, BLH, temperature, RH, precipitation,
  pressure) and the archived/live *forecast* valid at t + h (u, v, temperature, RH,
  precipitation). BLH has no archived forecast, so it is used at t only (docs/sources.md);
- regional pollution: CAMS PM2.5/PM10 at t only (no archived CAMS forecasts);
- time: hour/day-of-week of the target hour (cyclical), month, festival flag.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

LAGS = (0, 1, 2, 5, 11, 23)
ROLL_WINDOWS = (3, 6, 24)
WEATHER_AT_ISSUE = ("u", "v", "blh", "temp", "rh", "precip", "pressure")
WEATHER_AT_TARGET = ("u", "v", "temp", "rh", "precip")
HISTORY_HOURS = max(LAGS) + 1

# Diwali, Dussehra and New Year (+-2 days), when firecrackers and festivities shift emissions.
_FESTIVALS = (
    date(2024, 1, 1), date(2024, 10, 12), date(2024, 10, 31), date(2025, 1, 1),
    date(2025, 10, 2), date(2025, 10, 20), date(2026, 1, 1), date(2026, 10, 20),
    date(2026, 11, 8), date(2027, 1, 1),
)  # fmt: skip
FESTIVAL_DAYS = {d + timedelta(days=k) for d in _FESTIVALS for k in range(-2, 3)}


@dataclass
class StationSeries:
    """Aligned hourly arrays for one station (index i = hour time[i], UTC)."""

    station_code: int
    time: np.ndarray  # datetime64[h]
    pm25: np.ndarray
    pm10: np.ndarray
    weather: dict[str, np.ndarray]  # analysis valid at time[i]
    weather_forecast: dict[str, np.ndarray]  # forecast valid at time[i], issued >= 24 h earlier
    cams_pm25: np.ndarray
    cams_pm10: np.ndarray


def _other(pollutant: str) -> str:
    return "pm10" if pollutant == "pm25" else "pm25"


def feature_names(pollutant: str) -> list[str]:
    return [
        "station",
        *(f"lag{k}" for k in LAGS),
        "other_lag0",
        *(f"roll_mean_{w}" for w in ROLL_WINDOWS),
        *(f"roll_std_{w}" for w in ROLL_WINDOWS),
        *(f"wx_{k}" for k in WEATHER_AT_ISSUE),
        *(f"fc_{k}" for k in WEATHER_AT_TARGET),
        "cams_pm25_t",
        "cams_pm10_t",
        "hour_sin",
        "hour_cos",
        "dow_sin",
        "dow_cos",
        "month",
        "festival",
    ]


FEATURE_GROUPS: dict[str, list[str]] = {
    "recent_buildup": [
        *(f"lag{k}" for k in LAGS),
        "other_lag0",
        *(f"roll_mean_{w}" for w in ROLL_WINDOWS),
        *(f"roll_std_{w}" for w in ROLL_WINDOWS),
    ],
    "ventilation": [
        *(f"wx_{k}" for k in WEATHER_AT_ISSUE),
        *(f"fc_{k}" for k in WEATHER_AT_TARGET),
    ],
    "regional_pollution": ["cams_pm25_t", "cams_pm10_t"],
    "time_of_day": ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "month", "festival"],
}


def wind_uv(speed: np.ndarray, direction_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Meteorological direction (where the wind comes FROM) -> u (east), v (north)."""
    rad = np.deg2rad(direction_deg)
    return -speed * np.sin(rad), -speed * np.cos(rad)


def impute_short_gaps(x: np.ndarray, max_gap: int = 3) -> np.ndarray:
    """Linearly interpolate interior NaN runs of at most max_gap hours; leave longer gaps."""
    out = np.asarray(x, dtype=float).copy()
    isnan = np.isnan(out)
    i, n = 0, len(out)
    while i < n:
        if not isnan[i]:
            i += 1
            continue
        j = i
        while j < n and isnan[j]:
            j += 1
        if 0 < i and j < n and j - i <= max_gap:
            out[i:j] = np.interp(np.arange(i, j), [i - 1, j], [out[i - 1], out[j]])
        i = j
    return out


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    """out[t] = x[t - k] (k > 0 looks back, k < 0 looks ahead); NaN outside the range."""
    out = np.full(len(x), np.nan)
    if k >= 0:
        out[k:] = x[: len(x) - k]
    else:
        out[:k] = x[-k:]
    return out


def _rolling(x: np.ndarray, w: int) -> tuple[np.ndarray, np.ndarray]:
    """NaN-aware mean/std over the w hours ending at t (inclusive)."""
    valid = ~np.isnan(x)
    values = np.where(valid, x, 0.0)
    pad = np.zeros(1)
    csum = np.concatenate([pad, np.cumsum(values)])
    csq = np.concatenate([pad, np.cumsum(values**2)])
    ccount = np.concatenate([pad, np.cumsum(valid)])
    idx = np.arange(len(x))
    lo = np.maximum(idx - w + 1, 0)
    count = ccount[idx + 1] - ccount[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = (csum[idx + 1] - csum[lo]) / count
        var = (csq[idx + 1] - csq[lo]) / count - mean**2
    mean[count == 0] = np.nan
    std = np.sqrt(np.clip(var, 0, None))
    std[count == 0] = np.nan
    return mean, std


def feature_matrix(s: StationSeries, horizon: int, pollutant: str) -> np.ndarray:
    """Features for every issue hour t (rows) for a target at t + horizon."""
    y = np.asarray(getattr(s, pollutant), dtype=float)
    other = np.asarray(getattr(s, _other(pollutant)), dtype=float)
    n = len(y)
    columns = [np.full(n, float(s.station_code))]
    columns += [_shift(y, k) for k in LAGS]
    columns.append(other)
    rolls = [_rolling(y, w) for w in ROLL_WINDOWS]
    columns += [mean for mean, _ in rolls] + [std for _, std in rolls]
    columns += [np.asarray(s.weather[k], dtype=float) for k in WEATHER_AT_ISSUE]
    columns += [
        _shift(np.asarray(s.weather_forecast[k], float), -horizon) for k in WEATHER_AT_TARGET
    ]
    columns += [np.asarray(s.cams_pm25, float), np.asarray(s.cams_pm10, float)]
    target = s.time.astype("datetime64[h]") + np.timedelta64(horizon, "h")
    hour = (target.astype("int64") % 24).astype(float)
    days = target.astype("datetime64[D]")
    dow = ((days.astype("int64") + 3) % 7).astype(float)  # 1970-01-01 was a Thursday
    month = (days.astype("datetime64[M]").astype("int64") % 12 + 1).astype(float)
    festival = np.array([d.item() in FESTIVAL_DAYS for d in days], dtype=float)
    columns += [
        np.sin(2 * np.pi * hour / 24),
        np.cos(2 * np.pi * hour / 24),
        np.sin(2 * np.pi * dow / 7),
        np.cos(2 * np.pi * dow / 7),
        month,
        festival,
    ]
    return np.column_stack(columns)


def issue_features(s: StationSeries, t: int, horizon: int, pollutant: str) -> np.ndarray:
    return feature_matrix(s, horizon, pollutant)[t]


def training_rows(
    s: StationSeries, horizon: int, pollutant: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(X, y, issue_times) for every issue hour with a full lag history and an observed target."""
    X = feature_matrix(s, horizon, pollutant)
    y = _shift(np.asarray(getattr(s, pollutant), dtype=float), -horizon)
    rows = np.arange(len(y))
    keep = (rows >= HISTORY_HOURS - 1) & ~np.isnan(y)
    return X[keep], y[keep], s.time[keep]
