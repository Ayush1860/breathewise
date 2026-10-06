"""Serve contract fixtures by endpoint and scenario (Phase 1 mock storage)."""

from pydantic import BaseModel

from backend.schemas import (
    AdviceResponse,
    CurrentAqiResponse,
    ForecastResponse,
    HealthResponse,
    MetricsResponse,
    RefreshResponse,
    ScoreboardResponse,
    StationsResponse,
)
from backend.scripts.make_fixtures import FIXTURE_DIR

_FILES: dict[str, dict[str, tuple[str, type[BaseModel]]]] = {
    "stations": {"default": ("stations.json", StationsResponse)},
    "aqi_current": {
        "default": ("aqi_current.fresh.json", CurrentAqiResponse),
        "stale": ("aqi_current.stale.json", CurrentAqiResponse),
        "insufficient_data": ("aqi_current.insufficient_data.json", CurrentAqiResponse),
        "cams_fallback": ("aqi_current.cams_fallback.json", CurrentAqiResponse),
    },
    "aqi_forecast": {
        "default": ("aqi_forecast.json", ForecastResponse),
        "stale": ("aqi_forecast.stale.json", ForecastResponse),
    },
    "advice": {
        "default": ("advice.avoid.json", AdviceResponse),
        "go": ("advice.go.json", AdviceResponse),
        "go_with_n95": ("advice.go_with_n95.json", AdviceResponse),
        "avoid": ("advice.avoid.json", AdviceResponse),
        "reduce_exposure": ("advice.reduce_exposure.json", AdviceResponse),
    },
    "scoreboard": {"default": ("scoreboard.json", ScoreboardResponse)},
    "metrics": {"default": ("metrics.json", MetricsResponse)},
    "health": {"default": ("health.json", HealthResponse)},
    "refresh": {
        "default": ("refresh.accepted.json", RefreshResponse),
        "rate_limited": ("refresh.rate_limited.json", RefreshResponse),
    },
}


def load(endpoint: str, scenario: str = "default") -> BaseModel:
    variants = _FILES[endpoint]
    filename, model = variants.get(scenario, variants["default"])
    return model.model_validate_json((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
