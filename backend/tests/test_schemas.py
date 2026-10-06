from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.schemas import (
    AqiValue,
    Band,
    BestWindow,
    DriverGroup,
    ForecastHour,
    ForecastResponse,
    IndexQuantiles,
    Message,
    Pollutant,
    Quantiles,
    ReplayHour,
    ReplayObservation,
    Verdict,
)

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
