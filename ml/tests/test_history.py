import numpy as np
import pytest

from ml.history import chunks, merge_openmeteo


def payload(variables, times, values):
    return {
        "utc_offset_seconds": 0,
        "hourly_units": {v: "m/s" if "wind_speed" in v else "x" for v in variables},
        "hourly": {"time": times, **{v: values[v] for v in variables}},
    }


TIMES = ["2025-11-01T00:00", "2025-11-01T01:00"]


def test_merge_builds_feature_columns_with_uv_wind():
    analysis = payload(
        [
            "wind_speed_10m",
            "wind_direction_10m",
            "boundary_layer_height",
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "surface_pressure",
        ],
        TIMES,
        {
            "wind_speed_10m": [10, 10],
            "wind_direction_10m": [0, 90],
            "boundary_layer_height": [100, 200],
            "temperature_2m": [20, 21],
            "relative_humidity_2m": [50, 51],
            "precipitation": [0, 0],
            "surface_pressure": [990, 991],
        },
    )
    forecast = payload(
        [
            "wind_speed_10m_previous_day1",
            "wind_direction_10m_previous_day1",
            "temperature_2m_previous_day1",
            "relative_humidity_2m_previous_day1",
            "precipitation_previous_day1",
        ],
        TIMES,
        {
            "wind_speed_10m_previous_day1": [5, None],
            "wind_direction_10m_previous_day1": [180, None],
            "temperature_2m_previous_day1": [19, None],
            "relative_humidity_2m_previous_day1": [40, None],
            "precipitation_previous_day1": [0, None],
        },
    )
    cams = payload(["pm2_5", "pm10"], TIMES, {"pm2_5": [80, 90], "pm10": [120, 130]})
    df = merge_openmeteo(analysis, forecast, cams)
    assert list(df["time"].astype(str)) == [
        "2025-11-01 00:00:00+00:00",
        "2025-11-01 01:00:00+00:00",
    ]
    assert df["wx_v"].iloc[0] == pytest.approx(-10)
    assert df["wx_u"].iloc[1] == pytest.approx(-10)
    assert df["fc_v"].iloc[0] == pytest.approx(5)
    assert np.isnan(df["fc_u"].iloc[1])
    assert df["wx_blh"].tolist() == [100, 200]
    assert df["cams_pm25"].tolist() == [80, 90]


def test_chunks_cover_range_without_overlap():
    parts = list(chunks("2024-02-01", "2024-08-15", days=90))
    assert parts[0] == ("2024-02-01", "2024-04-30")
    assert parts[-1][1] == "2024-08-15"
    assert all(a[1] < b[0] for a, b in zip(parts, parts[1:], strict=False))
