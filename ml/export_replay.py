"""Export replay episodes from the held-out test window (Oct-Dec 2025) as static JSON.

The evaluation model (trained only up to 2025-10-05) replays each episode hour by hour:
observed values, the 12 h forecast with bands/drivers/explanations, persistence and CAMS
baselines, and a verdict for every profile x activity (via backend.advisory.verdict when
the advisory engine is present).

    uv run python -m ml.export_replay --model ml/artifacts/<version>/eval
"""

import argparse
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from backend.naqi import hourly_pm_index
from backend.schemas import (
    Activity,
    Profile,
    ReplayEpisode,
    ReplayHour,
    ReplayObservation,
    Station,
    Verdict,
    band_for_index,
)
from ingest.stations import load_stations
from ml.features import StationSeries
from ml.live import hours_from_model
from ml.model import ForecastModel

VerdictFn = Callable[[int, Profile, Activity], Verdict]
OUT_DIR = Path("docs/fixtures/replay")


def select_episodes(pm25: np.ndarray, n: int, length: int, earliest: int) -> list[int]:
    """Start indices of the n highest-mean, non-overlapping windows starting at >= earliest."""
    starts = range(earliest, len(pm25) - length + 1)
    with np.errstate(all="ignore"):
        means = {i: np.nanmean(pm25[i : i + length]) for i in starts}
    ranked = sorted((i for i in means if not np.isnan(means[i])), key=lambda i: -means[i])
    chosen: list[int] = []
    for i in ranked:
        if all(abs(i - j) >= length for j in chosen):
            chosen.append(i)
        if len(chosen) == n:
            break
    return chosen


def _aware(t: np.datetime64) -> datetime:
    return datetime.fromisoformat(str(t.astype("datetime64[h]"))).replace(tzinfo=UTC)


def _value(x: float) -> float | None:
    return None if np.isnan(x) else round(float(x), 1)


def build_episode(
    model: ForecastModel,
    s: StationSeries,
    station: Station,
    start: int,
    length: int,
    episode_id: str,
    title: str,
    verdict: VerdictFn | None,
) -> ReplayEpisode:
    steps = []
    for t in range(start, start + length):
        issued = _aware(s.time[t])
        hours, summary = hours_from_model(model, s, t, issued)
        pm25, pm10 = _value(s.pm25[t]), _value(s.pm10[t])
        index = hourly_pm_index(pm25, pm10)
        verdicts = (
            {f"{p.value}:{a.value}": verdict(index, p, a) for p in Profile for a in Activity}
            if verdict is not None and index is not None
            else {}
        )
        steps.append(
            ReplayHour(
                time=issued,
                observed=ReplayObservation(
                    pm25=pm25,
                    pm10=pm10,
                    index=index,
                    band=band_for_index(index) if index is not None else None,
                ),
                forecast_hours=hours,
                summary=summary,
                persistence_pm25=pm25,
                cams_pm25=_value(s.cams_pm25[t]),
                verdicts=verdicts,
            )
        )
    return ReplayEpisode(
        episode_id=episode_id,
        title=title,
        station=station,
        start=steps[0].time,
        end=steps[-1].time,
        model_version=model.model_version,
        hours=steps,
    )


def _advisory_verdict() -> VerdictFn | None:
    try:
        from backend.advisory import verdict
    except ImportError:
        return None
    return verdict


def main() -> None:
    from ml.train import TEST_END, TRAIN_END, load_frame, to_series, window

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True, help="evaluation model directory")
    parser.add_argument("--obs-dir", type=Path, default=Path("data/observations"))
    parser.add_argument("--wx-dir", type=Path, default=Path("data/openmeteo"))
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    model = ForecastModel.load(args.model)
    verdict = _advisory_verdict()
    candidates = []
    for station in load_stations():
        frame = window(
            load_frame(station.station_id, args.obs_dir, args.wx_dir), TRAIN_END, TEST_END
        )
        series = to_series(frame, model.station_codes[station.station_id])
        for start in select_episodes(series.pm25, args.episodes, args.hours, earliest=23):
            mean = float(np.nanmean(series.pm25[start : start + args.hours]))
            candidates.append((station.is_venue_default, mean, station, series, start))
    venue = sorted((c for c in candidates if c[0]), key=lambda c: -c[1])[:1]
    rest = sorted((c for c in candidates if c not in venue), key=lambda c: -c[1])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for _, mean, station, series, start in (venue + rest)[: args.episodes]:
        day = _aware(series.time[start]).strftime("%Y-%m-%d")
        episode_id = f"{station.station_id}-{day}"
        view = Station(
            station_id=station.station_id,
            name=station.name,
            lat=station.lat,
            lon=station.lon,
            is_venue_default=station.is_venue_default,
        )
        episode = build_episode(
            model,
            series,
            view,
            start,
            args.hours,
            episode_id,
            f"{station.name}: {day} (mean PM2.5 {mean:.0f} µg/m³)",
            verdict,
        )
        path = OUT_DIR / f"{episode_id}.json"
        path.write_text(episode.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {path}")
    if verdict is None:
        print("note: backend.advisory not found; verdicts left empty")


if __name__ == "__main__":
    main()
