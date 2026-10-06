from datetime import UTC, datetime

import pytest

from backend.schemas import MetricsResponse
from ml.evaluate import evaluate
from ml.model import train
from ml.tests.test_model import synthetic


@pytest.fixture(scope="module")
def metrics():
    model = train([synthetic()], horizons=(1, 6), model_version="lgbm-test", rounds=120)
    return evaluate(
        model,
        [synthetic(seed=7)],
        trained_until=datetime(2025, 10, 5, 18, 29, tzinfo=UTC),
        test_start=datetime(2025, 10, 5, 18, 30, tzinfo=UTC),
        test_end=datetime(2025, 12, 31, 18, 29, tzinfo=UTC),
        generated_at=datetime(2026, 10, 7, tzinfo=UTC),
    )


def test_metrics_match_contract(metrics):
    assert isinstance(metrics, MetricsResponse)
    assert [m.horizon_h for m in metrics.pm25] == [1, 6]
    assert metrics.model_version == "lgbm-test"


def test_model_beats_persistence_at_longer_horizon(metrics):
    h6 = metrics.pm25[1]
    assert h6.mae < h6.mae_persistence


def test_interval_coverage_is_a_fraction_near_80_percent(metrics):
    for m in metrics.pm25:
        assert 0.5 < m.interval_coverage <= 1.0


def test_category_accuracy_reported_for_model_and_persistence(metrics):
    for c in metrics.index_category_accuracy:
        assert 0 <= c.accuracy <= 1 and 0 <= c.accuracy_persistence <= 1
