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
| Member B | joining | Frontend, advisory engine (rules, strings, best window) |
