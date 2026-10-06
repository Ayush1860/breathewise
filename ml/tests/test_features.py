from datetime import UTC, datetime

import numpy as np
import pytest

from ml.features import (
    FEATURE_GROUPS,
    StationSeries,
    feature_names,
    impute_short_gaps,
    issue_features,
    training_rows,
    wind_uv,
)

N = 24 * 10
START = datetime(2025, 11, 1, tzinfo=UTC)


def series(seed=0, n=N):
    rng = np.random.default_rng(seed)
    times = np.datetime64("2025-11-01T00", "h") + np.arange(n).astype("timedelta64[h]")
    pm25 = 150 + 30 * np.sin(np.arange(n) / 4) + rng.normal(0, 5, n)
    weather = {k: rng.normal(size=n) for k in ("u", "v", "blh", "temp", "rh", "precip", "pressure")}
    forecast = {k: rng.normal(size=n) for k in ("u", "v", "temp", "rh", "precip")}
    return StationSeries(
        station_code=1,
        time=times,
        pm25=pm25,
        pm10=pm25 * 1.7,
        weather=weather,
        weather_forecast=forecast,
        cams_pm25=pm25 * 0.8,
        cams_pm10=pm25 * 1.3,
    )


def test_wind_uv_meteorological_convention():
    u, v = wind_uv(np.array([10.0, 10.0]), np.array([0.0, 90.0]))
    # wind FROM north blows southward (v < 0); FROM east blows westward (u < 0)
    assert u[0] == pytest.approx(0.0, abs=1e-9) and v[0] == pytest.approx(-10.0)
    assert u[1] == pytest.approx(-10.0) and v[1] == pytest.approx(0.0, abs=1e-9)


def test_impute_fills_gaps_up_to_three_hours_only():
    x = np.array([1.0, np.nan, np.nan, 4.0, np.nan, np.nan, np.nan, np.nan, 9.0])
    filled = impute_short_gaps(x, max_gap=3)
    assert filled[:4].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert np.isnan(filled[4:8]).all()


def test_feature_vector_matches_names_and_groups():
    s = series()
    row = issue_features(s, t=100, horizon=3, pollutant="pm25")
    names = feature_names("pm25")
    assert row.shape == (len(names),)
    grouped = {n for names_ in FEATURE_GROUPS.values() for n in names_}
    assert set(names) <= grouped | {"station"}


def test_no_feature_reads_after_issue_time_except_forecast_at_target():
    s = series()
    t, h = 120, 6
    base = issue_features(s, t, h, "pm25")
    future = series()
    for arr in (future.pm25, future.pm10, future.cams_pm25, future.cams_pm10):
        arr[t + 1 :] = 9999.0
    for arr in future.weather.values():
        arr[t + 1 :] = 9999.0
    for arr in future.weather_forecast.values():
        arr[t + 1 : t + h] = 9999.0
        arr[t + h + 1 :] = 9999.0
    np.testing.assert_array_equal(base, issue_features(future, t, h, "pm25"))


def test_forecast_feature_uses_target_hour():
    s = series()
    t, h = 120, 6
    names = feature_names("pm25")
    row = issue_features(s, t, h, "pm25")
    assert row[names.index("fc_u")] == pytest.approx(s.weather_forecast["u"][t + h])


def test_lag_and_rolling_values():
    s = series()
    t = 100
    names = feature_names("pm25")
    row = issue_features(s, t, 1, "pm25")
    assert row[names.index("lag0")] == pytest.approx(s.pm25[t])
    assert row[names.index("lag23")] == pytest.approx(s.pm25[t - 23])
    assert row[names.index("roll_mean_24")] == pytest.approx(s.pm25[t - 23 : t + 1].mean())


def test_training_rows_targets_and_skips_missing():
    s = series()
    s.pm25[150] = np.nan  # a missing target hour is skipped
    X, y, issue_times = training_rows(s, horizon=2, pollutant="pm25")
    assert X.shape[1] == len(feature_names("pm25"))
    assert len(X) == len(y) == len(issue_times)
    first_t = 23
    assert y[0] == pytest.approx(s.pm25[first_t + 2])
    assert np.datetime64(issue_times[0], "h") == s.time[first_t]
    assert not np.isnan(y).any()
    assert s.time[148] not in set(issue_times.astype("datetime64[h]"))
