"""Direct multi-horizon quantile LightGBM models: one per (pollutant, horizon, quantile).

Per-horizon models keep leakage reasoning and feature importance horizon-specific (the
explanation changes with lead time), at a training cost of seconds per model.
Explanations are exact TreeSHAP from LightGBM's pred_contrib on the q=0.5 models, summed
into driver groups.
"""

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

import lightgbm as lgb
import numpy as np

from ml.features import FEATURE_GROUPS, StationSeries, feature_matrix, feature_names, training_rows

QUANTILES = (0.1, 0.5, 0.9)
POLLUTANTS = ("pm25", "pm10")
PARAMS = {
    "objective": "quantile",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 40,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "verbose": -1,
    "seed": 0,
    "num_threads": 1,
}

Key = tuple[str, int, float]


def _filename(key: Key) -> str:
    pollutant, horizon, q = key
    return f"{pollutant}_h{horizon:02d}_q{round(q * 100):02d}.txt"


class ForecastModel:
    def __init__(
        self, boosters: dict[Key, lgb.Booster], model_version: str, horizons: Sequence[int]
    ):
        self.boosters = boosters
        self.model_version = model_version
        self.horizons = tuple(horizons)

    def predict(self, s: StationSeries, t: int) -> dict[int, dict[str, tuple[float, float, float]]]:
        """{horizon: {pollutant: (q10, q50, q90)}}, sorted per hour and clipped at 0."""
        out: dict[int, dict[str, tuple[float, float, float]]] = {}
        for h in self.horizons:
            out[h] = {}
            for p in POLLUTANTS:
                x = feature_matrix(s, h, p)[t : t + 1]
                raw = [float(self.boosters[(p, h, q)].predict(x)[0]) for q in QUANTILES]
                q10, q50, q90 = sorted(max(v, 0.0) for v in raw)
                out[h][p] = (round(q10, 1), round(q50, 1), round(q90, 1))
        return out

    def drivers(
        self, s: StationSeries, t: int, horizon: int, pollutant: str = "pm25"
    ) -> tuple[dict[str, float], float]:
        """Signed group contributions to the q50 prediction (ug/m3) and the baseline value.

        The station identity's contribution is folded into the baseline: it is a constant
        offset for that station, not a driver of change.
        """
        x = feature_matrix(s, horizon, pollutant)[t : t + 1]
        contrib = self.boosters[(pollutant, horizon, 0.5)].predict(x, pred_contrib=True)[0]
        names = feature_names(pollutant)
        by_name = dict(zip(names, contrib[:-1], strict=True))
        groups = {
            g: float(sum(by_name[n] for n in members)) for g, members in FEATURE_GROUPS.items()
        }
        expected = float(contrib[-1] + by_name["station"])
        return groups, expected

    def save(self, directory: Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for key, booster in self.boosters.items():
            booster.save_model(str(directory / _filename(key)))
        manifest = {
            "model_version": self.model_version,
            "horizons": list(self.horizons),
            "quantiles": list(QUANTILES),
            "pollutants": list(POLLUTANTS),
            "feature_names": {p: feature_names(p) for p in POLLUTANTS},
        }
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "ForecastModel":
        directory = Path(directory)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        boosters = {
            (p, h, q): lgb.Booster(model_file=str(directory / _filename((p, h, q))))
            for p in manifest["pollutants"]
            for h in manifest["horizons"]
            for q in manifest["quantiles"]
        }
        return cls(boosters, manifest["model_version"], manifest["horizons"])


def _rows(series: Iterable[StationSeries], horizon: int, pollutant: str):
    parts = [training_rows(s, horizon, pollutant) for s in series]
    return np.vstack([p[0] for p in parts]), np.concatenate([p[1] for p in parts])


def train(
    series: Sequence[StationSeries],
    horizons: Sequence[int] = tuple(range(1, 13)),
    model_version: str = "lgbm-v1",
    rounds: int = 400,
) -> ForecastModel:
    boosters: dict[Key, lgb.Booster] = {}
    for p in POLLUTANTS:
        names = feature_names(p)
        for h in horizons:
            X, y = _rows(series, h, p)
            for q in QUANTILES:
                data = lgb.Dataset(X, y, feature_name=names, categorical_feature=["station"])
                boosters[(p, h, q)] = lgb.train({**PARAMS, "alpha": q}, data, rounds)
    return ForecastModel(boosters, model_version, horizons)
