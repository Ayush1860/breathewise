"""G1 packaging probe: proves lightgbm + numpy + libgomp load and run on Lambda."""

import numpy as np


def handler(event, context):
    import lightgbm as lgb

    rng = np.random.default_rng(0)
    x = rng.normal(size=(64, 3))
    y = x[:, 0] * 2 + rng.normal(scale=0.1, size=64)
    model = lgb.train(
        {"objective": "quantile", "alpha": 0.5, "verbose": -1, "min_data_in_leaf": 2},
        lgb.Dataset(x, y),
        num_boost_round=10,
    )
    contrib = model.predict(x[:2], pred_contrib=True)
    return {
        "lightgbm": lgb.__version__,
        "numpy": np.__version__,
        "pred": model.predict(x[:2]).round(3).tolist(),
        "contrib_shape": list(contrib.shape),
        "contrib_sums_match": bool(np.allclose(contrib.sum(axis=1), model.predict(x[:2]))),
    }
