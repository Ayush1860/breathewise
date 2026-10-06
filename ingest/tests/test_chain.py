from datetime import UTC, datetime, timedelta

from backend.schemas import Pollutant, Source
from backend.store import Observation
from ingest.chain import FetchResult, run_chain
from ingest.http import SourceError
from ingest.stations import VENUE_LAT_LON, load_stations

T = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)
START, END = T - timedelta(hours=2), T


def station():
    return load_stations()[0]


def result(source, pm=True, hours=(0,)):
    values = {Pollutant.PM25: 100.0} if pm else {Pollutant.NO2: 40.0}
    obs = [Observation("dl-rohini", T - timedelta(hours=h), source, values) for h in hours]
    return FetchResult(observations=obs, raw={"source": source.value})


def test_registry_has_exactly_one_venue_default():
    stations = load_stations()
    assert sum(s.is_venue_default for s in stations) == 1
    assert all(s.distance_to(*VENUE_LAT_LON) >= 0 for s in stations)


def test_first_source_with_pm_data_wins():
    calls = []

    def fetch(source, outcome):
        def f(st, start, end):
            calls.append(source)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return source, f

    outcome = run_chain(
        station(),
        [
            fetch(Source.CPCB, SourceError("HTTP 503", 503)),
            fetch(Source.OPENAQ, result(Source.OPENAQ, pm=False)),
            fetch(Source.CAMS_MODEL, result(Source.CAMS_MODEL)),
        ],
        START,
        END,
    )
    assert outcome.source is Source.CAMS_MODEL
    assert calls == [Source.CPCB, Source.OPENAQ, Source.CAMS_MODEL]
    assert outcome.errors[Source.CPCB] == "HTTP 503"
    assert outcome.errors[Source.OPENAQ] == "no PM data in window"
    assert set(outcome.raws) == {Source.OPENAQ, Source.CAMS_MODEL}


def test_stops_at_first_success():
    calls = []

    def ok(st, start, end):
        calls.append("cpcb")
        return result(Source.CPCB)

    def never(st, start, end):
        calls.append("openaq")
        return result(Source.OPENAQ)

    outcome = run_chain(station(), [(Source.CPCB, ok), (Source.OPENAQ, never)], START, END)
    assert outcome.source is Source.CPCB and calls == ["cpcb"]
    assert outcome.errors == {}


def test_observations_outside_window_are_dropped():
    def f(st, start, end):
        return result(Source.CPCB, hours=(0, 1, 2, 5))

    outcome = run_chain(station(), [(Source.CPCB, f)], START, END)
    assert sorted(o.time for o in outcome.observations) == [START, START + timedelta(hours=1), END]


def test_unexpected_exception_is_recorded_not_raised():
    def boom(st, start, end):
        raise KeyError("station field")

    outcome = run_chain(station(), [(Source.CPCB, boom)], START, END)
    assert outcome.source is None
    assert "KeyError" in outcome.errors[Source.CPCB]


def test_all_sources_failing_gives_no_source():
    outcome = run_chain(station(), [], START, END)
    assert outcome.source is None and outcome.observations == []
