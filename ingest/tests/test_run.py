import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from backend.schemas import Pollutant, Source
from backend.store import Observation, Store, create_table
from ingest.chain import FetchResult
from ingest.http import SourceError
from ingest.run import cams_fetcher, force_fail, ingest_window, run_ingest
from ingest.stations import load_stations

NOW = datetime(2026, 10, 6, 9, 20, tzinfo=UTC)
AIR = json.loads(
    (Path(__file__).parent / "samples" / "openmeteo_air_quality.json").read_text(encoding="utf-8")
)


@pytest.fixture
def store():
    with mock_aws():
        table = create_table(boto3.resource("dynamodb", region_name="ap-south-1"), "t")
        yield Store(table, now=lambda: NOW)


def test_window_is_last_three_complete_hours():
    start, end = ingest_window(NOW)
    assert end == datetime(2026, 10, 6, 8, 0, tzinfo=UTC)
    assert start == end - timedelta(hours=2)


def fake(source, values=None, error=None):
    def fetch(station, start, end):
        if error:
            raise SourceError(error)
        obs = [
            Observation(station.station_id, start + timedelta(hours=h), source, values)
            for h in range(3)
        ]
        return FetchResult(obs, {"from": source.value})

    return source, fetch


def test_run_stores_observations_latest_raw_and_health(store):
    raws, triggered = {}, []
    summary = run_ingest(
        NOW,
        load_stations()[:1],
        [fake(Source.CPCB, error="HTTP 503"), fake(Source.OPENAQ, {Pollutant.PM25: 90.0})],
        store,
        raw_sink=raws.__setitem__,
        after=lambda: triggered.append(True),
    )
    assert summary == {"dl-rohini": "openaq"}
    start, end = ingest_window(NOW)
    assert len(store.observations("dl-rohini", since=start)) == 3
    assert store.latest("dl-rohini").time == end
    assert list(raws) == ["raw/2026/10/06/08/openaq-dl-rohini.json"]
    health = {h.source: h for h in store.health()}
    assert health[Source.CPCB].last_error == "HTTP 503"
    assert health[Source.OPENAQ].last_success_at is not None
    assert triggered == [True]


def test_run_with_all_sources_failing_reports_none_and_still_triggers(store):
    triggered = []
    summary = run_ingest(
        NOW,
        load_stations()[:1],
        [fake(Source.CPCB, error="down")],
        store,
        raw_sink=lambda k, v: None,
        after=lambda: triggered.append(True),
    )
    assert summary == {"dl-rohini": None}
    assert store.latest("dl-rohini") is None
    assert triggered == [True]


def test_force_fail_wraps_named_sources():
    source, fetch = force_fail([fake(Source.CPCB, {Pollutant.PM25: 1.0})], "cpcb,openaq")[0]
    with pytest.raises(SourceError, match="FORCE_FAIL"):
        fetch(load_stations()[0], NOW, NOW)


def test_cams_fetcher_maps_sample_to_observations():
    station = load_stations()[0]
    start = datetime.fromisoformat(AIR["hourly"]["time"][10]).replace(tzinfo=UTC)
    end = start + timedelta(hours=2)
    result = cams_fetcher(lambda url, params: AIR)(station, start, end)
    assert len(result.observations) == 3
    first = result.observations[0]
    assert first.source is Source.CAMS_MODEL and first.time == start
    assert first.values[Pollutant.PM25] == AIR["hourly"]["pm2_5"][10]
    assert first.values[Pollutant.CO] == pytest.approx(AIR["hourly"]["carbon_monoxide"][10] / 1000)
    assert result.raw is AIR
