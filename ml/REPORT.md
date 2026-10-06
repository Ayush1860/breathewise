# BreatheWise forecast model: report

**Status:** pipeline built and tested on synthetic data. Weather/CAMS history has been pulled. The observation history pull and the training run are waiting on the OpenAQ API key. Sections marked *(after training run)* get filled in by `python -m ml.train --city delhi`.

## 1. Task
Forecast hourly **PM2.5 and PM10** at t+1 … t+12 for each Delhi station, with an 80 % band (q10–q90). The forecasts are converted to the NAQI hourly index for advice and best-window search.

## 2. Data

| Source | Use | Window | Coverage |
|---|---|---|---|
| OpenAQ v3 / CPCB (station observations) | Targets, lags | 2024-02 → 2026-10 | *(after pull)* |
| Open-Meteo Historical Forecast API | Weather analysis at issue time t | 2024-02 → 2026-10 | 100 % except BLH: 78 % (missing 2024-02-01 → 2024-09-01, present for the whole test window) |
| Open-Meteo Previous Runs API (`*_previous_day1`) | Weather **forecast** valid at t+h, issued ≥ 24 h before | 2024-02 → 2026-10 | 100 % |
| Open-Meteo Air Quality (CAMS) | Regional pollution at t | 2024-02 → 2026-10 | 100 % |

Stations (provisional; final choice by measured coverage): Rohini (venue default, about 2 km from DTU), Bawana, Anand Vihar.

**Gaps:** gaps of 3 h or less are linearly interpolated. Longer gaps stay NaN; LightGBM routes NaN natively. Issue hours without a full 24 h lag history, and target hours without an observation, are excluded from training and evaluation.

## 3. Leakage audit (G2)
Archived forecasts were checked against real responses on 2026-10-06 (`docs/sources.md`).

| Feature family | Source timestamp | Max lookahead past issue time t | Notes |
|---|---|---|---|
| Target lags `lag0…lag23`, `other_lag0` | ≤ t | 0 | |
| Rolling mean/std 3/6/24 h | window ending at t | 0 | NaN-aware |
| `wx_u, wx_v, wx_blh, wx_temp, wx_rh, wx_precip, wx_pressure` | analysis at t | 0 | |
| `fc_u, fc_v, fc_temp, fc_rh, fc_precip` | forecast **valid at t+h**, issued ≥ 24 h before t+h | 0 (issued before t for h ≤ 24) | Training uses the day-ahead runs; live uses fresher runs (favourable skew) |
| BLH at t+h | not used | n/a | No archived BLH forecast exists |
| `cams_pm25_t, cams_pm10_t` | CAMS at t | 0 | No archived CAMS forecasts, so CAMS is used at issue time only |
| Time features | target hour t+h | n/a | Deterministic calendar |

`ml/tests/test_features.py::test_no_feature_reads_after_issue_time_except_forecast_at_target` overwrites every post-issue value (except the forecast valid at t+h) and asserts the features are unchanged. The Historical Forecast API stitches successive runs, so its values after t are never used.

## 4. Model
- **Direct multi-horizon:** one LightGBM model per (pollutant, horizon, quantile): 2 × 12 × 3 = 72 models, quantile objective with α ∈ {0.1, 0.5, 0.9}.
  - Why per-horizon rather than a single model with a horizon feature: the drivers differ by lead time (lags dominate at h=1, ventilation and the time of day at h≥6). Per-horizon models keep that explicit, make the leakage reasoning simple, and each trains in seconds.
- **Post-processing:** quantiles are sorted per hour (no crossing) and clipped at 0.
- **Explainability:** exact TreeSHAP via LightGBM `predict(pred_contrib=True)` on the q=0.5 models, summed into driver groups:
  - ventilation (wind u/v, BLH, weather analysis and forecast);
  - recent build-up (lags, rolling);
  - regional pollution (CAMS);
  - time-of-day pattern (calendar, festivals).

  The station identity's contribution is folded into the baseline. Contributions are relative to the station's typical level. Explanation templates say "the model expects … mainly because …" and never claim causation.

## 5. Evaluation protocol
- **Train** ≤ 2025-10-05 23:59 IST. **Test**: 2025-10-06 → 2025-12-31 IST (post-monsoon and stubble-burning season, the same regime as the event). The monsoon months are deliberately not the test window, and the replay episodes come from the test window only.
- **Baselines:**
  - persistence: y(t+h) = y(t);
  - raw CAMS: CAMS at t carried forward, the only leakage-free CAMS baseline since no archived CAMS forecasts exist.
- **Metrics:** MAE and RMSE per horizon, [q10, q90] coverage, NAQI-category accuracy (model vs persistence), written to `metrics.json` (served by `/metrics`).
- **Production model:** retrained on all data with the same settings. The evaluation model is kept as `…/eval` for the replays.

## 6. Results *(after training run)*
Per-horizon table, comparison against the baselines, coverage, feature importance by group, and replay episode choices.

## 7. Known limitations
- Observation history depends on OpenAQ/CPCB availability; station coverage is reported per station.
- Live weather forecasts are fresher than the day-ahead runs used in training, so live accuracy at short leads may be slightly better than reported.
- Only PM is forecast; the forecast index is PM-based (`basis: "pm_only"`).
