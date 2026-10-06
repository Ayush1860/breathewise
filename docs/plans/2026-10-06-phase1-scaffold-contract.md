# Phase 1 — Scaffold, API Contract and Fixtures: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** By the end of Phase 1, the repository exists, CI is green, and the API contract is final. The contract consists of the pydantic schemas, `docs/openapi.json`, the fixtures and a fixture-backed mock server, so Member B can start the UI today.

**Architecture:** There is one Python 3.12 uv project at the repo root, with the top-level packages `backend`, `ingest` and `ml`. `backend/schemas.py` is the single source of truth. A deterministic generator writes `docs/fixtures/*.json` from those schemas, and FastAPI exports `docs/openapi.json`. Tests fail if either file drifts from the schemas. The FastAPI app serves fixtures; the `X-Mock-Scenario` header selects a data state.

**Tech Stack:** Python 3.12 (via uv), pydantic v2, FastAPI, pytest, ruff, black, GitHub Actions, gh CLI.

**Spec:** `docs/specs/2026-10-06-breathewise-core-design.md` (§10 contract, §14 repo and workflow).

## Global Constraints

- Python `>=3.12,<3.13`, managed with `uv`. `uv.lock` is committed.
- No committed file, commit message, branch name or PR text may mention the AI assistant or its vendor. Assistant-specific local files are excluded through `.git/info/exclude`, never through `.gitignore`.
- No AI co-author trailers. Conventional Commits only.
- Branch for this phase: `as/repo-scaffold`. Never push to `main` directly. The one exception is the bootstrap push of the spec and plan commits (Task 6 Step 1), which happens before branch protection exists. Task 1's commits stay on the branch.
- Merge strategy: rebase-merge only (`gh pr merge --rebase --delete-branch`).
- Member B's GitHub handle is written as `@MEMBER_B` below. Replace it with the real handle supplied by the user before running any step that uses it.
- All datetimes in the contract are timezone-aware UTC and serialise with a trailing `Z`.
- Every response has `generated_at`. Every data payload has a `source` or `model_version`, an `observed_at` or `issued_at`, and `stale` with `age_minutes`.
- Secrets live only in `.env`, which is git-ignored. `.env.example` is committed with empty values.
- The contract is **final** at the end of this phase. Later changes must be additive only.
- Black and ruff line length is 100.

## Review Focus

1. **Fixture or OpenAPI drift.** When a schema field changes and the fixtures are not regenerated, B's UI would break silently. Expected: a test fails and names the regenerate command. (Task 3, Task 4)
2. **Quantile crossing in a payload** (q10 > q50). Expected: the schema rejects it, so no crossed band can reach the UI. (Task 2)
3. **An inconsistent AQI status** ("ok" with a null AQI, or "insufficient_data" with a value). Expected: rejected. (Task 2)
4. **Naive (timezone-less) datetimes**, which would show "updated X min ago" wrong by 5.5 h. Expected: rejected; UTC serialises with `Z`. (Task 2)
5. **A forecast with missing or out-of-order horizons.** Expected: rejected, because the best-window finder and the chart assume exactly h=1…12 in order. (Task 2)

---

## Execution order

Task 0 → Task 1 → Task 6 Steps 1–3 (public repo, push, labels, repo settings, invite B) → Tasks 2–5 → Task 6 Steps 4–9.

## File map

| File | Responsibility |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | Project, dependencies and tool config |
| `.gitignore`, `.gitattributes`, `.env.example` | Hygiene: LF line endings, secrets kept out |
| `backend/__init__.py`, `ingest/__init__.py`, `ml/__init__.py` | Package roots |
| `backend/schemas.py` | API contract (pydantic) |
| `backend/scripts/make_fixtures.py` | Deterministic fixture generator |
| `backend/scripts/export_openapi.py` | Writes `docs/openapi.json` |
| `backend/fixture_store.py` | Loads a fixture by endpoint and scenario |
| `backend/app.py` | FastAPI app; Phase 1 routes serve fixtures |
| `backend/tests/test_schemas.py`, `test_fixtures.py`, `test_app.py` | Tests |
| `docs/fixtures/**.json`, `docs/fixtures/README.md`, `docs/openapi.json` | Generated contract artefacts plus an index |
| `.github/workflows/ci.yml`, `.github/CODEOWNERS`, `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/{task,bug}.md` | CI and GitHub process |
| `README.md`, `CONTRIBUTING.md`, `frontend/README.md`, `infra/README.md` | Docs and placeholders |

---

### Task 0: Identity and local exclusions

**Files:** `.git/config` and `.git/info/exclude` (both local only, never committed).

- [ ] **Step 1: Pin the commit identity.** The user confirmed `ayushsuryawanshi9@gmail.com`. Pin it for this repo:

```bash
git config user.email "ayushsuryawanshi9@gmail.com"
git log --format="%h %an <%ae> %s"
```

Expected: every existing commit already shows `ayushsuryawanshi9@gmail.com`.

- [ ] **Step 2: Do not re-author anything.** The identity is unchanged.

- [ ] **Step 3: Exclude the assistant's local instruction file and its local settings directory.** Add their names to `.git/info/exclude`. The names are recorded in the operator's local notes, not in this repo. Verify with `git status --ignored`.

- [ ] **Step 4: Create the phase branch:**

```bash
git switch -c as/repo-scaffold
```

---

### Task 1: Python project tooling

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `.gitattributes`, `.env.example`, `backend/__init__.py`, `backend/scripts/__init__.py`, `backend/tests/__init__.py`, `ingest/__init__.py`, `ml/__init__.py`, `backend/tests/test_smoke.py`

**Interfaces:**
- Produces: `uv run pytest`, `uv run ruff check .` and `uv run black --check .` all work from the repo root, and `import backend` resolves.

- [ ] **Step 1: Write `pyproject.toml`:**

```toml
[project]
name = "breathewise"
version = "0.1.0"
description = "Explainable, personalised air-quality decision assistant for Delhi"
requires-python = ">=3.12,<3.13"
dependencies = [
    "pydantic>=2.9,<3",
    "fastapi>=0.115,<1",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "ruff>=0.6",
    "black>=24.8",
    "httpx>=0.27",
    "uvicorn>=0.30",
]

[tool.uv]
package = false

[tool.pytest.ini_options]
testpaths = ["backend/tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.black]
line-length = 100
target-version = ["py312"]
```

- [ ] **Step 2: Write `.python-version`** containing `3.12`.

- [ ] **Step 3: Write `.gitignore`:**

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/

# Secrets
.env
.env.*
!.env.example

