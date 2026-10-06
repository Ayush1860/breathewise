"""Hourly ingest: fallback chain per station -> DynamoDB + raw JSON to S3."""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from backend.schemas import Pollutant, Source
from backend.store import Observation, Store
from ingest.chain import FetchResult, SourceFetcher, run_chain
from ingest.http import SourceError, get_json
from ingest.openmeteo import AIR_QUALITY_URL, CAMS_VARS, parse_cams, request_params
from ingest.stations import StationConfig

log = logging.getLogger(__name__)

REFETCH_HOURS = 3  # CPCB backfills late; idempotent upserts make re-fetching safe


def floor_hour(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def ingest_window(now: datetime) -> tuple[datetime, datetime]:
    """(start, end) hour starts of the last REFETCH_HOURS complete hours."""
    end = floor_hour(now) - timedelta(hours=1)
    return end - timedelta(hours=REFETCH_HOURS - 1), end


def cams_fetcher(get: Callable[[str, Any], Any] = get_json) -> SourceFetcher:
    def fetch(station: StationConfig, start: datetime, end: datetime) -> FetchResult:
        raw = get(AIR_QUALITY_URL, request_params(station.lat, station.lon, CAMS_VARS, 1, 1))
        observations = [
            Observation(
                station.station_id,
                row.time,
                Source.CAMS_MODEL,
                {
                    p: v
                    for p, v in (
                        (Pollutant.PM25, row.pm25),
                        (Pollutant.PM10, row.pm10),
                        (Pollutant.NO2, row.no2),
                        (Pollutant.O3, row.o3),
                        (Pollutant.CO, row.co_mg_m3),
                        (Pollutant.SO2, row.so2),
                    )
                    if v is not None
                },
            )
            for row in parse_cams(raw)
            if start <= row.time <= end
        ]
        return FetchResult(observations, raw)

    return fetch


def force_fail(
    fetchers: Sequence[tuple[Source, SourceFetcher]], spec: str
) -> list[tuple[Source, SourceFetcher]]:
    """Demo drill: FORCE_FAIL=cpcb,openaq makes those sources raise."""
    failing = {s.strip() for s in spec.split(",") if s.strip()}

    def broken(source: Source) -> SourceFetcher:
        def fetch(station: StationConfig, start: datetime, end: datetime) -> FetchResult:
            raise SourceError(f"FORCE_FAIL simulated outage of {source.value}")

        return fetch

    return [(s, broken(s) if s.value in failing else f) for s, f in fetchers]


def run_ingest(
    now: datetime,
    stations: Sequence[StationConfig],
    fetchers: Sequence[tuple[Source, SourceFetcher]],
    store: Store,
    raw_sink: Callable[[str, Any], None],
    after: Callable[[], None],
) -> dict[str, str | None]:
    start, end = ingest_window(now)
    summary: dict[str, str | None] = {}
    for station in stations:
        outcome = run_chain(station, fetchers, start, end)
        for source, error in outcome.errors.items():
            store.record_health(source, ok=False, error=error)
        for source, raw in outcome.raws.items():
            raw_sink(f"raw/{end:%Y/%m/%d/%H}/{source.value}-{station.station_id}.json", raw)
        if outcome.source is not None:
            store.record_health(outcome.source, ok=True)
            for obs in outcome.observations:
                store.put_observation(obs)
            store.update_latest(max(outcome.observations, key=lambda o: o.time))
        else:
            log.error("no source produced data for %s: %s", station.station_id, outcome.errors)
        summary[station.station_id] = outcome.source.value if outcome.source else None
    after()
    return summary
