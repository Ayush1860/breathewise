# UI Handoff: BreatheWise API

This doc covers everything the frontend needs from the core system. The machine-readable contract is [`docs/openapi.json`](openapi.json). **If this doc and the OpenAPI disagree, the OpenAPI wins.** Example payloads are in [`docs/fixtures/`](fixtures/); every one of them validates against the schemas in CI.

> Status: written against the fixtures and the mock server. The **live base URL** and real example responses are added after the first deploy (see "Base URL").

## Base URL

| Environment | Base URL |
|---|---|
| Local mock (fixtures) | `http://127.0.0.1:8000`; run `uv sync` then `uv run uvicorn backend.app:app --reload` |
| Live (CloudFront) | *added after deploy* (stack output `ApiUrl`) |

CORS allows `http://localhost:5173` and `http://localhost:3000`. The Amplify domain is added at deploy time (send it over when you have it).

All times are **UTC ISO-8601 with `Z`**. Convert to IST (UTC+5:30) for display.

## Data states the UI must handle

| State | How you detect it | Suggested UI |
|---|---|---|
| Loading | Request in flight | Skeleton |
| Fresh | `stale: false` | Normal, plus "updated X min ago" from `age_minutes` |
| Stale | `stale: true` (observations older than 3 h, forecast older than 2 h) | Amber banner, e.g. "Last updated 3 h ago; live sources are delayed" |
| Insufficient data | `aqi.status == "insufficient_data"` (`aqi`, `band`, `dominant_pollutant` are `null`) | Show `hourly_index` / `hourly_band` as "indicative", explain that fewer than 3 pollutants were reported |
| Source fallback | `source == "cams_model"` | Label it "modelled estimate (CAMS)", not "measured" |
| Other sources | `source == "cpcb"` / `"openaq"` | "Measured at {station.name}" |
| Refresh rate-limited | `POST /refresh` returns **429** with `Retry-After`, `retry_after_s` and `message` | Disable the button, count down |
| No data yet | **503** `{"error": "no_data", ...}` | Empty state; retry with backoff |
| Advisory unavailable | **503** `{"error": "advisory_unavailable", ...}` on `/advice` | Hide the verdict card, keep the forecast |
| Unknown station | **404** `{"error": "not_found", ...}` | Fall back to the default station |
| Offline | Network error | Replay mode (bundled replay JSON) still works |

Every error body has the shape `{"error": "<code>", "message": "<text>"}`.

### Simulating states locally
Send the header `X-Mock-Scenario` to the mock server. The live API ignores it.

| Endpoint | Scenarios |
|---|---|
| `GET /aqi/current` | `stale`, `insufficient_data`, `cams_fallback` |
| `GET /aqi/forecast` | `stale` |
| `POST /advice` | `go`, `go_with_n95`, `avoid` (default), `reduce_exposure` |
| `POST /refresh` | `rate_limited` |

## Endpoints

| Method + path | Purpose | Cache (CloudFront) | Fixture |
|---|---|---|---|
| `GET /stations?lat&lon&radius_km` | Stations, nearest first, with `distance_km` | 300 s | `stations.json` |
| `GET /aqi/current?station_id` or `?lat&lon` | Current AQI. No params = venue station (DTU, nearest: Rohini). With lat/lon: nearest station + `station.distance_km` | 60 s | `aqi_current.*.json` |
| `GET /aqi/forecast?station_id` | 12-hour forecast with bands, drivers, explanations | 60 s | `aqi_forecast*.json` |
| `POST /advice` | Personal verdict + best window | none | `advice.*.json` |
| `GET /scoreboard?station_id&model_version&pollutant=pm25\|pm10` | Past forecasts vs actuals, MAE per horizon | 300 s | `scoreboard.json` |
| `GET /metrics` | Model accuracy on the held-out test window | 300 s | `metrics.json` |
| `POST /refresh` | Ask for a fresh ingest (global limit: once per 5 min) | none | `refresh.*.json` |
| `GET /health` | Source and pipeline status (for a status pill / presenter mode) | none | `health.json` |

### `GET /aqi/current`
- `aqi` follows the official CPCB method (24 h means; max 8 h means for O3/CO). It is the **headline number**.
- `hourly_index` / `hourly_band` apply the NAQI breakpoints to the latest hourly PM values. Treat it as an **indicative nowcast**, useful for "right now".
- `observed_at` is the end of the latest measured hour. CPCB lags 1–2 h, which is normal.
- `sub_indices[]` gives the concentration, unit (`ug_m3`, or `mg_m3` for CO) and sub-index per pollutant.