# Data and model artefacts (live in S3, never git)
data/
ml/artifacts/
*.lgb
*.parquet

# Build output
.aws-sam/
build/
dist/
*.zip

# Frontend
node_modules/

# OS / editors
.DS_Store
Thumbs.db
.vscode/
.idea/
```

- [ ] **Step 4: Write `.gitattributes`:**

```gitattributes
* text=auto eol=lf
*.png binary
```

- [ ] **Step 5: Write `.env.example`:**

```dotenv
# Copy to .env and fill in. Never commit .env.
DATA_GOV_IN_API_KEY=
OPENAQ_API_KEY=
FIRMS_MAP_KEY=
AWS_REGION=ap-south-1
VENUE_STATION_ID=
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

- [ ] **Step 6: Create the empty package files** `backend/__init__.py`, `backend/scripts/__init__.py`, `backend/tests/__init__.py`, `ingest/__init__.py` and `ml/__init__.py`. Then write the smoke test `backend/tests/test_smoke.py`:

```python
import sys


def test_python_is_312():
    assert sys.version_info[:2] == (3, 12)
```

- [ ] **Step 7: Install Python 3.12, sync and run:**

```bash
uv python install 3.12
uv sync
uv run pytest -q
uv run ruff check .
uv run black --check .
```

Expected: `1 passed`; ruff prints `All checks passed!`; black reports that all files would be left unchanged.

- [ ] **Step 8: Normalise line endings and commit:**

```bash
git add --renormalize .
git add pyproject.toml uv.lock .python-version .gitignore .gitattributes .env.example backend ingest ml
git commit -m "chore: scaffold uv project with ruff, black and pytest"
```

---

### Task 2: API contract schemas

**Files:**
- Create: `backend/schemas.py`
- Test: `backend/tests/test_schemas.py`

**Interfaces:**
- Produces these names, which later tasks and phases use exactly as written:
  - **Enums:** `Source`, `Band`, `Pollutant`, `Profile`, `Activity`, `Verdict`, `DriverGroup`.
  - **Building blocks:** `Message(key, params, text)`, `Station`, `SubIndex`, `AqiValue`, `Quantiles`, `IndexQuantiles`, `ForecastHour`, `BestWindow`, `ScoreboardPoint`, `HorizonScore`, `HorizonMetrics`, `CategoryAccuracy`, `SourceHealth`, `StationHealth`, `ReplayObservation`, `ReplayHour`, `ReplayEpisode`, `ErrorResponse`.
  - **Request and responses:** `StationsResponse`, `CurrentAqiResponse`, `ForecastResponse`, `AdviceRequest`, `AdviceResponse`, `ScoreboardResponse`, `MetricsResponse`, `RefreshResponse`, `HealthResponse`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_schemas.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.schemas import (
    AqiValue,
    Band,
    BestWindow,
    DriverGroup,
    ForecastHour,
    ForecastResponse,
    IndexQuantiles,
    Message,
    Pollutant,
    Quantiles,
    ReplayHour,
    ReplayObservation,
    Verdict,
)

T0 = datetime(2026, 10, 10, 4, 0, tzinfo=UTC)
MSG = Message(key="explain.falling.ventilation", params={"pollutant": "PM2.5"}, text="x")


def _hour(h: int) -> ForecastHour:
    return ForecastHour(
        target_time=T0 + timedelta(hours=h),
        horizon_h=h,
        pm25=Quantiles(q10=80, q50=100, q90=120),
        pm10=Quantiles(q10=140, q50=175, q90=210),
        index=IndexQuantiles(q10=263, q50=330, q90=346),
        band=Band.VERY_POOR,
        drivers={DriverGroup.VENTILATION: -12.5},
        explanation=MSG,
    )


def _forecast(hours: list[ForecastHour]) -> ForecastResponse:
    return ForecastResponse(
        generated_at=T0,
        station_id="dl-rohini",
        issued_at=T0,
        model_version="lgbm-v1-test",
        stale=False,
        age_minutes=5,
        summary=MSG,
        hours=hours,
    )


def test_quantiles_must_be_ordered():
    with pytest.raises(ValidationError, match="ordered"):
        Quantiles(q10=50, q50=40, q90=60)


def test_quantiles_accept_equal_values():
    assert Quantiles(q10=40, q50=40, q90=40).q50 == 40


def test_index_quantiles_must_be_ordered():
    with pytest.raises(ValidationError, match="ordered"):
        IndexQuantiles(q10=300, q50=200, q90=400)


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        Quantiles(q10=1, q50=2, q90=3, q99=4)


def test_aqi_ok_requires_value_band_and_dominant():
    with pytest.raises(ValidationError, match="requires"):
        AqiValue(status="ok", pollutants_present=[Pollutant.PM25])


def test_aqi_insufficient_must_not_carry_value():
    with pytest.raises(ValidationError, match="must not carry"):
        AqiValue(
            status="insufficient_data",
            aqi=120,
            band=Band.MODERATELY_POLLUTED,
            dominant_pollutant=Pollutant.PM25,
            pollutants_present=[Pollutant.PM25],
        )


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        BestWindow(
            start=datetime(2026, 10, 10, 4),
            end=datetime(2026, 10, 10, 6),
            worst_index=150,
            band=Band.MODERATELY_POLLUTED,
            improves_on_now=True,
        )


def test_datetimes_serialise_as_utc_z():
    window = BestWindow(
        start=T0,
        end=T0 + timedelta(hours=2),
        worst_index=150,
        band=Band.MODERATELY_POLLUTED,
        improves_on_now=True,
    )
    assert window.model_dump(mode="json")["start"] == "2026-10-10T04:00:00Z"


def test_best_window_end_must_follow_start():
    with pytest.raises(ValidationError, match="after start"):
        BestWindow(
            start=T0,
            end=T0,
            worst_index=150,
            band=Band.MODERATELY_POLLUTED,
            improves_on_now=False,
        )


def test_forecast_accepts_horizons_1_to_12():
    assert len(_forecast([_hour(h) for h in range(1, 13)]).hours) == 12


def test_forecast_rejects_out_of_order_horizons():
    hours = [_hour(h) for h in range(1, 13)]
    hours[3], hours[4] = hours[4], hours[3]
    with pytest.raises(ValidationError, match="horizons"):
        _forecast(hours)


def test_forecast_rejects_eleven_hours():
    with pytest.raises(ValidationError):
        _forecast([_hour(h) for h in range(1, 12)])


def test_message_key_must_be_dotted_lowercase():
    with pytest.raises(ValidationError):
        Message(key="Bad Key", text="x")


