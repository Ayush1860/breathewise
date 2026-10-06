"""BreatheWise API contract.

These pydantic models are the single source of truth. docs/openapi.json and
docs/fixtures/ are generated from them; tests fail if either drifts.
All datetimes are timezone-aware UTC.
"""

from datetime import UTC, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class Source(StrEnum):
    CPCB = "cpcb"
    OPENAQ = "openaq"
    CAMS_MODEL = "cams_model"


class Band(StrEnum):
    GOOD = "good"
    SATISFACTORY = "satisfactory"
    MODERATELY_POLLUTED = "moderately_polluted"
    POOR = "poor"
    VERY_POOR = "very_poor"
    SEVERE = "severe"


class Pollutant(StrEnum):
    PM25 = "pm25"
    PM10 = "pm10"
    NO2 = "no2"
    O3 = "o3"
    CO = "co"
    SO2 = "so2"
    NH3 = "nh3"


class Profile(StrEnum):
    HEALTHY_ADULT = "healthy_adult"
    RESPIRATORY = "respiratory"
    HEART = "heart"
    CHILD = "child"
    ELDERLY = "elderly"
    PREGNANT = "pregnant"
    OUTDOOR_WORKER = "outdoor_worker"


class Activity(StrEnum):
    WALK = "walk"
    RUN_EXERCISE = "run_exercise"
    CYCLING_COMMUTE = "cycling_commute"
    TWO_WHEELER_COMMUTE = "two_wheeler_commute"
    KIDS_OUTDOOR_PLAY = "kids_outdoor_play"
    OUTDOOR_WORK_SHIFT = "outdoor_work_shift"


class Verdict(StrEnum):
    GO = "GO"
    GO_WITH_N95 = "GO_WITH_N95"
    AVOID = "AVOID"
    REDUCE_EXPOSURE = "REDUCE_EXPOSURE"


class DriverGroup(StrEnum):
    VENTILATION = "ventilation"
    RECENT_BUILDUP = "recent_buildup"
    REGIONAL_POLLUTION = "regional_pollution"
    TIME_OF_DAY = "time_of_day"
    UPWIND_FIRES = "upwind_fires"


UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda d: d.astimezone(UTC))]
"""Timezone-aware datetime, normalised to UTC (serialises with a trailing Z)."""

_BAND_UPPER = (
    (50, Band.GOOD),
    (100, Band.SATISFACTORY),
    (200, Band.MODERATELY_POLLUTED),
    (300, Band.POOR),
    (400, Band.VERY_POOR),
)


def band_for_index(index: int) -> Band:
    """NAQI band for an index value (CPCB category ranges)."""
    for upper, band in _BAND_UPPER:
        if index <= upper:
            return band
    return Band.SEVERE


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        json_schema_serialization_defaults_required=True,
    )


class Message(Model):
    """User-facing text: a stable key (for styling/translation), its params, rendered English."""

    key: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    params: dict[str, str | int | float] = Field(default_factory=dict)
    text: str


class Station(Model):
    station_id: str
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    distance_km: float | None = Field(default=None, ge=0)
    coverage_pct: float | None = Field(default=None, ge=0, le=100)
    is_venue_default: bool = False


class StationsResponse(Model):
    generated_at: UtcDatetime
    stations: list[Station]


class SubIndex(Model):
    pollutant: Pollutant
    concentration: float = Field(ge=0)
    unit: Literal["ug_m3", "mg_m3"]
    sub_index: int = Field(ge=0, le=500)


class AqiValue(Model):
    """Official-method NAQI (24 h / 8 h averages). Needs >=3 pollutants incl. PM2.5 or PM10."""

    status: Literal["ok", "insufficient_data"]
    aqi: int | None = Field(default=None, ge=0, le=500)
    band: Band | None = None
    dominant_pollutant: Pollutant | None = None
    pollutants_present: list[Pollutant]

    @model_validator(mode="after")
    def _status_matches_fields(self) -> "AqiValue":
        filled = (self.aqi, self.band, self.dominant_pollutant)
        if self.status == "ok" and any(v is None for v in filled):
            raise ValueError("status 'ok' requires aqi, band and dominant_pollutant")
        if self.status == "insufficient_data" and any(v is not None for v in filled):
            raise ValueError("status 'insufficient_data' must not carry aqi, band or dominant")
        if self.dominant_pollutant is not None and (
            self.dominant_pollutant not in self.pollutants_present
        ):
            raise ValueError("dominant_pollutant must be one of pollutants_present")
        return self


