import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ingest.http import SourceError
from ingest.openmeteo import fetch_cams, fetch_weather, parse_cams, parse_weather

SAMPLES = Path(__file__).parent / "samples"
WEATHER = json.loads((SAMPLES / "openmeteo_weather.json").read_text(encoding="utf-8"))
AIR = json.loads((SAMPLES / "openmeteo_air_quality.json").read_text(encoding="utf-8"))


def test_parse_weather_rows_are_utc_and_complete():
    rows = parse_weather(WEATHER)
    assert len(rows) == len(WEATHER["hourly"]["time"])
    assert rows[0].time == datetime.fromisoformat(WEATHER["hourly"]["time"][0]).replace(tzinfo=UTC)
    assert rows[0].blh_m == WEATHER["hourly"]["boundary_layer_height"][0]


def test_parse_weather_converts_kmh_to_ms():
    rows = parse_weather(WEATHER)
    assert WEATHER["hourly_units"]["wind_speed_10m"] == "km/h"
    assert rows[0].wind_speed_ms == pytest.approx(WEATHER["hourly"]["wind_speed_10m"][0] / 3.6)


def test_parse_cams_converts_co_to_mg():
    rows = parse_cams(AIR)
    assert AIR["hourly_units"]["carbon_monoxide"] == "μg/m³"
    assert rows[0].co_mg_m3 == pytest.approx(AIR["hourly"]["carbon_monoxide"][0] / 1000)
    assert rows[0].pm25 == AIR["hourly"]["pm2_5"][0]


def test_missing_values_stay_none():
    payload = json.loads(json.dumps(AIR))
    payload["hourly"]["pm2_5"][0] = None
    assert parse_cams(payload)[0].pm25 is None


def test_mismatched_lengths_rejected():
    payload = json.loads(json.dumps(WEATHER))
    payload["hourly"]["temperature_2m"].pop()
    with pytest.raises(SourceError, match="length"):
        parse_weather(payload)


def test_non_utc_response_rejected():
    payload = {**WEATHER, "utc_offset_seconds": 19800}
    with pytest.raises(SourceError, match="UTC"):
        parse_weather(payload)


def test_fetch_requests_utc_and_variables():
    calls = []

    def fake_get(url, params):
        calls.append((url, params))
        return WEATHER if "air-quality" not in url else AIR

    assert len(fetch_weather(28.75, 77.117, get=fake_get)) == 48
    assert len(fetch_cams(28.75, 77.117, get=fake_get)) == 48
    (w_url, w_params), (a_url, a_params) = calls
    assert w_params["timezone"] == "UTC" and a_params["timezone"] == "UTC"
    assert "boundary_layer_height" in w_params["hourly"]
    assert "carbon_monoxide" in a_params["hourly"]
    assert a_url.startswith("https://air-quality-api.open-meteo.com")
