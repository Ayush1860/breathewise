"""Per-station source fallback chain: CPCB -> OpenAQ -> CAMS (first with PM data wins)."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.schemas import Pollutant, Source
from backend.store import Observation
from ingest.http import SourceError
from ingest.stations import StationConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    observations: list[Observation]
    raw: Any


SourceFetcher = Callable[[StationConfig, datetime, datetime], FetchResult]


@dataclass
class ChainOutcome:
    station_id: str
    source: Source | None = None
    observations: list[Observation] = field(default_factory=list)
    errors: dict[Source, str] = field(default_factory=dict)
    raws: dict[Source, Any] = field(default_factory=dict)


def _has_pm(obs: Observation) -> bool:
    return any(obs.values.get(p) is not None for p in (Pollutant.PM25, Pollutant.PM10))


def run_chain(
    station: StationConfig,
    fetchers: Sequence[tuple[Source, SourceFetcher]],
    start: datetime,
    end: datetime,
) -> ChainOutcome:
    outcome = ChainOutcome(station.station_id)
    for source, fetch in fetchers:
        try:
            result = fetch(station, start, end)
        except SourceError as exc:
            outcome.errors[source] = str(exc)
            continue
        except Exception as exc:  # a broken parser must not stop the chain
            log.exception("source %s failed for %s", source, station.station_id)
            outcome.errors[source] = f"{type(exc).__name__}: {exc}"
            continue
        outcome.raws[source] = result.raw
        usable = [o for o in result.observations if start <= o.time <= end and _has_pm(o)]
        if usable:
            outcome.source, outcome.observations = source, usable
            return outcome
        outcome.errors[source] = "no PM data in window"
    return outcome
