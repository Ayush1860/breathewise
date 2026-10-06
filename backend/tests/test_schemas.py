import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.schemas import (
    AqiValue,
    Band,
    BestWindow,
    CurrentAqiResponse,
    DriverGroup,
    ForecastHour,
    ForecastResponse,
    IndexQuantiles,
    Message,
    Pollutant,
    Quantiles,
    RefreshResponse,
    ReplayHour,
    ReplayObservation,
    Verdict,
)

FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "fixtures"
T0 = datetime(2026, 10, 10, 4, 0, tzinfo=UTC)
MSG = Message(key="explain.falling.ventilation", params={"pollutant": "PM2.5"}, text="x")


def _hour(h: int) -> ForecastHour:
    return ForecastHour(
        target_time=T0 + timedelta(hours=h),
        horizon_h=h,
        pm25=Quantiles(q10=80, q50=100, q90=120),
        pm10=Quantiles(q10=140, q50=175, q90=210),
        index=IndexQuantiles(q10=263, q50=330, q90=346),
        band=Band.VERY_POOR,
        drivers={DriverGroup.VENTILATION: -12.5},
        explanation=MSG,
    )


def _forecast(hours: list[ForecastHour]) -> ForecastResponse:
    return ForecastResponse(
        generated_at=T0,
        station_id="dl-rohini",
        issued_at=T0,
        model_version="lgbm-v1-test",
        stale=False,
        age_minutes=5,
        summary=MSG,
        hours=hours,
    )


def test_quantiles_must_be_ordered():
    with pytest.raises(ValidationError, match="ordered"):
        Quantiles(q10=50, q50=40, q90=60)


def test_quantiles_accept_equal_values():
    assert Quantiles(q10=40, q50=40, q90=40).q50 == 40


def test_index_quantiles_must_be_ordered():
    with pytest.raises(ValidationError, match="ordered"):
        IndexQuantiles(q10=300, q50=200, q90=400)


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        Quantiles(q10=1, q50=2, q90=3, q99=4)


def test_aqi_ok_requires_value_band_and_dominant():
    with pytest.raises(ValidationError, match="requires"):
        AqiValue(status="ok", pollutants_present=[Pollutant.PM25])


def test_aqi_insufficient_must_not_carry_value():
    with pytest.raises(ValidationError, match="must not carry"):
        AqiValue(
            status="insufficient_data",
            aqi=120,
            band=Band.MODERATELY_POLLUTED,
            dominant_pollutant=Pollutant.PM25,
            pollutants_present=[Pollutant.PM25],
        )


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        BestWindow(
            start=datetime(2026, 10, 10, 4),
            end=datetime(2026, 10, 10, 6),
            worst_index=150,
            band=Band.MODERATELY_POLLUTED,
            improves_on_now=True,
        )


def test_datetimes_serialise_as_utc_z():
    window = BestWindow(
        start=T0,
        end=T0 + timedelta(hours=2),
        worst_index=150,
        band=Band.MODERATELY_POLLUTED,
        improves_on_now=True,
    )
    assert window.model_dump(mode="json")["start"] == "2026-10-10T04:00:00Z"


def test_best_window_end_must_follow_start():
    with pytest.raises(ValidationError, match="after start"):
        BestWindow(
            start=T0,
            end=T0,
            worst_index=150,
            band=Band.MODERATELY_POLLUTED,
            improves_on_now=False,
        )


def test_forecast_accepts_horizons_1_to_12():
    assert len(_forecast([_hour(h) for h in range(1, 13)]).hours) == 12


def test_forecast_rejects_out_of_order_horizons():
    hours = [_hour(h) for h in range(1, 13)]
    hours[3], hours[4] = hours[4], hours[3]
    with pytest.raises(ValidationError, match="horizons"):
        _forecast(hours)


def test_forecast_rejects_eleven_hours():
    with pytest.raises(ValidationError):
        _forecast([_hour(h) for h in range(1, 12)])


def test_message_key_must_be_dotted_lowercase():
    with pytest.raises(ValidationError):
        Message(key="Bad Key", text="x")


def test_replay_verdict_keys_must_be_profile_activity_pairs():
    with pytest.raises(ValidationError, match="profile:activity"):
        ReplayHour(
            time=T0,
            observed=ReplayObservation(pm25=150, pm10=260, index=300, band=Band.POOR),
            forecast_hours=[_hour(h) for h in range(1, 13)],
            summary=MSG,
            persistence_pm25=150,
            cams_pm25=110,
            verdicts={"nobody:walk": Verdict.GO},
        )


IST = timezone(timedelta(hours=5, minutes=30))


def test_non_utc_aware_datetime_is_normalised_to_utc():
    window = BestWindow(
        start=datetime(2026, 10, 10, 9, 30, tzinfo=IST),
        end=datetime(2026, 10, 10, 11, 30, tzinfo=IST),
        worst_index=150,
        band=Band.MODERATELY_POLLUTED,
        improves_on_now=True,
    )
    assert window.model_dump(mode="json")["start"] == "2026-10-10T04:00:00Z"


def test_infinity_and_nan_rejected():
    with pytest.raises(ValidationError):
        Quantiles(q10=1, q50=2, q90=float("inf"))
    with pytest.raises(ValidationError):
        ForecastHour(**{**_hour(1).model_dump(), "drivers": {"ventilation": float("nan")}})


def test_forecast_target_time_must_equal_issued_plus_horizon():
    hours = [_hour(h) for h in range(1, 13)]
    with pytest.raises(ValidationError, match="target_time"):
        ForecastResponse(**{**_forecast(hours).__dict__, "issued_at": T0 + timedelta(hours=1)})


def test_forecast_hour_band_must_match_median_index():
    with pytest.raises(ValidationError, match="band"):
        ForecastHour(**{**_hour(1).model_dump(), "band": Band.SEVERE})


def test_hourly_index_and_band_must_be_set_together():
    current = json.loads((FIXTURES / "aqi_current.fresh.json").read_text(encoding="utf-8"))
    current["hourly_band"] = None
    with pytest.raises(ValidationError, match="hourly_index"):
        CurrentAqiResponse.model_validate(current)


def test_dominant_pollutant_must_be_present():
    with pytest.raises(ValidationError, match="dominant_pollutant"):
        AqiValue(
            status="ok",
            aqi=120,
            band=Band.MODERATELY_POLLUTED,
            dominant_pollutant=Pollutant.SO2,
            pollutants_present=[Pollutant.PM25, Pollutant.PM10, Pollutant.NO2],
        )


def test_refused_refresh_requires_retry_after():
    with pytest.raises(ValidationError, match="retry_after_s"):
        RefreshResponse(accepted=False, message=MSG)
