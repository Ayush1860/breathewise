"""Generate contract fixtures in docs/fixtures/ from backend.schemas.

Values are synthetic but realistic for a Delhi October morning, and fully
deterministic (integer arithmetic only), so CI can detect drift.

    uv run python -m backend.scripts.make_fixtures
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from backend.naqi import hourly_pm_index, sub_index
from backend.schemas import (
    Activity,
    AdviceResponse,
    AqiValue,
    Band,
    BestWindow,
    CategoryAccuracy,
    CurrentAqiResponse,
    DriverGroup,
    ForecastHour,
    ForecastResponse,
    HealthResponse,
    HorizonMetrics,
    HorizonScore,
    IndexQuantiles,
    MetricsResponse,
    Pollutant,
    Profile,
    Quantiles,
    RefreshResponse,
    ReplayEpisode,
    ReplayHour,
    ReplayObservation,
    ScoreboardPoint,
    ScoreboardResponse,
    Source,
    SourceHealth,
    Station,
    StationHealth,
    StationsResponse,
    SubIndex,
    Verdict,
    band_for_index,
)
from backend.text import message

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "docs" / "fixtures"

GENERATED_AT = datetime(2026, 10, 10, 4, 5, tzinfo=UTC)  # 09:35 IST, event morning
ISSUED_AT = datetime(2026, 10, 10, 4, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)  # CPCB lags ~1 h
MODEL_VERSION = "lgbm-v1-fixture"

VENUE = Station(
    station_id="dl-rohini",
    name="Rohini, Delhi - DPCC",
    lat=28.7325,
    lon=77.1112,
    distance_km=2.4,
    coverage_pct=91.5,
    is_venue_default=True,
)
OTHER = Station(
    station_id="dl-anand-vihar",
    name="Anand Vihar, Delhi - DPCC",
    lat=28.6468,
    lon=77.3160,
    distance_km=22.7,
    coverage_pct=95.2,
)

_BAND_ORDER = list(Band)


_msg = message


def _sub_index(conc: float, pollutant: Pollutant) -> int:
    return sub_index(pollutant, conc)


def _pm_index(pm25: float, pm10: float) -> int:
    return hourly_pm_index(pm25, pm10)


_band = band_for_index


def _ist(t: datetime) -> str:
    return (t + timedelta(hours=5, minutes=30)).strftime("%H:%M")


def _age(t: datetime) -> int:
    return int((GENERATED_AT - t).total_seconds() // 60)


CURRENT_PM25 = 182.0
CURRENT_PM10 = 318.0
PM25_Q50 = (176.0, 168.0, 155.0, 138.0, 121.0, 108.0, 99.0, 94.0, 96.0, 104.0, 118.0, 134.0)


def _forecast_hours(
    issued_at: datetime, pm25_q50: Sequence[float], current_pm25: float
) -> list[ForecastHour]:
    hours = []
    for h, q50 in enumerate(pm25_q50, start=1):
        spread = (15 + 2 * h) / 100
        pm25 = Quantiles(
            q10=round(q50 * (1 - spread), 1), q50=q50, q90=round(q50 * (1 + 1.5 * spread), 1)
        )
        pm10 = Quantiles(
            q10=round(pm25.q10 * 1.75, 1),
            q50=round(q50 * 1.75, 1),
            q90=round(pm25.q90 * 1.75, 1),
        )
        index = IndexQuantiles(
            q10=_pm_index(pm25.q10, pm10.q10),
            q50=_pm_index(pm25.q50, pm10.q50),
            q90=_pm_index(pm25.q90, pm10.q90),
        )
        delta = q50 - current_pm25
        drivers = {
            DriverGroup.VENTILATION: round(delta * 0.6, 1),
            DriverGroup.RECENT_BUILDUP: round(delta * 0.15 + 6.0, 1),
            DriverGroup.REGIONAL_POLLUTION: round(delta * 0.1 + 3.0, 1),
        }
        drivers[DriverGroup.TIME_OF_DAY] = round(delta - sum(drivers.values()), 1)
        main = max(drivers, key=lambda g: abs(drivers[g]))
        direction = "rising" if delta > 0 else "falling"
        hours.append(
            ForecastHour(
                target_time=issued_at + timedelta(hours=h),
                horizon_h=h,
                pm25=pm25,
                pm10=pm10,
                index=index,
                band=_band(index.q50),
                drivers=drivers,
                explanation=_msg(f"explain.{direction}.{main.value}", pollutant="PM2.5"),
            )
        )
    return hours


def _forecast(issued_at: datetime, stale: bool) -> ForecastResponse:
    hours = _forecast_hours(issued_at, PM25_Q50, CURRENT_PM25)
    return ForecastResponse(
        generated_at=GENERATED_AT,
        station_id=VENUE.station_id,
        issued_at=issued_at,
        model_version=MODEL_VERSION,
        stale=stale,
        age_minutes=_age(issued_at),
        summary=min(hours, key=lambda x: x.pm25.q50).explanation,
        hours=hours,
    )


def _current(
    source: Source, observed_at: datetime, stale: bool = False, insufficient: bool = False
) -> CurrentAqiResponse:
    pm25, pm10, pm25_24h, pm10_24h = (
        (141.0, 236.0, 128.0, 221.0)
        if source is Source.CAMS_MODEL
        else (182.0, 318.0, 164.0, 290.0)
    )
    subs = [
        SubIndex(
            pollutant=Pollutant.PM25,
            concentration=pm25_24h,
            unit="ug_m3",
            sub_index=_sub_index(pm25_24h, Pollutant.PM25),
        ),
        SubIndex(
            pollutant=Pollutant.PM10,
            concentration=pm10_24h,
            unit="ug_m3",
            sub_index=_sub_index(pm10_24h, Pollutant.PM10),
        ),
        SubIndex(pollutant=Pollutant.NO2, concentration=62.0, unit="ug_m3", sub_index=77),
        SubIndex(pollutant=Pollutant.O3, concentration=38.0, unit="ug_m3", sub_index=38),
        SubIndex(pollutant=Pollutant.CO, concentration=1.4, unit="mg_m3", sub_index=70),
    ]
    if insufficient:
        subs = [s for s in subs if s.pollutant in (Pollutant.PM25, Pollutant.NO2)]
        aqi = AqiValue(status="insufficient_data", pollutants_present=[s.pollutant for s in subs])
        hourly = _sub_index(pm25, Pollutant.PM25)
    else:
        top = max(subs, key=lambda s: s.sub_index)
        aqi = AqiValue(
            status="ok",
            aqi=top.sub_index,
            band=_band(top.sub_index),
            dominant_pollutant=top.pollutant,
            pollutants_present=[s.pollutant for s in subs],
        )
        hourly = _pm_index(pm25, pm10)
    return CurrentAqiResponse(
        generated_at=GENERATED_AT,
        station=VENUE,
        observed_at=observed_at,
        source=source,
        stale=stale,
        age_minutes=_age(observed_at),
        aqi=aqi,
        hourly_index=hourly,
        hourly_band=_band(hourly),
        sub_indices=subs,
    )


def _best_window(
    hours: list[ForecastHour], duration: int, use_q90: bool, now_index: int
) -> BestWindow:
    values = [h.index.q90 if use_q90 else h.index.q50 for h in hours]
    starts = range(len(values) - duration + 1)
    best = min(starts, key=lambda i: (max(values[i : i + duration]), i))
    worst = max(values[best : best + duration])
    return BestWindow(
        start=hours[best].target_time,
        end=hours[best + duration - 1].target_time + timedelta(hours=1),
        worst_index=worst,
        band=_band(worst),
        improves_on_now=worst < now_index,
    )


# _SENSITIVE and _fixture_verdict are defined further down; they are only used at call time.
# (scenario name) -> (profile, activity, duration_h, now_index, reason key, reason params,
#                     advice keys)
_ADVICE_SCENARIOS: dict[str, tuple] = {
    "go": (
        Profile.HEALTHY_ADULT,
        Activity.WALK,
        1,
        85,
        "reason.general.satisfactory",
        {"band": "Satisfactory"},
        ["advice.go_ahead"],
    ),
    "go_with_n95": (
        Profile.HEALTHY_ADULT,
        Activity.RUN_EXERCISE,
        1,
        160,
        "reason.exertion.moderately_polluted",
        {"band": "Moderately Polluted"},
        ["advice.wear_n95", "advice.lower_intensity"],
    ),
    "avoid": (
        Profile.RESPIRATORY,
        Activity.WALK,
        2,
        348,
        "reason.sensitive.very_poor",
        {"band": "Very Poor", "condition": "respiratory conditions"},
        ["advice.stay_indoors", "advice.n95_if_must"],
    ),
    "reduce_exposure": (
        Profile.OUTDOOR_WORKER,
        Activity.OUTDOOR_WORK_SHIFT,
        8,
        348,
        "reason.outdoor_worker.very_poor",
        {"band": "Very Poor"},
        ["advice.n95_on_shift", "advice.indoor_breaks"],
    ),
}


def _advice(scenario: str) -> AdviceResponse:
    profile, activity, duration, now_index, reason_key, reason_params, advice_keys = (
        _ADVICE_SCENARIOS[scenario]
    )
    use_q90 = profile in _SENSITIVE
    hours = _forecast_hours(ISSUED_AT, PM25_Q50, CURRENT_PM25)
    window = _best_window(hours, duration, use_q90, now_index)
    advice = [_msg(key) for key in advice_keys]
    if window.improves_on_now:
        advice.append(
            _msg(
                "advice.use_best_window",
                activity=activity.value.replace("_", " "),
                start=_ist(window.start),
                end=_ist(window.end),
            )
        )
    return AdviceResponse(
        generated_at=GENERATED_AT,
        station_id=VENUE.station_id,
        profile=profile,
        activity=activity,
        duration_h=duration,
        forecast_issued_at=ISSUED_AT,
        model_version=MODEL_VERSION,
        stale=False,
        age_minutes=_age(ISSUED_AT),
        verdict=_fixture_verdict(now_index, profile, activity),
        reason=_msg(reason_key, **reason_params),
        advice=advice,
        basis="q90" if use_q90 else "q50",
        best_window=window,
    )


def _scoreboard() -> ScoreboardResponse:
    points = []
    for k in range(24):
        target = ISSUED_AT - timedelta(hours=23 - k)
        actual = None if k == 23 else float(150 + (k * 37) % 61 - 30)
        reference = actual if actual is not None else 150.0
        for h in range(1, 13):
            q50 = round(max(reference + ((k * 7 + h * 13) % 11 - 5) * h * 0.6, 0.0), 1)
            points.append(
                ScoreboardPoint(
                    target_time=target,
                    issued_at=target - timedelta(hours=h),
                    horizon_h=h,
                    predicted=Quantiles(q10=round(q50 * 0.8, 1), q50=q50, q90=round(q50 * 1.25, 1)),
                    actual=actual,
                )
            )
    per_horizon = []
    for h in range(1, 13):
        errors = [
            abs(p.predicted.q50 - p.actual)
            for p in points
            if p.horizon_h == h and p.actual is not None
        ]
        mae = round(sum(errors) / len(errors), 1) if errors else None
        per_horizon.append(HorizonScore(horizon_h=h, mae=mae, n=len(errors)))
    return ScoreboardResponse(
        generated_at=GENERATED_AT,
        station_id=VENUE.station_id,
        model_version=MODEL_VERSION,
        pollutant="pm25",
        since=ISSUED_AT - timedelta(hours=35),
        points=points,
        per_horizon=per_horizon,
    )


def _horizon_metrics(scale: float) -> list[HorizonMetrics]:
    return [
        HorizonMetrics(
            horizon_h=h,
            mae=round((9 + 2.1 * h) * scale, 1),
            rmse=round((9 + 2.1 * h) * 1.4 * scale, 1),
            mae_persistence=round((8 + 4.0 * h) * scale, 1),
            mae_cams=round((38 + 0.5 * h) * scale, 1),
            interval_coverage=round(0.80 - 0.004 * h, 3),
        )
        for h in range(1, 13)
    ]


def _metrics() -> MetricsResponse:
    return MetricsResponse(
        generated_at=GENERATED_AT,
        model_version=MODEL_VERSION,
        trained_until=datetime(2025, 10, 5, 17, 30, tzinfo=UTC),
        test_start=datetime(2025, 10, 5, 18, 30, tzinfo=UTC),
        test_end=datetime(2025, 12, 31, 18, 29, tzinfo=UTC),
        pm25=_horizon_metrics(1.0),
        pm10=_horizon_metrics(1.6),
        index_category_accuracy=[
            CategoryAccuracy(
                horizon_h=h,
                accuracy=round(0.84 - 0.015 * h, 3),
                accuracy_persistence=round(0.81 - 0.03 * h, 3),
            )
            for h in range(1, 13)
        ],
    )


def _health() -> HealthResponse:
    return HealthResponse(
        generated_at=GENERATED_AT,
        status="degraded",
        model_version=MODEL_VERSION,
        last_forecast_at=ISSUED_AT,
        sources=[
            SourceHealth(
                source=Source.CPCB,
                last_success_at=ISSUED_AT - timedelta(hours=2),
                last_failure_at=ISSUED_AT,
                last_error="HTTPStatusError 503",
            ),
            SourceHealth(
                source=Source.OPENAQ,
                last_success_at=ISSUED_AT,
                last_failure_at=None,
                last_error=None,
            ),
            SourceHealth(
                source=Source.CAMS_MODEL,
                last_success_at=ISSUED_AT,
                last_failure_at=None,
                last_error=None,
            ),
        ],
        stations=[
            StationHealth(
                station_id=VENUE.station_id,
                last_observation_at=OBSERVED_AT,
                last_source=Source.OPENAQ,
            ),
            StationHealth(
                station_id=OTHER.station_id,
                last_observation_at=OBSERVED_AT,
                last_source=Source.OPENAQ,
            ),
        ],
    )


_SENSITIVE = {Profile.RESPIRATORY, Profile.HEART, Profile.CHILD, Profile.ELDERLY, Profile.PREGNANT}
_EXERTION = {Activity.RUN_EXERCISE, Activity.CYCLING_COMMUTE}


def _fixture_verdict(index: int, profile: Profile, activity: Activity) -> Verdict:
    """Simplified stand-in for fixtures only; backend/advisory.py is the real engine."""
    level = _BAND_ORDER.index(_band(index)) + (profile in _SENSITIVE) + (activity in _EXERTION)
    if level >= 4:
        return Verdict.REDUCE_EXPOSURE if profile is Profile.OUTDOOR_WORKER else Verdict.AVOID
    if level == 3:
        return Verdict.GO_WITH_N95
    return Verdict.GO


def _replay() -> ReplayEpisode:
    start = datetime(2025, 11, 12, 18, 30, tzinfo=UTC)
    observed_pm25 = (210.0, 236.0, 262.0, 281.0, 274.0, 255.0)
    steps = []
    for i, pm25 in enumerate(observed_pm25):
        t = start + timedelta(hours=i)
        pm10 = round(pm25 * 1.7, 1)
        index = _pm_index(pm25, pm10)
        series = [round(pm25 + (6 - abs(h - 4)) * 4.0, 1) for h in range(1, 13)]
        hours = _forecast_hours(t, series, pm25)
        steps.append(
            ReplayHour(
                time=t,
                observed=ReplayObservation(pm25=pm25, pm10=pm10, index=index, band=_band(index)),
                forecast_hours=hours,
                summary=max(hours, key=lambda x: x.pm25.q50).explanation,
                persistence_pm25=pm25,
                cams_pm25=round(pm25 * 0.7, 1),
                verdicts={
                    f"{p.value}:{a.value}": _fixture_verdict(index, p, a)
                    for p in Profile
                    for a in Activity
                },
            )
        )
    return ReplayEpisode(
        episode_id="example",
        title="Synthetic example episode (real episodes are exported in Phase 7)",
        station=VENUE,
        start=start,
        end=start + timedelta(hours=len(observed_pm25) - 1),
        model_version=MODEL_VERSION,
        hours=steps,
    )


def build_fixtures() -> dict[str, BaseModel]:
    return {
        "stations.json": StationsResponse(generated_at=GENERATED_AT, stations=[VENUE, OTHER]),
        "aqi_current.fresh.json": _current(Source.CPCB, OBSERVED_AT),
        "aqi_current.stale.json": _current(
            Source.CPCB, GENERATED_AT - timedelta(minutes=185), stale=True
        ),
        "aqi_current.insufficient_data.json": _current(Source.CPCB, OBSERVED_AT, insufficient=True),
        "aqi_current.cams_fallback.json": _current(Source.CAMS_MODEL, OBSERVED_AT),
        "aqi_forecast.json": _forecast(ISSUED_AT, stale=False),
        "aqi_forecast.stale.json": _forecast(ISSUED_AT - timedelta(hours=3), stale=True),
        **{f"advice.{name}.json": _advice(name) for name in _ADVICE_SCENARIOS},
        "scoreboard.json": _scoreboard(),
        "metrics.json": _metrics(),
        "refresh.accepted.json": RefreshResponse(accepted=True, message=_msg("refresh.accepted")),
        "refresh.rate_limited.json": RefreshResponse(
            accepted=False, retry_after_s=212, message=_msg("refresh.rate_limited", minutes=4)
        ),
        "health.json": _health(),
        "replay/example.json": _replay(),
    }


def dump(model: BaseModel) -> str:
    return model.model_dump_json(indent=2) + "\n"


def main() -> None:
    for name, model in build_fixtures().items():
        path = FIXTURE_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump(model), encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(FIXTURE_DIR.parents[1])}")


if __name__ == "__main__":
    main()
