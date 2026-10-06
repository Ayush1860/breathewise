# Advisory engine: integration interface

Owner: member B (`backend/advisory.py`, `backend/rules.yaml`, `backend/strings.yaml`).
The API (`POST /advice`) and the replay export call into this module. Until it exists, `/advice` returns 503 `advisory_unavailable` in live mode, and replay verdicts stay empty.

## Functions the core calls

```python
from datetime import datetime
from backend.schemas import (
    Activity, AdviceRequest, AdviceResponse, CurrentAqiResponse, ForecastResponse, Profile, Verdict,
)

def advise(
    request: AdviceRequest,              # profile, activity, duration_h, station_id
    forecast: ForecastResponse,          # 12 h, with index.q10/q50/q90 per hour
    current: CurrentAqiResponse | None,  # None if the station has no observations yet
    now: datetime,                       # UTC
) -> AdviceResponse: ...

def verdict(index: int, profile: Profile, activity: Activity) -> Verdict: ...
```

## Rules the core relies on
- `advise` must return a valid `AdviceResponse`:
  - copy `station_id`, `profile`, `activity` and `duration_h` from the request;
  - copy `forecast_issued_at`, `model_version`, `stale` and `age_minutes` from the forecast;
  - set `generated_at = now`.
- "Now" for the verdict:
  - use `current.hourly_index` when present;
  - otherwise use `forecast.hours[0].index`, at q90 for sensitive profiles and q50 otherwise.
- Best window:
  - consider the contiguous `duration_h`-hour window in `forecast.hours` whose worst hourly index is lowest;
  - use q90 for sensitive profiles (`basis = "q90"`) and q50 otherwise (`basis = "q50"`);
  - ties go to the earliest window;
  - `start` is the first hour's `target_time` and `end` is the last hour's `target_time + 1 h`;
  - set `improves_on_now` to whether the window's worst index is below the "now" index.
- `reason` and `advice[]` are `Message(key, params, text)`. Keys live in `strings.yaml`, and the fixture keys (`reason.*` and `advice.*` in `backend/text.py`) must keep working: move them into `strings.yaml` rather than renaming them.
- `verdict` is a pure function used per replay hour for all 42 profile × activity combinations.
- Keep everything deterministic, with no network or AWS calls. It runs inside the API Lambda (only pydantic, fastapi and the standard library are available, plus `pyyaml` once it's added to the common layer in `infra/scripts/build.py`).

## Tests the core will run against it
- `POST /advice` in live mode (`backend/tests/test_app_live.py`) once `advise` exists.
- The replay export calls `verdict` for each hour.
