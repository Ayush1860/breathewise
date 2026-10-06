from datetime import UTC, datetime

import numpy as np
import pytest

from backend.schemas import Station, Verdict
from ml.export_replay import build_episode, select_episodes
from ml.model import train
from ml.tests.test_model import synthetic

STATION = Station(station_id="dl-rohini", name="Rohini", lat=28.73, lon=77.12)


def test_select_episodes_picks_highest_non_overlapping_windows():
    pm = np.full(200, 50.0)
    pm[20:44] = 300.0
    pm[100:124] = 250.0
    pm[30:40] = 400.0  # inside the first episode, must not create an overlapping second one
    starts = select_episodes(pm, n=2, length=24, earliest=0)
    assert sorted(starts) == [20, 100]


def test_select_episodes_respects_earliest_and_nan():
    pm = np.full(100, 50.0)
    pm[0:24] = 500.0
    pm[60:84] = 200.0
    pm[70] = np.nan
    assert select_episodes(pm, n=1, length=24, earliest=24) == [60]


@pytest.fixture(scope="module")
def model():
    return train([synthetic()], horizons=tuple(range(1, 13)), model_version="lgbm-test", rounds=30)


def test_build_episode_validates_and_uses_verdict_function(model):
    s = synthetic(seed=9)
    calls = []

    def verdict(index, profile, activity):
        calls.append((profile, activity))
        return Verdict.AVOID

    episode = build_episode(
        model,
        s,
        STATION,
        start=200,
        length=6,
        episode_id="ep1",
        title="Test episode",
        verdict=verdict,
    )
    assert len(episode.hours) == 6
    first = episode.hours[0]
    assert first.time == datetime.fromisoformat(str(s.time[200])).replace(tzinfo=UTC)
    assert first.observed.pm25 == pytest.approx(round(s.pm25[200], 1))
    assert first.persistence_pm25 == first.observed.pm25
    assert len(first.forecast_hours) == 12
    assert len(first.verdicts) == 7 * 6 and set(first.verdicts.values()) == {Verdict.AVOID}


def test_build_episode_without_advisory_leaves_verdicts_empty(model):
    episode = build_episode(model, synthetic(seed=9), STATION, 200, 2, "ep", "t", verdict=None)
    assert episode.hours[0].verdicts == {}
