# Data sources

These shapes were verified against real responses on 2026-10-06. Redacted samples are in `ingest/tests/samples/`.

## Open-Meteo weather (no key)
- **Endpoint:** `GET https://api.open-meteo.com/v1/forecast`
- **Request:** `hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,boundary_layer_height,precipitation,surface_pressure`, `past_days`, `forecast_days`, `timezone=UTC`.
- **Response:**
  - `utc_offset_seconds: 0`.
  - `hourly.time[]` holds naive ISO strings in UTC.
  - Each variable is a parallel array that may contain `null`.
  - Units are in `hourly_units`; wind defaults to `km/h`, and the parser converts it to m/s.
- **Grid snapping:** the query 28.75 N, 77.117 E (DTU) returns 28.787 N, 77.143 E.

## Open-Meteo air quality / CAMS (no key)
- **Endpoint:** `GET https://air-quality-api.open-meteo.com/v1/air-quality`
- **Request:** `hourly=pm2_5,pm10,nitrogen_dioxide,ozone,carbon_monoxide,sulphur_dioxide`, `timezone=UTC`.
- **Units:** everything is in µg/m³, **including CO**. The parser divides CO by 1000 to get mg/m³, the unit NAQI uses.
- **History:** a past `start_date`/`end_date` works back to at least 2023-01 (CAMS global).
- **Grid snapping:** the query 28.75 N, 77.117 E returns 28.80 N, 77.10 E.

## G2 — archived forecasts vs reanalysis (spec §5)

| Family | Archived *forecast* available? | Evidence | Feature policy |
|---|---|---|---|
| Wind speed/direction, temperature, RH, precipitation, surface pressure | **Yes, from about 2024-02.** Previous Runs API `*_previous_day1` (a run issued at least 24 h before the target) | 2024-03 to 2025-06 complete; 2023 and 2024-01 empty | Use `*_previous_day1` at t+h for training (issued ≤ t for h ≤ 24, so no leakage). Production uses the live forecast at t+h. The skew is in the favourable direction: live leads are shorter and more accurate. |
| Boundary-layer height | **No.** `boundary_layer_height_previous_day1` is always null | 2023 to 2025 | **Issue time t only.** Use the Historical Forecast API value at t (a short-lead stitched forecast, ≈ analysis). |
| CAMS PM2.5/PM10 | **No.** `pm2_5_previous_day1` is always null | 2025-11 | **Issue time t only.** Use CAMS at t. |

The Historical Forecast API stitches the first hours of successive runs. A value at t+h therefore comes from a run issued *after* t, so it is **never** used for t+h features.

**Consequence for the training window:** wind and weather forecast features exist only from about 2024-02. So training runs from 2024-02 to 2025-10-05 (including the 2024–25 winter), and the test window is 2025-10-06 to 2025-12-31.

## CPCB (data.gov.in) and OpenAQ v3
Pending: API keys are needed for samples.
