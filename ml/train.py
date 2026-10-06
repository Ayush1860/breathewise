"""Reproducible training: python -m ml.train --city delhi

Inputs (git-ignored, mirrored to S3):
  data/observations/<station>.parquet  time (UTC hour), pm25, pm10   (OpenAQ/CPCB history)
  data/openmeteo/<station>.parquet     time, wx_*, fc_*, cams_*       (ml.history)

Split (spec §8): train on everything up to 2025-10-05 23:59 IST, test on 2025-10-06 ..
2025-12-31 IST (post-monsoon + stubble season). After evaluation the production model is
retrained on all data with the same settings. Outputs ml/artifacts/<model_version>/ with
the boosters, manifest.json and metrics.json.
"""

import argparse
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ingest.stations import load_stations
from ml.evaluate import evaluate
from ml.features import HISTORY_HOURS, StationSeries, impute_short_gaps
from ml.model import train

TRAIN_END = datetime(2025, 10, 5, 18, 30, tzinfo=UTC)  # 2025-10-06 00:00 IST
TEST_END = datetime(2025, 12, 31, 18, 30, tzinfo=UTC)  # 2026-01-01 00:00 IST
WX = ("u", "v", "blh", "temp", "rh", "precip", "pressure")
FC = ("u", "v", "temp", "rh", "precip")


def load_frame(station_id: str, obs_dir: Path, wx_dir: Path) -> pd.DataFrame:
    obs = pd.read_parquet(obs_dir / f"{station_id}.parquet")
    wx = pd.read_parquet(wx_dir / f"{station_id}.parquet")
    for df in (obs, wx):
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.floor("h")
    start, end = min(obs["time"].min(), wx["time"].min()), max(obs["time"].max(), wx["time"].max())
    grid = pd.DataFrame({"time": pd.date_range(start, end, freq="h", tz="UTC")})
    frame = grid.merge(obs.groupby("time", as_index=False).mean(), on="time", how="left")
    return frame.merge(wx.drop_duplicates("time"), on="time", how="left")


def to_series(frame: pd.DataFrame, code: int) -> StationSeries:
    col = lambda name: frame[name].to_numpy(dtype=float)  # noqa: E731
    return StationSeries(
        station_code=code,
        time=frame["time"].dt.tz_localize(None).to_numpy().astype("datetime64[h]"),
        pm25=impute_short_gaps(col("pm25")),
        pm10=impute_short_gaps(col("pm10")),
        weather={k: col(f"wx_{k}") for k in WX},
        weather_forecast={k: col(f"fc_{k}") for k in FC},
        cams_pm25=col("cams_pm25"),
        cams_pm10=col("cams_pm10"),
    )


def window(frame: pd.DataFrame, start: datetime | None, end: datetime) -> pd.DataFrame:
    """Rows with time < end; when start is given, keep HISTORY_HOURS-1 hours of lag history
    before it so the first issue hour with full lags is exactly `start`."""
    keep = frame["time"] < end
    if start is not None:
        keep &= frame["time"] >= start - timedelta(hours=HISTORY_HOURS - 1)
    return frame[keep].reset_index(drop=True)


def coverage(frame: pd.DataFrame) -> dict[str, float]:
    return {c: round(float(frame[c].notna().mean()), 3) for c in ("pm25", "pm10")}


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "local"


def run(
    obs_dir: Path,
    wx_dir: Path,
    out_dir: Path,
    rounds: int = 400,
    horizons: tuple[int, ...] = tuple(range(1, 13)),
) -> Path:
    stations = load_stations()
    frames = {s.station_id: load_frame(s.station_id, obs_dir, wx_dir) for s in stations}
    codes = {s.station_id: i for i, s in enumerate(stations)}
    for sid, frame in frames.items():
        print(f"{sid}: {len(frame)} hours, coverage {coverage(frame)}")
    version = f"lgbm-v1-{git_sha()}"

    train_series = [to_series(window(f, None, TRAIN_END), codes[s]) for s, f in frames.items()]
    test_series = [to_series(window(f, TRAIN_END, TEST_END), codes[s]) for s, f in frames.items()]
    eval_model = train(train_series, horizons, version, rounds)
    metrics = evaluate(
        eval_model,
        test_series,
        trained_until=TRAIN_END - timedelta(hours=1),
        test_start=TRAIN_END,
        test_end=TEST_END - timedelta(hours=1),
        generated_at=datetime.now(UTC),
    )

    all_series = [to_series(f, codes[s]) for s, f in frames.items()]
    production = train(all_series, horizons, version, rounds)
    target = out_dir / version
    production.save(target)
    (target / "metrics.json").write_text(metrics.model_dump_json(indent=2), encoding="utf-8")
    for m in metrics.pm25:
        print(
            f"pm25 h{m.horizon_h:>2}: MAE {m.mae:6.1f}  persistence {m.mae_persistence:6.1f}"
            f"  CAMS {m.mae_cams:6.1f}  coverage {m.interval_coverage:.2f}"
        )
    print(f"saved {target}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="delhi", choices=["delhi"])
    parser.add_argument("--obs-dir", type=Path, default=Path("data/observations"))
    parser.add_argument("--wx-dir", type=Path, default=Path("data/openmeteo"))
    parser.add_argument("--out", type=Path, default=Path("ml/artifacts"))
    parser.add_argument("--rounds", type=int, default=400)
    args = parser.parse_args()
    np.seterr(all="ignore")
    run(args.obs_dir, args.wx_dir, args.out, args.rounds)


if __name__ == "__main__":
    main()
