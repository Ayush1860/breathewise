"""Day-1 baseline forecast: CAMS at t+h plus a rolling station bias (model baseline-camsbias-v0).

bias = median(observed - CAMS) over the last 72 h; the 10th/90th percentile residuals set
the band, never narrower than +-15 % of the median forecast.
"""

import statistics
from collections.abc import Sequence
from datetime import datetime, timedelta

from backend.naqi import hourly_pm_index
from backend.schemas import (
    DriverGroup,
    ForecastHour,
    ForecastResponse,
    IndexQuantiles,
    Pollutant,
    Quantiles,
    band_for_index,
)
from backend.store import Observation
from backend.text import message
from ingest.openmeteo import CamsHour

MODEL_VERSION = "baseline-camsbias-v0"
BIAS_WINDOW = timedelta(hours=72)
MIN_RESIDUALS = 12
MIN_SPREAD = 0.15
HORIZONS = range(1, 13)

_CAMS_FIELD = {Pollutant.PM25: "pm25", Pollutant.PM10: "pm10"}


def _residual_stats(
    pollutant: Pollutant, issued_at: datetime, obs: Sequence[Observation], cams: dict
) -> tuple[float, float, float]:
    """(bias, lower offset, upper offset) relative to the bias."""
    residuals = []
    for o in obs:
        model = cams.get(o.time)
        value = o.values.get(pollutant)
        model_value = getattr(model, _CAMS_FIELD[pollutant]) if model else None
        if issued_at - BIAS_WINDOW < o.time <= issued_at and None not in (value, model_value):
            residuals.append(value - model_value)
    if not residuals:
        return 0.0, 0.0, 0.0
    bias = statistics.median(residuals)
    if len(residuals) < MIN_RESIDUALS:
        return bias, 0.0, 0.0
    deciles = statistics.quantiles(residuals, n=10)
    return bias, deciles[0] - bias, deciles[-1] - bias


def _quantiles(q50_raw: float, lower: float, upper: float) -> Quantiles:
    q50 = max(q50_raw, 0.0)
    q10 = max(min(q50 + lower, q50 * (1 - MIN_SPREAD)), 0.0)
    q90 = max(q50 + upper, q50 * (1 + MIN_SPREAD))
    return Quantiles(q10=round(q10, 1), q50=round(q50, 1), q90=round(q90, 1))


def _current_pm25(issued_at: datetime, obs: Sequence[Observation], cams: dict) -> float:
    recent = [o for o in obs if o.time <= issued_at and o.values.get(Pollutant.PM25) is not None]
    if recent:
        return max(recent, key=lambda o: o.time).values[Pollutant.PM25]
    now = cams.get(issued_at)
    return now.pm25 if now and now.pm25 is not None else 0.0


def baseline_forecast(
    station_id: str,
    issued_at: datetime,
    observations: Sequence[Observation],
    cams_hours: Sequence[CamsHour],
) -> ForecastResponse:
    cams = {c.time: c for c in cams_hours}
    stats = {p: _residual_stats(p, issued_at, observations, cams) for p in _CAMS_FIELD}
    current = _current_pm25(issued_at, observations, cams)
    hours = []
    for h in HORIZONS:
        target = issued_at + timedelta(hours=h)
        future = cams.get(target)
        if future is None or future.pm25 is None or future.pm10 is None:
            raise ValueError(f"CAMS forecast missing for {target.isoformat()}")
        bands = {}
        for p, (bias, lower, upper) in stats.items():
            bands[p] = _quantiles(getattr(future, _CAMS_FIELD[p]) + bias, lower, upper)
        pm25, pm10 = bands[Pollutant.PM25], bands[Pollutant.PM10]
        index = IndexQuantiles(
            q10=hourly_pm_index(pm25.q10, pm10.q10),
            q50=hourly_pm_index(pm25.q50, pm10.q50),
            q90=hourly_pm_index(pm25.q90, pm10.q90),
        )
        delta = round(pm25.q50 - current, 1)
        direction = "rising" if delta > 0 else "falling"
        hours.append(
            ForecastHour(
                target_time=target,
                horizon_h=h,
                pm25=pm25,
                pm10=pm10,
                index=index,
                band=band_for_index(index.q50),
                drivers={DriverGroup.REGIONAL_POLLUTION: delta},
                explanation=message(f"explain.{direction}.regional_pollution", pollutant="PM2.5"),
            )
        )
    summary = max(hours, key=lambda x: abs(x.drivers[DriverGroup.REGIONAL_POLLUTION]))
    return ForecastResponse(
        generated_at=issued_at,
        station_id=station_id,
        issued_at=issued_at,
        model_version=MODEL_VERSION,
        stale=False,
        age_minutes=0,
        summary=summary.explanation,
        hours=hours,
    )
