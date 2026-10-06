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
