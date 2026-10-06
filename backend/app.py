"""BreatheWise HTTP API.

Live mode (TABLE_NAME set): reads DynamoDB via backend.service.
Fixture mode (no TABLE_NAME): serves docs/fixtures; the X-Mock-Scenario header selects a
variant (stale, insufficient_data, cams_fallback, go, go_with_n95, avoid, reduce_exposure,
rate_limited) so the UI can exercise every data state.
"""

import os
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend import service
from backend.schemas import (
    AdviceRequest,
    AdviceResponse,
    CurrentAqiResponse,
    ErrorResponse,
    ForecastResponse,
    HealthResponse,
    MetricsResponse,
    RefreshResponse,
    ScoreboardResponse,
    StationsResponse,
)
from backend.store import Store
from backend.text import message
from ingest.stations import load_stations

try:  # the advisory engine (backend/advisory.py) is owned by the advisory workstream
    from backend.advisory import advise
except ImportError:
    advise = None

MockScenario = Annotated[str, Header(alias="X-Mock-Scenario", include_in_schema=False)]
_DEFAULT_ORIGINS = "http://localhost:5173,http://localhost:3000"
STATIONS = load_stations()

app = FastAPI(
    title="BreatheWise API",
    version="1.0.0",
    description="Personalised, explainable air-quality decisions for Delhi. Times are UTC.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",") if o],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Mock-Scenario"],
)

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Unknown station_id"}}
UNAVAILABLE = {503: {"model": ErrorResponse, "description": "No data available yet"}}


class ApiError(Exception):
    def __init__(self, status: int, error: str, detail: str):
        super().__init__(detail)
        self.status, self.error, self.detail = status, error, detail


def _error(status: int, error: str, detail: str, headers=None) -> JSONResponse:
    body = ErrorResponse(error=error, message=detail)
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


@app.exception_handler(HTTPException)
def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail), exc.headers)


@app.exception_handler(ApiError)
def _api_error(request: Request, exc: ApiError) -> JSONResponse:
    return _error(exc.status, exc.error, exc.detail)


@app.exception_handler(service.NotFound)
def _not_found(request: Request, exc: service.NotFound) -> JSONResponse:
    return _error(404, "not_found", str(exc))


def live() -> bool:
    return bool(os.environ.get("TABLE_NAME"))


@lru_cache(maxsize=1)
def store() -> Store:
    import boto3

    return Store(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))


def now() -> datetime:
    return datetime.now(UTC)


def trigger_ingest() -> None:
    import boto3

    boto3.client("lambda").invoke(
        FunctionName=os.environ["INGEST_FUNCTION"], InvocationType="Event"
    )


def _fixtures():
    from backend import fixture_store  # fixture mode only; not packaged for Lambda

    return fixture_store


def _require(value, what: str):
    if value is None:
        raise ApiError(503, "no_data", f"no {what} available yet")
    return value


def _location(lat: float | None, lon: float | None) -> tuple[float, float] | None:
    return (lat, lon) if lat is not None and lon is not None else None


@app.get("/stations", response_model=StationsResponse)
def get_stations(
    lat: float | None = None,
    lon: float | None = None,
    radius_km: Annotated[float, Query(gt=0, le=100)] = 25.0,
    scenario: MockScenario = "default",
):
    if not live():
        return _fixtures().load("stations", scenario)
    location = _location(lat, lon)
    views = [service.station_view(s, location) for s in STATIONS]
    if location:
        views = sorted(
            (v for v in views if v.distance_km <= radius_km), key=lambda v: v.distance_km
        )
    return StationsResponse(generated_at=now(), stations=views)


@app.get("/aqi/current", response_model=CurrentAqiResponse, responses=NOT_FOUND | UNAVAILABLE)
def get_current_aqi(
    station_id: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    scenario: MockScenario = "default",
):
    if not live():
        return _fixtures().load("aqi_current", scenario)
    station = service.resolve_station(STATIONS, station_id, lat, lon)
    current = service.current_aqi(store(), station, now(), _location(lat, lon))
    return _require(current, "observations")


@app.get("/aqi/forecast", response_model=ForecastResponse, responses=NOT_FOUND | UNAVAILABLE)
def get_forecast(station_id: str | None = None, scenario: MockScenario = "default"):
    if not live():
        return _fixtures().load("aqi_forecast", scenario)
    station = service.resolve_station(STATIONS, station_id, None, None)
    return _require(service.forecast_view(store(), station, now()), "forecast")


@app.post("/advice", response_model=AdviceResponse, responses=NOT_FOUND | UNAVAILABLE)
def post_advice(body: AdviceRequest, scenario: MockScenario = "default"):
    if not live():
        return _fixtures().load("advice", scenario)
    station = service.resolve_station(STATIONS, body.station_id, None, None)
    at = now()
    forecast = _require(service.forecast_view(store(), station, at), "forecast")
    if advise is None:
        raise ApiError(503, "advisory_unavailable", "advisory engine is not deployed yet")
    current = service.current_aqi(store(), station, at, None)
    return advise(body, forecast, current, at)


@app.get("/scoreboard", response_model=ScoreboardResponse, responses=NOT_FOUND)
def get_scoreboard(
    station_id: str | None = None,
    model_version: str | None = None,
    pollutant: Literal["pm25", "pm10"] = "pm25",
    scenario: MockScenario = "default",
):
    if not live():
        return _fixtures().load("scoreboard", scenario)
    station = service.resolve_station(STATIONS, station_id, None, None)
    return service.scoreboard(store(), station, model_version, pollutant, now())


@app.get("/metrics", response_model=MetricsResponse, responses=UNAVAILABLE)
def get_metrics(scenario: MockScenario = "default"):
    if not live():
        return _fixtures().load("metrics", scenario)
    path = os.environ.get("METRICS_PATH", "")
    if not path or not os.path.exists(path):
        raise ApiError(503, "no_data", "model metrics are not published yet")
    with open(path, encoding="utf-8") as fh:
        return MetricsResponse.model_validate_json(fh.read())


@app.get("/health", response_model=HealthResponse)
def get_health(scenario: MockScenario = "default"):
    if not live():
        return _fixtures().load("health", scenario)
    return service.health(store(), STATIONS, now())


@app.post(
    "/refresh",
    status_code=202,
    response_model=RefreshResponse,
    responses={429: {"model": RefreshResponse, "description": "Refreshed in the last 5 min"}},
)
def post_refresh(
    response: Response, station_id: str | None = None, scenario: MockScenario = "default"
):
    if not live():
        result = _fixtures().load("refresh", scenario)
    else:
        retry = service.try_refresh(store(), now())
        if retry is None:
            trigger_ingest()
            result = RefreshResponse(accepted=True, message=message("refresh.accepted"))
        else:
            result = RefreshResponse(
                accepted=False,
                retry_after_s=retry,
                message=message("refresh.rate_limited", minutes=max(round(retry / 60), 1)),
            )
    if not result.accepted:
        response.status_code = 429
        response.headers["Retry-After"] = str(result.retry_after_s)
    return result
