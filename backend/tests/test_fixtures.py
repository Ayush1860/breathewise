from backend.scripts.make_fixtures import FIXTURE_DIR, build_fixtures, dump

REQUIRED = {
    "stations.json",
    "aqi_current.fresh.json",
    "aqi_current.stale.json",
    "aqi_current.insufficient_data.json",
    "aqi_current.cams_fallback.json",
    "aqi_forecast.json",
    "aqi_forecast.stale.json",
    "advice.go.json",
    "advice.go_with_n95.json",
    "advice.avoid.json",
    "advice.reduce_exposure.json",
    "scoreboard.json",
    "metrics.json",
    "refresh.accepted.json",
    "refresh.rate_limited.json",
    "health.json",
    "replay/example.json",
}
REGEN = "run: uv run python -m backend.scripts.make_fixtures"


def test_generator_covers_every_required_state():
    assert REQUIRED <= set(build_fixtures())


def test_fixture_files_match_generator():
    for name, model in build_fixtures().items():
        path = FIXTURE_DIR / name
        assert path.exists(), f"{name} missing; {REGEN}"
        assert path.read_text(encoding="utf-8") == dump(model), f"{name} is stale; {REGEN}"


def test_no_orphan_fixture_files():
    on_disk = {p.relative_to(FIXTURE_DIR).as_posix() for p in FIXTURE_DIR.rglob("*.json")}
    assert on_disk == set(build_fixtures()), f"orphan fixtures; {REGEN}"


def test_stale_fixtures_are_flagged_stale():
    fixtures = build_fixtures()
    assert fixtures["aqi_current.stale.json"].stale is True
    assert fixtures["aqi_forecast.stale.json"].stale is True
    assert fixtures["aqi_current.fresh.json"].stale is False


def test_advice_fixtures_cover_every_verdict():
    fixtures = build_fixtures()
    expected = {
        "advice.go.json": ("GO", "healthy_adult", "q50"),
        "advice.go_with_n95.json": ("GO_WITH_N95", "healthy_adult", "q50"),
        "advice.avoid.json": ("AVOID", "respiratory", "q90"),
        "advice.reduce_exposure.json": ("REDUCE_EXPOSURE", "outdoor_worker", "q50"),
    }
    for name, (verdict, profile, basis) in expected.items():
        advice = fixtures[name]
        assert advice.verdict.value == verdict, name
        assert advice.basis == basis, name
        assert advice.profile.value == profile, name


def test_scoreboard_mae_ignores_missing_actuals():
    board = build_fixtures()["scoreboard.json"]
    h1 = [p for p in board.points if p.horizon_h == 1]
    assert any(p.actual is None for p in h1)
    assert board.per_horizon[0].n == sum(p.actual is not None for p in h1)
