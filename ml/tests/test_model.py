import numpy as np
import pytest

from ml.features import StationSeries
from ml.model import QUANTILES, ForecastModel, train

HORIZONS = (1, 3, 6)


def synthetic(seed=0, n=24 * 120, code=0):
    """PM2.5 that falls when (forecast) wind is strong: a learnable ventilation signal."""
    rng = np.random.default_rng(seed)
    times = np.datetime64("2025-01-01T00", "h") + np.arange(n).astype("timedelta64[h]")
    wind = 3 + 2 * np.sin(np.arange(n) / 9) + rng.normal(0, 0.3, n)
    pm25 = np.empty(n)
    pm25[0] = 150
    for i in range(1, n):
        pm25[i] = 0.8 * pm25[i - 1] + 0.2 * (220 - 35 * wind[i]) + rng.normal(0, 4)
    weather = {k: rng.normal(size=n) for k in ("blh", "temp", "rh", "precip", "pressure")}
    weather["u"], weather["v"] = wind, np.zeros(n)
    forecast = {k: rng.normal(size=n) for k in ("temp", "rh", "precip")}
    forecast["u"], forecast["v"] = wind + rng.normal(0, 0.2, n), np.zeros(n)
    return StationSeries(code, times, pm25, pm25 * 1.6, weather, forecast, pm25 * 0.7, pm25 * 1.1)


@pytest.fixture(scope="module")
def model():
    return train([synthetic()], horizons=HORIZONS, model_version="lgbm-test", rounds=150)


def test_trains_one_model_per_pollutant_horizon_quantile(model):
    assert set(model.boosters) == {
        (p, h, q) for p in ("pm25", "pm10") for h in HORIZONS for q in QUANTILES
    }


def test_predictions_are_ordered_and_beat_persistence():
    test = synthetic(seed=1)
    m = train([synthetic()], horizons=(6,), model_version="lgbm-test", rounds=150)
    errors, persistence = [], []
    for t in range(200, len(test.pm25) - 6, 7):
        pred = m.predict(test, t)[6]["pm25"]
        assert pred[0] <= pred[1] <= pred[2]
        errors.append(abs(pred[1] - test.pm25[t + 6]))
        persistence.append(abs(test.pm25[t] - test.pm25[t + 6]))
    assert np.mean(errors) < np.mean(persistence)


def test_drivers_sum_to_prediction_minus_baseline(model):
    s = synthetic(seed=2)
    t = 500
    drivers, expected_value = model.drivers(s, t, horizon=3)
    q50 = model.predict(s, t)[3]["pm25"][1]
    assert sum(drivers.values()) + expected_value == pytest.approx(q50, abs=0.051)  # q50 rounded to 0.1
    assert set(drivers) == {"ventilation", "recent_buildup", "regional_pollution", "time_of_day"}


def test_ventilation_matters_for_this_signal(model):
    s = synthetic(seed=3)
    spans = [abs(model.drivers(s, t, horizon=6)[0]["ventilation"]) for t in range(300, 900, 25)]
    assert np.mean(spans) > 1.0


def test_save_and_load_round_trip(model, tmp_path):
    model.save(tmp_path)
    loaded = ForecastModel.load(tmp_path)
    s = synthetic(seed=4)
    assert loaded.model_version == "lgbm-test"
    assert loaded.predict(s, 400) == model.predict(s, 400)


def test_negative_predictions_clipped(model):
    s = synthetic(seed=5)
    s.pm25[:] = 0.0
    s.pm10[:] = 0.0
    for horizon in model.predict(s, 300).values():
        assert min(horizon["pm25"]) >= 0