### `GET /aqi/forecast`
- `hours[]` has exactly 12 entries, `horizon_h` 1…12. `target_time` is the **start** of the forecast hour.
- `pm25` / `pm10`: concentration quantiles `q10 ≤ q50 ≤ q90` in µg/m³. Draw `q50` as the line and `q10`–`q90` as the band.
- `index`: PM-based hourly NAQI index at each quantile. `band` is the band of `index.q50`. Colour by `band`.
- `basis: "pm_only"`: only PM2.5 and PM10 are forecast. In Delhi, PM dominates nearly every hour.
- `drivers`: signed contributions to the PM2.5 median, in µg/m³, per group:

  | Key | Label |
  |---|---|
  | `ventilation` | Wind & mixing |
  | `recent_buildup` | Recent build-up |
  | `regional_pollution` | Regional pollution |
  | `time_of_day` | Time-of-day pattern |
  | `upwind_fires` | Upwind fires (stretch; may be absent) |

  Positive pushes PM2.5 up, negative pushes it down. Contributions are relative to the station's typical level. The Day-1 baseline model only returns `regional_pollution`.
- `explanation` / `summary`: a `Message`; see "Strings" below.
- `model_version`: `baseline-camsbias-v0` on Day 1, then `lgbm-v1-<sha>`. Show it small, e.g. in presenter mode.

### `POST /advice`
Request:
```json
{"profile": "respiratory", "activity": "walk", "duration_h": 2, "station_id": null}
```
- `profile` is one of `healthy_adult`, `respiratory`, `heart`, `child`, `elderly`, `pregnant`, `outdoor_worker`.
- `activity` is one of `walk`, `run_exercise`, `cycling_commute`, `two_wheeler_commute`, `kids_outdoor_play`, `outdoor_work_shift`.
- `duration_h` is 1–12. A null `station_id` means the venue station.

Response fields:
- `verdict`: one of `GO`, `GO_WITH_N95`, `AVOID`, `REDUCE_EXPOSURE`.
- `reason`: a `Message`.
- `advice[]`: a list of `Message`s.
- `basis`: `q90` (cautious) for sensitive profiles, otherwise `q50`.
- `best_window`: `{start, end, worst_index, band, improves_on_now}`. When `improves_on_now` is `false`, now is already as good as it gets; say so instead of suggesting a wait.

### `GET /scoreboard`
- `points[]` covers the last 48 h: `{target_time, issued_at, horizon_h, predicted{q10,q50,q90}, actual|null}`.
  - `actual` is `null` until the observation arrives.
  - Suggested chart: actual line vs the h=3 / h=6 / h=12 forecasts.
- `per_horizon[]`: `{horizon_h, mae|null, n}` over up to 7 days "since launch". Show `n` honestly; it's small in the first days.
- It never mixes model versions. `model_version` defaults to the current model.

### `GET /metrics`
- `pm25[]` / `pm10[]`: per horizon `{mae, rmse, mae_persistence, mae_cams, interval_coverage}`, from the held-out test window `test_start`…`test_end` (Oct–Dec 2025).
- `index_category_accuracy[]`: `{horizon_h, accuracy, accuracy_persistence}`.
- Headline idea: "At 6 h ahead the model's error is X µg/m³ vs Y for 'assume nothing changes'."

### `POST /refresh`
- **202** with `message`, or **429** with `Retry-After` header, `retry_after_s` and `message`.
- New data shows up about a minute later. Poll `/aqi/current` once.

## Strings
Every user-facing text is a `Message`:
```json
{"key": "explain.falling.ventilation", "params": {"pollutant": "PM2.5"}, "text": "The model expects PM2.5 to fall, mainly because of better ventilation (stronger winds and a deeper mixing layer)."}
```
- `key` is stable. Use it for icons and styling, and later for translation.
- `text` is rendered English, ready to display.

| Key pattern | Meaning |
|---|---|
| `explain.{rising\|falling}.{ventilation\|recent_buildup\|regional_pollution\|time_of_day}` | Forecast explanation (core-owned, `backend/text.py`) |
| `reason.*`, `advice.*` | Advisory reasons and protection advice (advisory engine, `backend/strings.yaml`) |
| `refresh.accepted`, `refresh.rate_limited` | Refresh feedback |

Explanations never claim causation. They describe what the *model* expects.

## Replay episodes (offline demo)
- Bundle `docs/fixtures/replay/*.json` in the app. The schema is `ReplayEpisode` in the OpenAPI components.
- `episode_id`, `title`, `station`, `start`, `end`, `model_version`.
- `hours[]`: one entry per replay step (issue time `time`), each with:
  - `observed {pm25, pm10, index, band}`: what actually happened at that hour;
  - `forecast_hours[12]`: same shape as `/aqi/forecast` hours;
  - `summary`;
  - `persistence_pm25` and `cams_pm25`: baselines for comparison;
  - `verdicts`: `{"<profile>:<activity>": "<VERDICT>"}` for every combination.
- `example.json` is synthetic, to show the format. Real episodes from the Oct–Dec 2025 test window replace it.

## Known limitations
- The station list is provisional until real coverage is measured. The venue default is the nearest good station to DTU; `distance_km` is always shown.
- When CPCB and OpenAQ are both down, the current reading falls back to CAMS (modelled). The UI must label it.
- Forecasts cover PM2.5 and PM10 only.
- The scoreboard history starts at deploy time (a few days by the event).
- Forecast weather inputs: training used day-ahead forecasts (archived from 2024-02), while live uses fresher forecasts. Boundary-layer height and CAMS are used at issue time only (no archived forecasts exist; see `docs/sources.md`).