class CurrentAqiResponse(Model):
    generated_at: UtcDatetime
    station: Station
    observed_at: UtcDatetime
    source: Source
    stale: bool
    age_minutes: int = Field(ge=0)
    aqi: AqiValue
    hourly_index: int | None = Field(
        default=None, ge=0, le=500, description="Indicative NAQI from the latest hourly PM values"
    )
    hourly_band: Band | None = None
    sub_indices: list[SubIndex]

    @model_validator(mode="after")
    def _hourly_pair(self) -> "CurrentAqiResponse":
        if (self.hourly_index is None) != (self.hourly_band is None):
            raise ValueError("hourly_index and hourly_band must be set together")
        return self


def _check_ordered(q10: float, q50: float, q90: float) -> None:
    if not q10 <= q50 <= q90:
        raise ValueError("quantiles must be ordered q10 <= q50 <= q90")


class Quantiles(Model):
    """Concentration quantiles in ug/m3."""

    q10: float = Field(ge=0)
    q50: float = Field(ge=0)
    q90: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "Quantiles":
        _check_ordered(self.q10, self.q50, self.q90)
        return self


class IndexQuantiles(Model):
    """PM-based hourly NAQI index at each concentration quantile."""

    q10: int = Field(ge=0, le=500)
    q50: int = Field(ge=0, le=500)
    q90: int = Field(ge=0, le=500)

    @model_validator(mode="after")
    def _ordered(self) -> "IndexQuantiles":
        _check_ordered(self.q10, self.q50, self.q90)
        return self


class ForecastHour(Model):
    target_time: UtcDatetime = Field(description="Start of the forecast hour (UTC)")
    horizon_h: int = Field(ge=1, le=12)
    pm25: Quantiles
    pm10: Quantiles
    index: IndexQuantiles
    band: Band = Field(description="Band of index.q50")
    drivers: dict[DriverGroup, float] = Field(
        description="Signed contribution of each driver group to the PM2.5 median, ug/m3"
    )
    explanation: Message

    @model_validator(mode="after")
    def _band_matches_index(self) -> "ForecastHour":
        if self.band != band_for_index(self.index.q50):
            raise ValueError("band must be the band of index.q50")
        return self


class ForecastResponse(Model):
    generated_at: UtcDatetime
    station_id: str
    issued_at: UtcDatetime
    model_version: str
    basis: Literal["pm_only"] = "pm_only"
    stale: bool
    age_minutes: int = Field(ge=0)
    summary: Message
    hours: list[ForecastHour] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def _horizons_in_order(self) -> "ForecastResponse":
        if [h.horizon_h for h in self.hours] != list(range(1, 13)):
            raise ValueError("forecast horizons must be exactly 1..12 in order")
        for hour in self.hours:
            if hour.target_time != self.issued_at + timedelta(hours=hour.horizon_h):
                raise ValueError("target_time must equal issued_at + horizon_h hours")
        return self


class AdviceRequest(Model):
    profile: Profile
    activity: Activity
    duration_h: int = Field(ge=1, le=12)
    station_id: str | None = Field(default=None, description="Defaults to the venue station")


class BestWindow(Model):
    start: UtcDatetime
    end: UtcDatetime
    worst_index: int = Field(ge=0, le=500)
    band: Band
    improves_on_now: bool

    @model_validator(mode="after")
    def _end_after_start(self) -> "BestWindow":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class AdviceResponse(Model):
    generated_at: UtcDatetime
    station_id: str
    profile: Profile
    activity: Activity
    duration_h: int = Field(ge=1, le=12)
    forecast_issued_at: UtcDatetime
    model_version: str
    stale: bool
    age_minutes: int = Field(ge=0)
    verdict: Verdict
    reason: Message
    advice: list[Message]
    basis: Literal["q50", "q90"] = Field(description="q90 (cautious) for sensitive profiles")
    best_window: BestWindow | None