def test_replay_verdict_keys_must_be_profile_activity_pairs():
    with pytest.raises(ValidationError, match="profile:activity"):
        ReplayHour(
            time=T0,
            observed=ReplayObservation(pm25=150, pm10=260, index=300, band=Band.POOR),
            forecast_hours=[_hour(h) for h in range(1, 13)],
            summary=MSG,
            persistence_pm25=150,
            cams_pm25=110,
            verdicts={"nobody:walk": Verdict.GO},
        )
```

- [ ] **Step 2: Run the tests and confirm they fail:**

```bash
uv run pytest backend/tests/test_schemas.py -q
```

Expected: a collection error, `ModuleNotFoundError: No module named 'backend.schemas'`.

- [ ] **Step 3: Implement `backend/schemas.py`:**

```python
"""BreatheWise API contract.

These pydantic models are the single source of truth. docs/openapi.json and
docs/fixtures/ are generated from them; tests fail if either drifts.
All datetimes are timezone-aware UTC.
"""

from enum import StrEnum
from typing import Literal

from pydantic import (
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


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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
    generated_at: AwareDatetime
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
        return self


class CurrentAqiResponse(Model):
    generated_at: AwareDatetime
    station: Station
    observed_at: AwareDatetime
    source: Source
    stale: bool
    age_minutes: int = Field(ge=0)
    aqi: AqiValue
    hourly_index: int | None = Field(
        default=None, ge=0, le=500, description="Indicative NAQI from the latest hourly PM values"
    )
    hourly_band: Band | None = None
    sub_indices: list[SubIndex]


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
    target_time: AwareDatetime = Field(description="Start of the forecast hour (UTC)")
    horizon_h: int = Field(ge=1, le=12)
    pm25: Quantiles
    pm10: Quantiles
    index: IndexQuantiles
    band: Band = Field(description="Band of index.q50")
    drivers: dict[DriverGroup, float] = Field(
        description="Signed contribution of each driver group to the PM2.5 median, ug/m3"
    )
    explanation: Message


class ForecastResponse(Model):
    generated_at: AwareDatetime
    station_id: str
    issued_at: AwareDatetime
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
        return self


class AdviceRequest(Model):
    profile: Profile
    activity: Activity
    duration_h: int = Field(ge=1, le=12)
    station_id: str | None = Field(default=None, description="Defaults to the venue station")


class BestWindow(Model):
    start: AwareDatetime
    end: AwareDatetime
    worst_index: int = Field(ge=0, le=500)
    band: Band
    improves_on_now: bool

    @model_validator(mode="after")
    def _end_after_start(self) -> "BestWindow":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class AdviceResponse(Model):
    generated_at: AwareDatetime
    station_id: str
    profile: Profile
    activity: Activity
    duration_h: int = Field(ge=1, le=12)
    forecast_issued_at: AwareDatetime
    model_version: str
    stale: bool
    age_minutes: int = Field(ge=0)
    verdict: Verdict
    reason: Message
    advice: list[Message]
    basis: Literal["q50", "q90"] = Field(description="q90 (cautious) for sensitive profiles")
    best_window: BestWindow | None


class ScoreboardPoint(Model):
    target_time: AwareDatetime
    issued_at: AwareDatetime
    horizon_h: int = Field(ge=1, le=12)
    predicted: Quantiles
    actual: float | None = Field(default=None, ge=0)


class HorizonScore(Model):
    horizon_h: int = Field(ge=1, le=12)
    mae: float | None = Field(default=None, ge=0)
    n: int = Field(ge=0)


class ScoreboardResponse(Model):
    generated_at: AwareDatetime
    station_id: str
    model_version: str
    pollutant: Literal["pm25", "pm10"]
    since: AwareDatetime
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
    generated_at: AwareDatetime
    model_version: str
    trained_until: AwareDatetime
    test_start: AwareDatetime
    test_end: AwareDatetime
    pm25: list[HorizonMetrics]
    pm10: list[HorizonMetrics]
    index_category_accuracy: list[CategoryAccuracy]


class RefreshResponse(Model):
    accepted: bool
    retry_after_s: int | None = Field(default=None, ge=0)
    message: Message


class SourceHealth(Model):
    source: Source
    last_success_at: AwareDatetime | None
    last_failure_at: AwareDatetime | None
    last_error: str | None


class StationHealth(Model):
    station_id: str
    last_observation_at: AwareDatetime | None
    last_source: Source | None


class HealthResponse(Model):
    generated_at: AwareDatetime
    status: Literal["ok", "degraded", "down"]
    model_version: str | None
    last_forecast_at: AwareDatetime | None
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
    time: AwareDatetime = Field(description="Issue time of this replay step")
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
    start: AwareDatetime
    end: AwareDatetime
    model_version: str
    hours: list[ReplayHour]


class ErrorResponse(Model):
    error: str
    message: str
```

- [ ] **Step 4: Run the tests and confirm they pass:**

```bash
uv run pytest backend/tests/test_schemas.py -q
```

Expected: `14 passed`.

- [ ] **Step 5: Lint and commit:**

```bash
uv run ruff check . && uv run black --check .
git add backend/schemas.py backend/tests/test_schemas.py
git commit -m "feat(backend): define API contract schemas"
```

---

### Task 3: Deterministic fixture generator and fixtures

**Files:**
- Create: `backend/scripts/make_fixtures.py`, `docs/fixtures/README.md`, `docs/fixtures/**.json` (generated)
- Test: `backend/tests/test_fixtures.py`

**Interfaces:**
- Consumes: everything in `backend.schemas` (Task 2).
- Produces:
  - `FIXTURE_DIR: Path`
  - `build_fixtures() -> dict[str, BaseModel]`, which returns a mapping from a path relative to `docs/fixtures` to a model
  - `dump(model: BaseModel) -> str`
  - Fixture filenames, used by Task 4: `stations.json`, `aqi_current.{fresh,stale,insufficient_data,cams_fallback}.json`, `aqi_forecast.json`, `aqi_forecast.stale.json`, `advice.{go,go_with_n95,avoid,reduce_exposure}.json`, `scoreboard.json`, `metrics.json`, `refresh.accepted.json`, `refresh.rate_limited.json`, `health.json`, `replay/example.json`
  - The string keys `explain.{rising,falling}.{ventilation,recent_buildup,regional_pollution,time_of_day}`, `reason.*`, `advice.*`, `refresh.*`. Phase 3's `strings.yaml` must keep these keys.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_fixtures.py`:

```python
from backend.scripts.make_fixtures import FIXTURE_DIR, build_fixtures, dump

REQUIRED = {
    "stations.json",
    "aqi_current.fresh.json",
    "aqi_current.stale.json",
    "aqi_current.insufficient_data.json",
    "aqi_current.cams_fallback.json",
    "aqi_forecast.json",
    "aqi_forecast.stale.json",
    "advice.go.json",
    "advice.go_with_n95.json",
    "advice.avoid.json",
    "advice.reduce_exposure.json",
    "scoreboard.json",
    "metrics.json",
    "refresh.accepted.json",
    "refresh.rate_limited.json",
    "health.json",
    "replay/example.json",
}
REGEN = "run: uv run python -m backend.scripts.make_fixtures"


def test_generator_covers_every_required_state():
    assert REQUIRED <= set(build_fixtures())


def test_fixture_files_match_generator():
    for name, model in build_fixtures().items():
        path = FIXTURE_DIR / name
        assert path.exists(), f"{name} missing; {REGEN}"
        assert path.read_text(encoding="utf-8") == dump(model), f"{name} is stale; {REGEN}"


def test_no_orphan_fixture_files():
    on_disk = {p.relative_to(FIXTURE_DIR).as_posix() for p in FIXTURE_DIR.rglob("*.json")}
    assert on_disk == set(build_fixtures()), f"orphan fixtures; {REGEN}"


def test_stale_fixtures_are_flagged_stale():
    fixtures = build_fixtures()
    assert fixtures["aqi_current.stale.json"].stale is True
    assert fixtures["aqi_forecast.stale.json"].stale is True
    assert fixtures["aqi_current.fresh.json"].stale is False


def test_advice_fixtures_cover_every_verdict():
    fixtures = build_fixtures()
    expected = {
        "advice.go.json": ("GO", "healthy_adult", "q50"),
        "advice.go_with_n95.json": ("GO_WITH_N95", "healthy_adult", "q50"),
        "advice.avoid.json": ("AVOID", "respiratory", "q90"),
        "advice.reduce_exposure.json": ("REDUCE_EXPOSURE", "outdoor_worker", "q50"),
    }
    for name, (verdict, profile, basis) in expected.items():
        advice = fixtures[name]
        assert advice.verdict.value == verdict, name
        assert advice.basis == basis, name
        assert advice.profile.value == profile, name


def test_scoreboard_mae_ignores_missing_actuals():
    board = build_fixtures()["scoreboard.json"]
    h1 = [p for p in board.points if p.horizon_h == 1]
    assert any(p.actual is None for p in h1)
    assert board.per_horizon[0].n == sum(p.actual is not None for p in h1)
```

- [ ] **Step 2: Run the tests and confirm they fail:**

```bash
uv run pytest backend/tests/test_fixtures.py -q
```

Expected: `ModuleNotFoundError: No module named 'backend.scripts.make_fixtures'`.

- [ ] **Step 3: Implement `backend/scripts/make_fixtures.py`:**

```python
"""Generate contract fixtures in docs/fixtures/ from backend.schemas.

Values are synthetic but realistic for a Delhi October morning, and fully
deterministic (integer arithmetic only), so CI can detect drift.

    uv run python -m backend.scripts.make_fixtures
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

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
    Message,
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
)

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

# Fixture-only PM breakpoints (CPCB NAQI). backend/naqi.py is the real implementation.
Table = tuple[tuple[int, int, int, int], ...]
_PM25: Table = (
    (0, 30, 0, 50),
    (31, 60, 51, 100),
    (61, 90, 101, 200),
    (91, 120, 201, 300),
    (121, 250, 301, 400),
    (251, 380, 401, 500),
)
_PM10: Table = (
    (0, 50, 0, 50),
    (51, 100, 51, 100),
    (101, 250, 101, 200),
    (251, 350, 201, 300),
    (351, 430, 301, 400),
    (431, 510, 401, 500),
)
_BAND_LIMITS = (
    (50, Band.GOOD),
    (100, Band.SATISFACTORY),
    (200, Band.MODERATELY_POLLUTED),
    (300, Band.POOR),
    (400, Band.VERY_POOR),
)
_BAND_ORDER = list(Band)

TEXT = {
    "explain.falling.ventilation": "The model expects {pollutant} to fall, mainly because of "
    "better ventilation (stronger winds and a deeper mixing layer).",
    "explain.rising.ventilation": "The model expects {pollutant} to rise, mainly because of "
    "weaker ventilation (calmer winds and a shallower mixing layer).",
    "explain.falling.recent_buildup": "The model expects {pollutant} to fall, mainly because "
    "the recent build-up is easing.",
    "explain.rising.recent_buildup": "The model expects {pollutant} to rise, mainly because "
    "pollution has been building up over the last few hours.",
    "explain.falling.regional_pollution": "The model expects {pollutant} to fall, mainly "
    "because regional pollution levels are expected to drop.",
    "explain.rising.regional_pollution": "The model expects {pollutant} to rise, mainly "
    "because regional pollution levels are expected to increase.",
    "explain.falling.time_of_day": "The model expects {pollutant} to fall, mainly because of "
    "the usual daytime pattern at this location.",
    "explain.rising.time_of_day": "The model expects {pollutant} to rise, mainly because of "
    "the usual evening pattern at this location.",
    "reason.general.satisfactory": "Air quality is {band}. Normal outdoor activity is fine.",
    "reason.exertion.moderately_polluted": "Air quality is {band}. Hard exercise makes you "
    "breathe in much more air, and more pollution with it.",
    "reason.sensitive.very_poor": "Air quality is {band}. People with {condition} are more "
    "affected at this level.",
    "reason.outdoor_worker.very_poor": "Air quality is {band}. Over a long outdoor shift, "
    "exposure at this level adds up.",
    "advice.go_ahead": "Go ahead. Conditions are fine for this activity.",
    "advice.wear_n95": "Wear a well-fitted N95 mask.",
    "advice.lower_intensity": "Consider a lighter pace or a shorter session.",
    "advice.stay_indoors": "Stay indoors and keep windows closed during peak hours.",
    "advice.n95_if_must": "If you must go out, wear a well-fitted N95 mask.",
    "advice.n95_on_shift": "Wear a well-fitted N95 mask throughout the shift.",
    "advice.indoor_breaks": "Take regular breaks indoors or in a cleaner space.",
    "advice.use_best_window": "Plan your {activity} for {start}-{end} IST, when air is "
    "expected to be cleanest.",
    "refresh.accepted": "Refresh started. New data in about a minute.",
    "refresh.rate_limited": "Data was refreshed recently. Try again in {minutes} min.",
}


def _msg(key: str, **params: str | int | float) -> Message:
    return Message(key=key, params=params, text=TEXT[key].format(**params))


def _sub_index(conc: float, table: Table) -> int:
    c = round(conc)
    for lo, hi, ilo, ihi in table:
        if c <= hi:
            return round(ilo + (ihi - ilo) * (c - lo) / (hi - lo))
    return 500


def _pm_index(pm25: float, pm10: float) -> int:
    return max(_sub_index(pm25, _PM25), _sub_index(pm10, _PM10))


def _band(index: int) -> Band:
    for limit, band in _BAND_LIMITS:
        if index <= limit:
            return band
    return Band.SEVERE


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
        (141.0, 236.0, 128.0, 221.0) if source is Source.CAMS_MODEL else (182.0, 318.0, 164.0, 290.0)
    )
    subs = [
        SubIndex(pollutant=Pollutant.PM25, concentration=pm25_24h, unit="ug_m3",
                 sub_index=_sub_index(pm25_24h, _PM25)),
        SubIndex(pollutant=Pollutant.PM10, concentration=pm10_24h, unit="ug_m3",
                 sub_index=_sub_index(pm10_24h, _PM10)),
        SubIndex(pollutant=Pollutant.NO2, concentration=62.0, unit="ug_m3", sub_index=77),
        SubIndex(pollutant=Pollutant.O3, concentration=38.0, unit="ug_m3", sub_index=38),
        SubIndex(pollutant=Pollutant.CO, concentration=1.4, unit="mg_m3", sub_index=70),
    ]
    if insufficient:
        subs = [s for s in subs if s.pollutant in (Pollutant.PM25, Pollutant.NO2)]
        aqi = AqiValue(status="insufficient_data", pollutants_present=[s.pollutant for s in subs])
        hourly = _sub_index(pm25, _PM25)
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
        Profile.HEALTHY_ADULT, Activity.WALK, 1, 85,
        "reason.general.satisfactory", {"band": "Satisfactory"},
        ["advice.go_ahead"],
    ),
    "go_with_n95": (
        Profile.HEALTHY_ADULT, Activity.RUN_EXERCISE, 1, 160,
        "reason.exertion.moderately_polluted", {"band": "Moderately Polluted"},
        ["advice.wear_n95", "advice.lower_intensity"],
    ),
    "avoid": (
        Profile.RESPIRATORY, Activity.WALK, 2, 348,
        "reason.sensitive.very_poor",
        {"band": "Very Poor", "condition": "respiratory conditions"},
        ["advice.stay_indoors", "advice.n95_if_must"],
    ),
    "reduce_exposure": (
        Profile.OUTDOOR_WORKER, Activity.OUTDOOR_WORK_SHIFT, 8, 348,
        "reason.outdoor_worker.very_poor", {"band": "Very Poor"},
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
        errors = [abs(p.predicted.q50 - p.actual) for p in points
                  if p.horizon_h == h and p.actual is not None]
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
            SourceHealth(source=Source.CPCB, last_success_at=ISSUED_AT - timedelta(hours=2),
                         last_failure_at=ISSUED_AT, last_error="HTTPStatusError 503"),
            SourceHealth(source=Source.OPENAQ, last_success_at=ISSUED_AT,
                         last_failure_at=None, last_error=None),
            SourceHealth(source=Source.CAMS_MODEL, last_success_at=ISSUED_AT,
                         last_failure_at=None, last_error=None),
        ],
        stations=[
            StationHealth(station_id=VENUE.station_id, last_observation_at=OBSERVED_AT,
                          last_source=Source.OPENAQ),
            StationHealth(station_id=OTHER.station_id, last_observation_at=OBSERVED_AT,
                          last_source=Source.OPENAQ),
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
```

- [ ] **Step 4: Format, generate the fixtures, and run the tests:**

```bash
uv run black backend && uv run ruff check . --fix
uv run python -m backend.scripts.make_fixtures
uv run pytest -q
```

Expected: 17 `wrote docs/fixtures/...` lines; all tests pass.

- [ ] **Step 5: Spot-check realism.** Open `docs/fixtures/aqi_forecast.json` and check:
  - h1 `band` is `very_poor`;
  - the minimum falls around h8 in the `poor` band;
  - `drivers.ventilation` is negative while PM falls.

Open `docs/fixtures/advice.avoid.json` and check that `best_window` is 2 h long, lies in the afternoon IST, and that `improves_on_now` is `true`.

Open `docs/fixtures/advice.go.json` and check that `improves_on_now` is `false`; this is the "now is already fine" state.

- [ ] **Step 6: Write `docs/fixtures/README.md`:**

```markdown
# Contract fixtures

Generated from `backend/schemas.py` by `uv run python -m backend.scripts.make_fixtures`.
Do not edit by hand; CI fails if these drift from the schemas.

All values are synthetic (Delhi, event morning 2026-10-10 09:35 IST). Station ids are
illustrative until real stations are chosen.

| File | Endpoint | Data state |
|---|---|---|
| `stations.json` | `GET /stations` | normal |
| `aqi_current.fresh.json` | `GET /aqi/current` | fresh, CPCB |
| `aqi_current.stale.json` | `GET /aqi/current` | stale (185 min old) |
| `aqi_current.insufficient_data.json` | `GET /aqi/current` | < 3 pollutants |
| `aqi_current.cams_fallback.json` | `GET /aqi/current` | all stations down, modelled estimate |
| `aqi_forecast.json` | `GET /aqi/forecast` | fresh |
| `aqi_forecast.stale.json` | `GET /aqi/forecast` | stale (3 h old) |
| `advice.go.json` | `POST /advice` | healthy_adult + walk, GO |
| `advice.go_with_n95.json` | `POST /advice` | healthy_adult + run_exercise, GO_WITH_N95 |
| `advice.avoid.json` | `POST /advice` | respiratory + walk, AVOID (default) |
| `advice.reduce_exposure.json` | `POST /advice` | outdoor_worker + outdoor_work_shift, REDUCE_EXPOSURE |
| `scoreboard.json` | `GET /scoreboard` | 24 h, latest actual missing |
| `metrics.json` | `GET /metrics` | test-window metrics |
| `refresh.accepted.json` | `POST /refresh` | 202 |
| `refresh.rate_limited.json` | `POST /refresh` | 429 |
| `health.json` | `GET /health` | degraded (CPCB failing) |
| `replay/example.json` | bundled in UI | replay episode format |

## Mock server

    uv run uvicorn backend.app:app --reload

Send an `X-Mock-Scenario` header to get a variant; anything else returns the default.

| Endpoint | Scenarios |
|---|---|
| `GET /aqi/current` | `stale`, `insufficient_data`, `cams_fallback` |
| `GET /aqi/forecast` | `stale` |
| `POST /advice` | `go`, `go_with_n95`, `avoid` (default), `reduce_exposure` |
| `POST /refresh` | `rate_limited` |

In mock mode `POST /advice` returns the scenario fixture regardless of the request body.
Advice fixtures are independent scenarios: their reason band is not tied to `aqi_current`.
```

- [ ] **Step 7: Commit:**

```bash
git add backend/scripts/make_fixtures.py backend/tests/test_fixtures.py docs/fixtures
git commit -m "feat(backend): generate contract fixtures for every data state"
```

---

### Task 4: Fixture-backed FastAPI app and OpenAPI export

**Files:**
- Create: `backend/fixture_store.py`, `backend/app.py`, `backend/scripts/export_openapi.py`, `docs/openapi.json` (generated)
- Test: `backend/tests/test_app.py`

**Interfaces:**
- Consumes: `FIXTURE_DIR` and the fixture filenames (Task 3); response models (Task 2).
- Produces:
  - `fixture_store.load(endpoint: str, scenario: str = "default") -> BaseModel`
  - `backend.app:app`, a FastAPI instance. Phase 4 replaces `fixture_store` with the repository layer, keeping the routes and signatures.
  - `export_openapi.render() -> str`

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_app.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.schemas import Verdict
from backend.scripts.export_openapi import OPENAPI_PATH, render

client = TestClient(app)


@pytest.mark.parametrize(
    "path",
    ["/stations", "/aqi/current", "/aqi/forecast", "/scoreboard", "/metrics", "/health"],
)
def test_read_endpoints_return_payload(path):
    response = client.get(path)
    assert response.status_code == 200
    assert "generated_at" in response.json()


def test_mock_scenario_header_selects_stale_variant():
    response = client.get("/aqi/current", headers={"X-Mock-Scenario": "stale"})
    assert response.json()["stale"] is True


def test_unknown_scenario_falls_back_to_default():
    response = client.get("/aqi/current", headers={"X-Mock-Scenario": "nonsense"})
    assert response.status_code == 200
    assert response.json()["stale"] is False


def test_advice_returns_verdict():
    body = {"profile": "respiratory", "activity": "walk", "duration_h": 2}
    response = client.post("/advice", json=body)
    assert response.status_code == 200
    assert response.json()["verdict"] in {v.value for v in Verdict}


@pytest.mark.parametrize(
    "scenario,verdict",
    [
        ("go", "GO"),
        ("go_with_n95", "GO_WITH_N95"),
        ("avoid", "AVOID"),
        ("reduce_exposure", "REDUCE_EXPOSURE"),
    ],
)
def test_advice_scenario_header_selects_verdict(scenario, verdict):
    body = {"profile": "healthy_adult", "activity": "walk", "duration_h": 1}
    response = client.post("/advice", json=body, headers={"X-Mock-Scenario": scenario})
    assert response.json()["verdict"] == verdict


def test_advice_rejects_duration_over_12h():
    body = {"profile": "respiratory", "activity": "walk", "duration_h": 13}
    assert client.post("/advice", json=body).status_code == 422


def test_refresh_accepted_returns_202():
    assert client.post("/refresh").status_code == 202


def test_refresh_rate_limited_returns_429_with_retry_after():
    response = client.post("/refresh", headers={"X-Mock-Scenario": "rate_limited"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(response.json()["retry_after_s"])


def test_cors_allows_local_frontend():
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_openapi_file_is_current():
    expected = render()
    assert Path(OPENAPI_PATH).read_text(encoding="utf-8") == expected, (
        "docs/openapi.json is stale; run: uv run python -m backend.scripts.export_openapi"
    )
```

- [ ] **Step 2: Run the tests and confirm they fail:**

```bash
uv run pytest backend/tests/test_app.py -q
```

Expected: `ModuleNotFoundError: No module named 'backend.app'`.

- [ ] **Step 3: Implement `backend/fixture_store.py`:**

```python
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
```

- [ ] **Step 4: Implement `backend/app.py`:**

```python
"""BreatheWise HTTP API.

Phase 1: routes serve the contract fixtures in docs/fixtures/. The optional
X-Mock-Scenario header selects a variant (stale, insufficient_data, cams_fallback,
rate_limited) so the UI can exercise every data state.
"""

import os
from typing import Annotated

from fastapi import FastAPI, Header, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from backend import fixture_store
from backend.schemas import (
    AdviceRequest,
    AdviceResponse,
    CurrentAqiResponse,
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


@app.get("/stations", response_model=StationsResponse)
def get_stations(
    lat: float | None = None,
    lon: float | None = None,
    radius_km: Annotated[float, Query(gt=0, le=100)] = 25.0,
    scenario: MockScenario = "default",
):
    return fixture_store.load("stations", scenario)


@app.get("/aqi/current", response_model=CurrentAqiResponse)
def get_current_aqi(
    station_id: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    scenario: MockScenario = "default",
):
    return fixture_store.load("aqi_current", scenario)


@app.get("/aqi/forecast", response_model=ForecastResponse)
def get_forecast(station_id: str | None = None, scenario: MockScenario = "default"):
    return fixture_store.load("aqi_forecast", scenario)


@app.post("/advice", response_model=AdviceResponse)
def post_advice(body: AdviceRequest, scenario: MockScenario = "default"):
    return fixture_store.load("advice", scenario)


@app.get("/scoreboard", response_model=ScoreboardResponse)
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
```

- [ ] **Step 5: Implement `backend/scripts/export_openapi.py`:**

```python
"""Write docs/openapi.json from the FastAPI app.

    uv run python -m backend.scripts.export_openapi
"""

import json
from pathlib import Path

from backend.app import app

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    OPENAPI_PATH.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Export, run the tests, and smoke-test the server:**

```bash
uv run python -m backend.scripts.export_openapi
uv run pytest -q
uv run ruff check . && uv run black --check .
```

Expected: all tests pass. Then start `uv run uvicorn backend.app:app --port 8000` in the background and run:

```bash
curl -s -H "X-Mock-Scenario: stale" http://127.0.0.1:8000/aqi/current
```

Expected: JSON containing `"stale":true`. Stop the server.

- [ ] **Step 7: Commit:**

```bash
git add backend/fixture_store.py backend/app.py backend/scripts/export_openapi.py backend/tests/test_app.py docs/openapi.json
git commit -m "feat(backend): serve fixtures from FastAPI mock and export OpenAPI"
```

---

### Task 5: CI, repository process docs and placeholders

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/CODEOWNERS`, `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/task.md`, `.github/ISSUE_TEMPLATE/bug.md`, `README.md`, `CONTRIBUTING.md`, `frontend/README.md`, `infra/README.md`

**Interfaces:**
- Produces: a CI check named `python`, which branch protection requires in Task 6.

- [ ] **Step 1: Write `.github/workflows/ci.yml`:**

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

jobs:
  python:
    name: python
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run black --check .
      - run: uv run pytest -q
      - name: No env files tracked
        run: "! git ls-files | grep -E '(^|/)\\.env$'"

  gitleaks:
    name: gitleaks
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  infra:
    name: infra
    runs-on: ubuntu-latest
    env:
      AWS_DEFAULT_REGION: ap-south-1
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/setup-sam@v2
        if: hashFiles('infra/template.yaml') != ''
        with:
          use-installer: true
      - name: sam validate
        if: hashFiles('infra/template.yaml') != ''
        run: sam validate --lint --template infra/template.yaml
      - name: No template yet
        if: hashFiles('infra/template.yaml') == ''
        run: echo "infra/template.yaml not present yet; skipping"

  frontend:
    name: frontend
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        if: hashFiles('frontend/package.json') != ''
        with:
          node-version: "20"
      - if: hashFiles('frontend/package.json') != ''
        run: npm ci
      - if: hashFiles('frontend/package.json') != ''
        run: npm run lint
      - if: hashFiles('frontend/package.json') != ''
        run: npm run typecheck
      - if: hashFiles('frontend/package.json') != ''
        run: npm run build
      - if: hashFiles('frontend/package.json') == ''
        run: echo "frontend not scaffolded yet; skipping"
        working-directory: .
```

- [ ] **Step 2: Write `.github/CODEOWNERS`:**

```text
# Core system: data, ML, infra, API, docs
*                       @Ayush1860

# Member B
/frontend/              @MEMBER_B
/backend/advisory.py    @MEMBER_B
/backend/rules.yaml     @MEMBER_B
/backend/strings.yaml   @MEMBER_B
```

- [ ] **Step 3: Write `.github/pull_request_template.md`:**

```markdown
## What
<!-- One or two sentences. -->

Closes #

## Why

## Verification
<!-- Paste evidence: test output, curl, CloudWatch screenshot. -->
- [ ] `uv run pytest -q` passes
- [ ] `uv run ruff check . && uv run black --check .` clean
- [ ] Contract unchanged, or fixtures + `docs/openapi.json` regenerated and change is additive
- [ ] No secrets, data dumps or model binaries added

## Reviewer focus
```

- [ ] **Step 4: Write `.github/ISSUE_TEMPLATE/task.md`:**

```markdown
---
name: Task
about: A unit of planned work
labels: []
---

## Goal

## Done when
- [ ]

## Notes
```

and `.github/ISSUE_TEMPLATE/bug.md`:

```markdown
---
name: Bug
about: Something is broken
labels: []
---

## What happened

## Expected

## Steps / evidence
```

- [ ] **Step 5: Write `README.md`:**

````markdown
# BreatheWise

Explainable, personalised air-quality decisions for Delhi: is it safe for *you* to do
*this activity* now, what is the best window in the next 12 hours, and *why* is the air
expected to change.

Built for Environmental Hacks (Bharat Builds, WeMakeDevs x AWS) - Air track.

## Repository

| Path | Contents |
|---|---|
| `backend/` | FastAPI API, NAQI, advisory engine, contract schemas |
| `ingest/` | Source clients and hourly ingest Lambda |
| `ml/` | Forecast model training, evaluation, explanations, replay export |
| `infra/` | AWS SAM template |
| `frontend/` | Web UI |
| `docs/` | Design spec, plans, API contract (`openapi.json`), fixtures |

## Quick start

```bash
uv sync
uv run pytest -q
uv run uvicorn backend.app:app --reload   # mock API on fixtures
```

## Team

| Member | GitHub | Owns |
|---|---|---|
| Ayush Suryawanshi | [@Ayush1860](https://github.com/Ayush1860) | Data, ML, AWS infra, API, replay/scoreboard/accuracy views |
| Member B | [@MEMBER_B](https://github.com/MEMBER_B) | Frontend, advisory engine (rules, strings, best window) |
````

- [ ] **Step 6: Write `CONTRIBUTING.md`:**

```markdown
# Contributing

## Before your first commit
1. `git config user.name` and `git config user.email` must match **your own** GitHub
   account (a verified email). Never commit under another member's identity.
2. `cp .env.example .env` and fill in your own keys. `.env` is never committed.
3. `uv sync` (Python 3.12 is installed automatically by uv).
4. Tool- or editor-specific local config stays local: add it to `.git/info/exclude`,
   not `.gitignore`.

## Workflow
- One feature = one issue = one branch = one PR. Branch: `<initials>/<area>-<short-desc>`
  (e.g. `as/ml-lightgbm-v1`). Use `git worktree` for parallel branches.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`).
  `Co-authored-by:` only for genuine pair work between team members.
- `main` is protected: PR + green CI + 1 approval from the other member. No direct pushes.
- Merge with **rebase** only (`gh pr merge --rebase --delete-branch`), so each member's
  commits keep their author on `main`.
- PR description must include verification evidence (test output, curl, logs).
- Test-first for `naqi.py`, `advisory.py`, the best-window finder, feature engineering and
  API handlers.

## API contract
`backend/schemas.py` is the source of truth. After changing it:

    uv run python -m backend.scripts.make_fixtures
    uv run python -m backend.scripts.export_openapi

Contract changes after Phase 1 must be additive. Breaking changes need agreement from the
frontend owner.

## Cloud
Production runs only in the repo owner's AWS account (`breathewise-prod`). Other members
use fixtures, local runs, or a separately named dev stack (`breathewise-dev-<initials>`).
No `sam deploy` without a reviewed resource list and cost estimate.

## Freeze
No merges to `main` after Friday 2026-10-09 18:00 IST.
```

- [ ] **Step 7: Write the placeholders.** `frontend/README.md`:

```markdown
# Frontend

Built separately. Develop against `docs/fixtures/` or the mock API
(`uv run uvicorn backend.app:app`). The live API base URL arrives in `docs/UI_HANDOFF.md`.
```

and `infra/README.md`:

```markdown
# Infrastructure

AWS SAM template for the `breathewise-prod` stack (added in Phase 5).
```

- [ ] **Step 8: Check for forbidden mentions, then commit.** The search below must print nothing:

```bash
git grep -n -i -E "anthr[o]pic|cl[a]ude" -- . ; echo "exit=$?"
```

The bracketed letters stop this command from matching its own text.

Expected: no matches, then `exit=1`. Then:

```bash
git add .github README.md CONTRIBUTING.md frontend/README.md infra/README.md
git commit -m "chore: add CI, CODEOWNERS, templates and contributor docs"
```

---

### Task 6: Publish to GitHub

Steps 1–3 run right after Task 1. The user approved creating a public repo, pushing, adding labels and inviting B. Steps 4–8 run after Task 5.

**Interfaces:**
- Consumes: the CI checks named `python` and `gitleaks` (Task 5).
- Produces:
  - The public repo `github.com/Ayush1860/breathewise`, with rebase-merge only, secret scanning and push protection.
  - Labels.
  - B invited as a collaborator.
  - Protected `main`.
  - Issues.
  - The Phase 1 PR.

- [ ] **Step 1: Create the public repo and push only the docs commits on `main`:**

```bash
gh auth status
gh repo create Ayush1860/breathewise --public --description "Explainable, personalised air-quality decisions for Delhi"
git remote add origin https://github.com/Ayush1860/breathewise.git
git push -u origin main
```

Expected: `main` on GitHub has only the spec and plan commits. `as/repo-scaffold` stays local.

- [ ] **Step 2: Labels and repo settings.** Allow rebase-merge only, delete branches on merge, and enable secret scanning with push protection:

```bash
for l in ml data infra backend frontend ux demo; do gh label create "$l" --repo Ayush1860/breathewise --force; done
gh repo edit Ayush1860/breathewise --enable-rebase-merge --enable-squash-merge=false --enable-merge-commit=false --delete-branch-on-merge
gh api -X PATCH repos/Ayush1860/breathewise --input - <<'JSON'
{"security_and_analysis": {"secret_scanning": {"status": "enabled"},
                           "secret_scanning_push_protection": {"status": "enabled"}}}
JSON
gh api repos/Ayush1860/breathewise --jq '{rebase: .allow_rebase_merge, squash: .allow_squash_merge, merge: .allow_merge_commit, ss: .security_and_analysis.secret_scanning.status, pp: .security_and_analysis.secret_scanning_push_protection.status}'
```

Expected: `{"merge":false,"pp":"enabled","rebase":true,"squash":false,"ss":"enabled"}`.

- [ ] **Step 3: Invite Member B** (handle supplied by the user):

```bash
gh api -X PUT repos/Ayush1860/breathewise/collaborators/MEMBER_B -f permission=push
```

- [ ] **Step 4: Protect `main`** (after Task 5's CI is on the branch). Require PRs, the `python` and `gitleaks` checks, 0 approvals for now, and enforce the rules for admins too:

```bash
gh api -X PUT repos/Ayush1860/breathewise/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["python", "gitleaks"]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
gh api repos/Ayush1860/breathewise/branches/main/protection --jq '.required_status_checks.contexts'
```

Expected: `["python","gitleaks"]`.

- [ ] **Step 5: Create the issues.** Use one command per row:

```bash
gh issue create --repo Ayush1860/breathewise --assignee <assignee> --label <labels> --title "<title>" --body "<Goal + Done when, from the spec section>"
```

| Title | Labels | Assignee |
|---|---|---|
| Scaffold repo, CI and API contract (Phase 1) | backend | Ayush1860 |
| Sample sources (G3) and choose Delhi stations by coverage | data | Ayush1860 |
| naqi.py with CPCB breakpoint cross-check | backend | Ayush1860 |
| Lambda packaging probe for lightgbm (G1) | infra, ml | Ayush1860 |
| SAM stack: ingest Lambda, DynamoDB, S3, scheduler, baseline forecast | infra | Ayush1860 |
| Archived forecast vs reanalysis check (G2) | ml, data | Ayush1860 |
| LightGBM v1 with quantiles, TreeSHAP groups and metrics | ml | Ayush1860 |
| advisory.py, rules, strings and best-window finder | backend | MEMBER_B |
| API on DynamoDB behind CloudFront with refresh and health | backend, infra | Ayush1860 |
| UI_HANDOFF.md (due Thu 12:00 IST) | ux, demo | Ayush1860 |
| Replay episode export | ml, demo | Ayush1860 |
| Failure simulation, smoke load test, warm-up toggle | demo, infra | Ayush1860 |
| UI: design direction and foundations | frontend, ux | MEMBER_B |
| UI: setup flow, home dashboard and data states | frontend, ux | MEMBER_B |
| UI: replay, scoreboard and accuracy views (data viz) | frontend | Ayush1860 |
| UI: presenter and audience modes | frontend, demo | MEMBER_B |
| UI: wire live API and deploy on Amplify | frontend, infra | MEMBER_B |
| UI: quality pass (a11y, performance, offline) | frontend, ux | MEMBER_B |

If B has not accepted the invite yet, GitHub rejects B as an assignee. In that case, create B's issues unassigned and assign them after B accepts.

- [ ] **Step 6: Push the branch and open the PR:**

```bash
git switch as/repo-scaffold
git push -u origin as/repo-scaffold
gh pr create --base main --title "chore: scaffold repo, CI and API contract" --body-file -
```

The body follows the PR template, closes the Phase 1 issue, and pastes the `pytest` output as evidence.

- [ ] **Step 7: Wait for green CI and review.** Run the code-review skill on the PR diff and address the findings. Then merge and pull:

```bash
gh pr merge --rebase --delete-branch
git switch main && git pull --ff-only
```

- [ ] **Step 8: Require B's approval once B has accepted the invite.** Check with:

```bash
gh api repos/Ayush1860/breathewise/collaborators/MEMBER_B --silent && echo accepted
```

Then raise the required approvals to 1:

```bash
gh api -X PATCH repos/Ayush1860/breathewise/branches/main/protection/required_pull_request_reviews -F required_approving_review_count=1
```

Until that has happened, report "approval rule pending B" in the phase exit.

- [ ] **Step 9: Phase 1 exit.** Report to the user:
  - CI run link;
  - test count;
  - fixture list;
  - repo settings evidence;
  - the instructions for B: clone, then `uv run uvicorn backend.app:app`, then `X-Mock-Scenario`.

  Then STOP for "continue".
