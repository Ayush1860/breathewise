"""BreatheWise HTTP API.

Phase 1: routes serve the contract fixtures in docs/fixtures/. The optional
X-Mock-Scenario header selects a variant (stale, insufficient_data, cams_fallback,
rate_limited) so the UI can exercise every data state.
"""

import os
from typing import Annotated

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend import fixture_store
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

MockScenario = Annotated[str, Header(alias="X-Mock-Scenario", include_in_schema=False)]
_DEFAULT_ORIGINS = "http://localhost:5173,http://localhost:3000"

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


@app.exception_handler(HTTPException)
def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
    body = ErrorResponse(error=f"http_{exc.status_code}", message=str(exc.detail))
    return JSONResponse(body.model_dump(), status_code=exc.status_code, headers=exc.headers)


@app.get("/stations", response_model=StationsResponse)
def get_stations(
    lat: float | None = None,
    lon: float | None = None,
    radius_km: Annotated[float, Query(gt=0, le=100)] = 25.0,
    scenario: MockScenario = "default",
):
    return fixture_store.load("stations", scenario)


@app.get("/aqi/current", response_model=CurrentAqiResponse, responses=NOT_FOUND)
def get_current_aqi(
    station_id: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    scenario: MockScenario = "default",
):
    return fixture_store.load("aqi_current", scenario)


@app.get("/aqi/forecast", response_model=ForecastResponse, responses=NOT_FOUND)
def get_forecast(station_id: str | None = None, scenario: MockScenario = "default"):
    return fixture_store.load("aqi_forecast", scenario)


@app.post("/advice", response_model=AdviceResponse, responses=NOT_FOUND)
def post_advice(body: AdviceRequest, scenario: MockScenario = "default"):
    return fixture_store.load("advice", scenario)


@app.get("/scoreboard", response_model=ScoreboardResponse, responses=NOT_FOUND)
def get_scoreboard(
    station_id: str | None = None,
    model_version: str | None = None,
    scenario: MockScenario = "default",
):
    return fixture_store.load("scoreboard", scenario)


@app.get("/metrics", response_model=MetricsResponse)
def get_metrics(scenario: MockScenario = "default"):
    return fixture_store.load("metrics", scenario)


@app.get("/health", response_model=HealthResponse)
def get_health(scenario: MockScenario = "default"):
    return fixture_store.load("health", scenario)


@app.post(
    "/refresh",
    status_code=202,
    response_model=RefreshResponse,
    responses={429: {"model": RefreshResponse, "description": "Refreshed in the last 5 min"}},
)
def post_refresh(
    response: Response, station_id: str | None = None, scenario: MockScenario = "default"
):
    result = fixture_store.load("refresh", scenario)
    if not result.accepted:
        response.status_code = 429
        response.headers["Retry-After"] = str(result.retry_after_s)
    return result