class ScoreboardPoint(Model):
    target_time: UtcDatetime
    issued_at: UtcDatetime
    horizon_h: int = Field(ge=1, le=12)
    predicted: Quantiles
    actual: float | None = Field(default=None, ge=0)


class HorizonScore(Model):
    horizon_h: int = Field(ge=1, le=12)
    mae: float | None = Field(default=None, ge=0)
    n: int = Field(ge=0)


class ScoreboardResponse(Model):
    generated_at: UtcDatetime
    station_id: str
    model_version: str
    pollutant: Literal["pm25", "pm10"]
    since: UtcDatetime
    points: list[ScoreboardPoint]
    per_horizon: list[HorizonScore]


class HorizonMetrics(Model):
    horizon_h: int = Field(ge=1, le=12)
    mae: float = Field(ge=0)
    rmse: float = Field(ge=0)
    mae_persistence: float = Field(ge=0)
    mae_cams: float = Field(ge=0)
    interval_coverage: float = Field(ge=0, le=1, description="Share of actuals inside [q10, q90]")


class CategoryAccuracy(Model):
    horizon_h: int = Field(ge=1, le=12)
    accuracy: float = Field(ge=0, le=1)
    accuracy_persistence: float = Field(ge=0, le=1)


class MetricsResponse(Model):
    generated_at: UtcDatetime
    model_version: str
    trained_until: UtcDatetime
    test_start: UtcDatetime
    test_end: UtcDatetime
    pm25: list[HorizonMetrics]
    pm10: list[HorizonMetrics]
    index_category_accuracy: list[CategoryAccuracy]


class RefreshResponse(Model):
    accepted: bool
    retry_after_s: int | None = Field(default=None, ge=0)
    message: Message

    @model_validator(mode="after")
    def _retry_after_when_refused(self) -> "RefreshResponse":
        if not self.accepted and self.retry_after_s is None:
            raise ValueError("retry_after_s is required when accepted is false")
        return self


class SourceHealth(Model):
    source: Source
    last_success_at: UtcDatetime | None
    last_failure_at: UtcDatetime | None
    last_error: str | None


class StationHealth(Model):
    station_id: str
    last_observation_at: UtcDatetime | None
    last_source: Source | None


class HealthResponse(Model):
    generated_at: UtcDatetime
    status: Literal["ok", "degraded", "down"]
    model_version: str | None
    last_forecast_at: UtcDatetime | None
    sources: list[SourceHealth]
    stations: list[StationHealth]


class ReplayObservation(Model):
    pm25: float | None = Field(default=None, ge=0)
    pm10: float | None = Field(default=None, ge=0)
    index: int | None = Field(default=None, ge=0, le=500)
    band: Band | None = None


_PROFILES = {p.value for p in Profile}
_ACTIVITIES = {a.value for a in Activity}


class ReplayHour(Model):
    time: UtcDatetime = Field(description="Issue time of this replay step")
    observed: ReplayObservation
    forecast_hours: list[ForecastHour] = Field(min_length=12, max_length=12)
    summary: Message
    persistence_pm25: float | None = Field(default=None, ge=0)
    cams_pm25: float | None = Field(default=None, ge=0)
    verdicts: dict[str, Verdict] = Field(description="Keyed 'profile:activity'")

    @field_validator("verdicts")
    @classmethod
    def _keys_are_profile_activity(cls, value: dict[str, Verdict]) -> dict[str, Verdict]:
        for key in value:
            profile, _, activity = key.partition(":")
            if profile not in _PROFILES or activity not in _ACTIVITIES:
                raise ValueError(f"verdict key {key!r} must be 'profile:activity'")
        return value


class ReplayEpisode(Model):
    episode_id: str
    title: str
    station: Station
    start: UtcDatetime
    end: UtcDatetime
    model_version: str
    hours: list[ReplayHour]


class ErrorResponse(Model):
    error: str
    message: str
