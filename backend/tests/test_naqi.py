import math

import pytest

from backend.naqi import BREAKPOINTS, UNITS, averaged, hourly_pm_index, overall, sub_index
from backend.schemas import Band, Pollutant

P = Pollutant

# (pollutant, [(c_lo, c_hi, i_lo, i_hi), ...]) as published by CPCB; Severe uses our anchors.
PUBLISHED = {
    P.PM25: [(0, 30), (31, 60), (61, 90), (91, 120), (121, 250), (251, 380)],
    P.PM10: [(0, 50), (51, 100), (101, 250), (251, 350), (351, 430), (431, 510)],
    P.NO2: [(0, 40), (41, 80), (81, 180), (181, 280), (281, 400), (401, 520)],
    P.O3: [(0, 50), (51, 100), (101, 168), (169, 208), (209, 748), (749, 1288)],
    P.CO: [(0, 1.0), (1.1, 2.0), (2.1, 10), (10.1, 17), (17.1, 34), (34.1, 51.0)],
    P.SO2: [(0, 40), (41, 80), (81, 380), (381, 800), (801, 1600), (1601, 2400)],
    P.NH3: [(0, 200), (201, 400), (401, 800), (801, 1200), (1201, 1800), (1801, 2400)],
}
INDEX_EDGES = [(0, 50), (51, 100), (101, 200), (201, 300), (301, 400), (401, 500)]


@pytest.mark.parametrize("pollutant", list(PUBLISHED))
def test_every_band_edge_maps_to_published_index_edge(pollutant):
    for (c_lo, c_hi), (i_lo, i_hi) in zip(PUBLISHED[pollutant], INDEX_EDGES, strict=True):
        assert sub_index(pollutant, c_lo) == i_lo, (pollutant, c_lo)
        assert sub_index(pollutant, c_hi) == i_hi, (pollutant, c_hi)


def test_breakpoint_table_matches_published_values():
    for pollutant, bands in PUBLISHED.items():
        assert [(b[0], b[1]) for b in BREAKPOINTS[pollutant]] == bands


def test_units():
    assert UNITS[P.CO] == "mg_m3"
    assert all(UNITS[p] == "ug_m3" for p in PUBLISHED if p is not P.CO)


def test_gap_values_round_into_correct_band():
    assert sub_index(P.PM25, 30.4) == 50
    assert sub_index(P.PM25, 30.6) == 51
    assert sub_index(P.CO, 1.04) == 50
    assert sub_index(P.CO, 1.06) == 51


def test_mid_band_value_interpolates_linearly():
    # PM2.5 185 in 121-250 -> 301 + 99 * 64/129 = 350.1
    assert sub_index(P.PM25, 185) == 350


def test_values_beyond_severe_anchor_cap_at_500():
    assert sub_index(P.PM25, 999) == 500


@pytest.mark.parametrize("bad", [-1.0, math.nan, math.inf])
def test_invalid_concentrations_raise(bad):
    with pytest.raises(ValueError):
        sub_index(P.PM25, bad)


def test_averaged_24h_mean_ignores_missing():
    values = [100.0] * 20 + [None] * 4
    assert averaged(P.PM25, values) == 100.0


def test_averaged_24h_needs_16_valid_hours():
    assert averaged(P.PM25, [100.0] * 15 + [None] * 9) is None
    assert averaged(P.PM25, [100.0] * 16 + [None] * 8) == 100.0


def test_averaged_uses_only_latest_24_hours():
    assert averaged(P.PM10, [999.0] * 6 + [50.0] * 24) == 50.0


def test_averaged_8h_takes_max_running_mean():
    values = [10.0] * 16 + [80.0] * 8
    assert averaged(P.O3, values) == 80.0


def test_averaged_8h_skips_windows_with_fewer_than_6_valid():
    # The last window holds five 500s and three gaps (5 valid) and must be skipped; the
    # best valid window is 10 + five 500s + two gaps (6 valid).
    values = [10.0] * 16 + [500.0] * 5 + [None] * 3
    assert averaged(P.CO, values) == pytest.approx(2510 / 6)


def test_averaged_8h_none_when_no_window_has_6_valid():
    assert averaged(P.O3, [None, 1.0] * 12) is None


def test_overall_ok_with_three_pollutants_including_pm():
    aqi = overall({P.PM25: 320, P.NO2: 90, P.O3: 40})
    assert (aqi.status, aqi.aqi, aqi.band, aqi.dominant_pollutant) == (
        "ok",
        320,
        Band.VERY_POOR,
        P.PM25,
    )
    assert set(aqi.pollutants_present) == {P.PM25, P.NO2, P.O3}


def test_overall_insufficient_with_two_pollutants():
    aqi = overall({P.PM25: 320, P.NO2: 90})
    assert aqi.status == "insufficient_data"
    assert aqi.aqi is None


def test_overall_insufficient_without_pm():
    assert overall({P.NO2: 90, P.O3: 40, P.CO: 70}).status == "insufficient_data"


def test_overall_tie_prefers_pm25():
    assert overall({P.PM10: 300, P.PM25: 300, P.NO2: 10}).dominant_pollutant is P.PM25


def test_hourly_pm_index_takes_max_and_handles_missing():
    assert hourly_pm_index(185, 300) == max(sub_index(P.PM25, 185), sub_index(P.PM10, 300))
    assert hourly_pm_index(None, 300) == sub_index(P.PM10, 300)
    assert hourly_pm_index(None, None) is None
