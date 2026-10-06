"""Test-window evaluation: MAE/RMSE per horizon vs persistence and raw CAMS, interval
coverage, and NAQI-category accuracy. Output matches the /metrics contract."""

from collections.abc import Sequence
from datetime import datetime

import numpy as np

from backend.naqi import hourly_pm_index
from backend.schemas import CategoryAccuracy, HorizonMetrics, MetricsResponse, band_for_index
from ml.features import StationSeries, feature_names, training_rows
from ml.model import POLLUTANTS, QUANTILES, ForecastModel


def _predict_rows(model: ForecastModel, X: np.ndarray, pollutant: str, h: int) -> np.ndarray:
    raw = np.column_stack([model.boosters[(pollutant, h, q)].predict(X) for q in QUANTILES])
    return np.clip(np.sort(raw, axis=1), 0, None)


def _band_codes(pm25: np.ndarray, pm10: np.ndarray) -> list[str]:
    return [band_for_index(hourly_pm_index(a, b)).value for a, b in zip(pm25, pm10, strict=True)]


def evaluate(
    model: ForecastModel,
    test_series: Sequence[StationSeries],
    trained_until: datetime,
    test_start: datetime,
    test_end: datetime,
    generated_at: datetime,
) -> MetricsResponse:
    per_pollutant: dict[str, list[HorizonMetrics]] = {p: [] for p in POLLUTANTS}
    categories: list[CategoryAccuracy] = []
    for h in model.horizons:
        joined: dict[str, dict] = {}
        for p in POLLUTANTS:
            names = feature_names(p)
            truth, pred, persist, cams, times = [], [], [], [], []
            for s in test_series:
                X, y, t = training_rows(s, h, p)
                truth.append(y)
                pred.append(_predict_rows(model, X, p, h))
                persist.append(X[:, names.index("lag0")])
                cams.append(X[:, names.index(f"cams_{p}_t")])
                times.append([(s.station_code, ti) for ti in t.astype("datetime64[h]").tolist()])
            y, q = np.concatenate(truth), np.vstack(pred)
            lag0, cam = np.concatenate(persist), np.concatenate(cams)
            err = q[:, 1] - y
            ok_p, ok_c = ~np.isnan(lag0), ~np.isnan(cam)
            per_pollutant[p].append(
                HorizonMetrics(
                    horizon_h=h,
                    mae=round(float(np.mean(np.abs(err))), 2),
                    rmse=round(float(np.sqrt(np.mean(err**2))), 2),
                    mae_persistence=round(float(np.mean(np.abs(lag0[ok_p] - y[ok_p]))), 2),
                    mae_cams=round(float(np.mean(np.abs(cam[ok_c] - y[ok_c]))), 2),
                    interval_coverage=round(float(np.mean((y >= q[:, 0]) & (y <= q[:, 2]))), 3),
                )
            )
            keys = [k for chunk in times for k in chunk]
            joined[p] = {k: (y[i], q[i, 1], lag0[i]) for i, k in enumerate(keys)}
        common = [k for k in joined["pm25"] if k in joined["pm10"]]
        rows = [(joined["pm25"][k], joined["pm10"][k]) for k in common]
        rows = [(a, b) for a, b in rows if not (np.isnan(a[2]) or np.isnan(b[2]))]
        if rows:
            actual = _band_codes([a[0] for a, _ in rows], [b[0] for _, b in rows])
            predicted = _band_codes([a[1] for a, _ in rows], [b[1] for _, b in rows])
            persisted = _band_codes([a[2] for a, _ in rows], [b[2] for _, b in rows])
            categories.append(
                CategoryAccuracy(
                    horizon_h=h,
                    accuracy=round(float(np.mean(np.array(actual) == np.array(predicted))), 3),
                    accuracy_persistence=round(
                        float(np.mean(np.array(actual) == np.array(persisted))), 3
                    ),
                )
            )
    return MetricsResponse(
        generated_at=generated_at,
        model_version=model.model_version,
        trained_until=trained_until,
        test_start=test_start,
        test_end=test_end,
        pm25=per_pollutant["pm25"],
        pm10=per_pollutant["pm10"],
        index_category_accuracy=categories,
    )
