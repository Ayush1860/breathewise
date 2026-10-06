import json

import numpy as np
import pandas as pd

from backend.schemas import MetricsResponse
from ingest.stations import load_stations
from ml.model import ForecastModel
from ml.train import run


def write_inputs(tmp_path):
    obs_dir, wx_dir = tmp_path / "obs", tmp_path / "wx"
    obs_dir.mkdir(), wx_dir.mkdir()
    times = pd.date_range("2025-08-01", "2026-01-05", freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    for station in load_stations():
        n = len(times)
        wind = 3 + 2 * np.sin(np.arange(n) / 9)
        pm25 = 220 - 35 * wind + rng.normal(0, 5, n)
        pm25[100:102] = np.nan  # short gap gets imputed
        pd.DataFrame({"time": times, "pm25": pm25, "pm10": pm25 * 1.6}).to_parquet(
            obs_dir / f"{station.station_id}.parquet"
        )
        wx = {"time": times}
        for k in ("u", "v", "blh", "temp", "rh", "precip", "pressure"):
            wx[f"wx_{k}"] = wind if k == "u" else rng.normal(size=n)
        for k in ("u", "v", "temp", "rh", "precip"):
            wx[f"fc_{k}"] = wind if k == "u" else rng.normal(size=n)
        wx["cams_pm25"], wx["cams_pm10"] = pm25 * 0.7, pm25 * 1.1
        pd.DataFrame(wx).to_parquet(wx_dir / f"{station.station_id}.parquet")
    return obs_dir, wx_dir


def test_run_trains_evaluates_and_saves(tmp_path):
    obs_dir, wx_dir = write_inputs(tmp_path)
    target = run(obs_dir, wx_dir, tmp_path / "artifacts", rounds=30, horizons=(1, 3))
    metrics = MetricsResponse.model_validate_json((target / "metrics.json").read_text())
    assert metrics.test_start.isoformat() == "2025-10-05T18:30:00+00:00"
    assert [m.horizon_h for m in metrics.pm25] == [1, 3]
    assert json.loads((target / "manifest.json").read_text())["horizons"] == [1, 3]
    assert ForecastModel.load(target).model_version == metrics.model_version
    assert ForecastModel.load(target / "eval").station_codes["dl-rohini"] == 0
