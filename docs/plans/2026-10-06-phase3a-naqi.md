# Phase 3a — `backend/naqi.py` Implementation Plan

**Goal:** a pure NAQI module, written test-first. Ingest, the forecast and the API use it to turn concentrations into CPCB sub-indices, the AQI and bands.

**Spec:** `docs/specs/2026-10-06-breathewise-core-design.md` §7.

## Breakpoint cross-check (official CPCB NAQI table)
- Matches the project brief for every pollutant and band.
- CPCB writes CO "Poor" as `10–17`. With one-decimal rounding this is the same as the brief's `10.1–17`.
- **Not published:** an upper anchor for Severe. Ruling: Severe starts one unit above the Very Poor upper bound, and its width equals the Very Poor band width: PM2.5 251–380, PM10 431–510, NO2 401–520, O3 749–1288, CO 34.1–51.0, SO2 1601–2400, NH3 1801–2400. This reproduces the common 380/510 convention for PM. Values beyond the anchor cap at 500.

## Interfaces (produced)
- `BREAKPOINTS: dict[Pollutant, tuple[Breakpoint, ...]]`, where `Breakpoint = (c_lo, c_hi, i_lo, i_hi)`.
- `UNITS: dict[Pollutant, Literal["ug_m3", "mg_m3"]]`; CO is mg/m³.
- `sub_index(pollutant, concentration) -> int`: rounds per CPCB (integer µg/m³, 0.1 for CO), interpolates, caps at 500, raises `ValueError` on negatives or NaN.
- `hourly_pm_index(pm25: float | None, pm10: float | None) -> int | None`: the indicative nowcast; `None` if both are missing.
- `averaged(pollutant, hourly: Sequence[float | None]) -> float | None`: takes the latest 24 hourly values, oldest first.
  - PM, NO2, SO2, NH3: 24 h mean, needing at least 16 valid values.
  - O3, CO: the maximum 8 h running mean, each window needing at least 6 of 8 valid values.
  - Returns `None` if there is not enough data.
- `overall(sub_indices: Mapping[Pollutant, int]) -> AqiValue`. The result is `ok` only with at least 3 pollutants that include PM2.5 or PM10; otherwise it is `insufficient_data`. The dominant pollutant is the one with the maximum sub-index; ties go to PM2.5, then PM10, then the enum order.
- `band_for_index` comes from `backend.schemas` and is reused.

## Tests (`backend/tests/test_naqi.py`)
1. Every band edge for every pollutant (both ends of each range) maps to the published index edge.
2. Gap values round into the right band: PM2.5 30.4 → 50 and 30.6 → 51; CO 1.04 → 50 and 1.06 → 51.
3. A mid-band value interpolates linearly.
4. Values above the Severe anchor cap at 500. Negatives and NaN raise.
5. `averaged` returns the 24 h mean; returns `None` with 15 valid hours; ignores `None` values.
6. `averaged` for O3/CO returns the max 8 h running mean; windows with fewer than 6 valid values are skipped.
7. `overall` returns `ok` for 3 pollutants incl. PM, and `insufficient_data` for 2 pollutants or for 3 without PM. The dominant pollutant is correct.
8. `hourly_pm_index` takes the max of the two PM indices, handles a single PM value, and returns `None` when both are missing.
