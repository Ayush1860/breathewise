"""Indian National Air Quality Index (CPCB NAQI).

Pure functions: concentrations -> sub-indices -> overall AQI. Breakpoints follow the
official CPCB NAQI table. CPCB publishes no upper bound for "Severe"; we use an anchor
one unit above the Very Poor upper bound with the same width as the Very Poor band
(PM2.5 251-380, PM10 431-510), and cap at 500.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Literal

from backend.schemas import AqiValue, Pollutant, band_for_index

P = Pollutant
Breakpoint = tuple[float, float, int, int]

_INDEX_BANDS = ((0, 50), (51, 100), (101, 200), (201, 300), (301, 400), (401, 500))
_CONCENTRATION_BANDS: dict[Pollutant, tuple[tuple[float, float], ...]] = {
    P.PM25: ((0, 30), (31, 60), (61, 90), (91, 120), (121, 250), (251, 380)),
    P.PM10: ((0, 50), (51, 100), (101, 250), (251, 350), (351, 430), (431, 510)),
    P.NO2: ((0, 40), (41, 80), (81, 180), (181, 280), (281, 400), (401, 520)),
    P.O3: ((0, 50), (51, 100), (101, 168), (169, 208), (209, 748), (749, 1288)),
    P.CO: ((0, 1.0), (1.1, 2.0), (2.1, 10), (10.1, 17), (17.1, 34), (34.1, 51.0)),
    P.SO2: ((0, 40), (41, 80), (81, 380), (381, 800), (801, 1600), (1601, 2400)),
    P.NH3: ((0, 200), (201, 400), (401, 800), (801, 1200), (1201, 1800), (1801, 2400)),
}
BREAKPOINTS: dict[Pollutant, tuple[Breakpoint, ...]] = {
    pollutant: tuple(
        (c_lo, c_hi, i_lo, i_hi)
        for (c_lo, c_hi), (i_lo, i_hi) in zip(bands, _INDEX_BANDS, strict=True)
    )
    for pollutant, bands in _CONCENTRATION_BANDS.items()
}
UNITS: dict[Pollutant, Literal["ug_m3", "mg_m3"]] = {
    p: ("mg_m3" if p is P.CO else "ug_m3") for p in Pollutant
}

_EIGHT_HOUR = {P.O3, P.CO}
_DOMINANCE_ORDER = list(Pollutant)  # PM2.5 first, then PM10, then the rest


def _round(pollutant: Pollutant, concentration: float) -> float:
    # CPCB reports CO to 0.1 mg/m3 and the rest to whole ug/m3; rounding closes band gaps.
    # Half-up rounding (not banker's) so 30.5 -> 31.
    if pollutant is P.CO:
        return math.floor(concentration * 10 + 0.5) / 10
    return math.floor(concentration + 0.5)


def sub_index(pollutant: Pollutant, concentration: float) -> int:
    if not math.isfinite(concentration) or concentration < 0:
        raise ValueError(f"invalid {pollutant} concentration: {concentration!r}")
    c = _round(pollutant, concentration)
    for c_lo, c_hi, i_lo, i_hi in BREAKPOINTS[pollutant]:
        if c <= c_hi:
            return round(i_lo + (i_hi - i_lo) * (c - c_lo) / (c_hi - c_lo))
    return 500


def hourly_pm_index(pm25: float | None, pm10: float | None) -> int | None:
    """Indicative nowcast: NAQI breakpoints applied to hourly PM (not an official AQI)."""
    indices = [sub_index(p, c) for p, c in ((P.PM25, pm25), (P.PM10, pm10)) if c is not None]
    return max(indices) if indices else None


def _mean(values: Sequence[float | None], min_valid: int) -> float | None:
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if len(valid) >= min_valid else None


def averaged(pollutant: Pollutant, hourly: Sequence[float | None]) -> float | None:
    """CPCB averaging over the latest 24 hourly values (oldest first).

    24 h mean (>= 16 valid) for PM, NO2, SO2, NH3; maximum 8 h running mean (each window
    >= 6 of 8 valid) for O3 and CO. None when there is not enough data.
    """
    last = list(hourly[-24:])
    if pollutant not in _EIGHT_HOUR:
        return _mean(last, min_valid=16)
    means = [_mean(last[i : i + 8], min_valid=6) for i in range(max(len(last) - 7, 0))]
    valid = [m for m in means if m is not None]
    return max(valid) if valid else None


def overall(sub_indices: Mapping[Pollutant, int]) -> AqiValue:
    """Overall AQI = max sub-index; needs >= 3 pollutants including PM2.5 or PM10."""
    present = [p for p in _DOMINANCE_ORDER if p in sub_indices]
    has_pm = P.PM25 in sub_indices or P.PM10 in sub_indices
    if len(present) < 3 or not has_pm:
        return AqiValue(status="insufficient_data", pollutants_present=present)
    dominant = max(present, key=lambda p: (sub_indices[p], -_DOMINANCE_ORDER.index(p)))
    value = sub_indices[dominant]
    return AqiValue(
        status="ok",
        aqi=value,
        band=band_for_index(value),
        dominant_pollutant=dominant,
        pollutants_present=present,
    )
