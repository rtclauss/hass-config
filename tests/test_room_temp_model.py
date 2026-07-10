"""Unit tests for the external room-temperature model core.

room_temp_model_service/model.py is pure Python (pandas/sklearn/astral are
lazily imported inside the functions that need them), so the feature-assembly
and prediction paths are testable without any of the heavy deps. The
training-data tests need pandas and skip cleanly when it is absent.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

MODEL_PATH = Path(__file__).resolve().parents[1] / "room_temp_model_service" / "model.py"


def _load_model_module():
    spec = importlib.util.spec_from_file_location("room_temp_model", MODEL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["room_temp_model"] = module
    spec.loader.exec_module(module)
    return module


model = _load_model_module()

LAT, LON = 44.761712, -93.203609

ROOMS = [
    {
        "name": "owner_suite",
        "temp_sensors": ["sensor.owner_suite_tph_temperature", "sensor.bedroom_temperature"],
        "humidity_sensors": ["sensor.owner_suite_tph_humidity"],
        "confidence_sensor": "sensor.bedroom_room_confidence",
    }
]


@pytest.fixture
def rtm(tmp_path):
    return model.RoomTempModel({
        "model_dir": str(tmp_path),
        "latitude": LAT,
        "longitude": LON,
        "min_training_samples": 10,
        "influxdb": {"host": "x", "port": 8086, "database": "d"},
        "rooms": ROOMS,
    })


def _raw(**overrides):
    base = {
        "room_temp": 72.0,
        "room_humidity": 45.0,
        "outside_temp": 80.0,
        "outside_humidity": 50.0,
        "cloud_cover": 40.0,
        "wind_speed": 5.0,
        "uv_index": 3.0,
        "precipitation": 0.0,
        "occupancy": 100.0,
        "hvac_heating": 0.0,
        "hvac_cooling": 1.0,
        "room_temp_rate_15m": 0.02,
        "outside_delta_3h": 1.5,
        "forecast": {},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- sun_position


def test_sun_position_is_high_at_local_solar_noon():
    # ~17:30 UTC ≈ 12:30 local (CDT) on the summer solstice.
    elev, azim = model.sun_position(LAT, LON, datetime(2026, 6, 21, 17, 30, tzinfo=timezone.utc))
    assert elev > 30.0
    assert 0.0 <= azim <= 360.0


def test_sun_position_is_below_horizon_at_local_midnight():
    # ~06:00 UTC ≈ 01:00 local.
    elev, _ = model.sun_position(LAT, LON, datetime(2026, 6, 21, 6, 0, tzinfo=timezone.utc))
    assert elev < 0.0


def test_sun_position_winter_noon_lower_than_summer_noon():
    summer, _ = model.sun_position(LAT, LON, datetime(2026, 6, 21, 17, 30, tzinfo=timezone.utc))
    winter, _ = model.sun_position(LAT, LON, datetime(2026, 12, 21, 18, 0, tzinfo=timezone.utc))
    assert winter < summer


def test_sun_position_falls_back_when_astral_missing(monkeypatch):
    """The pure-math fallback must still return sane values (no astral installed)."""
    monkeypatch.setitem(sys.modules, "astral", None)  # force the except branch
    elev, azim = model.sun_position(LAT, LON, datetime(2026, 6, 21, 17, 30, tzinfo=timezone.utc))
    assert isinstance(elev, float) and isinstance(azim, float)
    assert -90.0 <= elev <= 90.0
    assert 0.0 <= azim <= 360.0


# --------------------------------------------------------------- _assemble_row


def test_assemble_row_emits_every_horizon_feature(rtm):
    row = rtm._assemble_row(_raw(), datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc))
    for h in model.HORIZONS:
        for stem in ("cloud_cover", "outside_temp", "outside_humidity",
                     "wind_speed", "precipitation", "uv_index",
                     "sun_elevation", "sun_azimuth_sin", "sun_azimuth_cos"):
            assert f"{stem}_{h}m" in row, f"missing {stem}_{h}m"


def test_assemble_row_forecast_missing_falls_back_to_current_values(rtm):
    row = rtm._assemble_row(_raw(forecast={}), datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc))
    assert row["cloud_cover_60m"] == 40.0
    assert row["outside_temp_60m"] == 80.0
    assert row["wind_speed_30m"] == 5.0


def test_assemble_row_uses_forecast_when_present(rtm):
    fc = {"60": {"cloud_cover": 10, "temperature": 90, "humidity": 30,
                 "wind_speed": 12, "uv_index": 8, "precipitation": 0.5}}
    row = rtm._assemble_row(_raw(forecast=fc), datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc))
    assert row["cloud_cover_60m"] == 10
    assert row["outside_temp_60m"] == 90
    assert row["precipitation_60m"] == 0.5
    # A horizon with no forecast entry still falls back to current.
    assert row["cloud_cover_15m"] == 40.0


def test_assemble_row_cyclic_encodings_lie_on_unit_circle(rtm):
    row = rtm._assemble_row(_raw(), datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc))
    for s, c in (("hour_sin", "hour_cos"), ("doy_sin", "doy_cos"),
                 ("sun_azimuth_sin", "sun_azimuth_cos")):
        assert math.isclose(row[s] ** 2 + row[c] ** 2, 1.0, abs_tol=1e-9)


def test_assemble_row_preserves_none_humidity_rather_than_zeroing(rtm):
    """None must stay None so the caller's fillna is explicit, not a silent 0."""
    row = rtm._assemble_row(_raw(room_humidity=None), datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc))
    assert row["room_humidity"] is None


def test_assemble_row_defaults_occupancy_and_rate_to_zero(rtm):
    row = rtm._assemble_row(
        _raw(occupancy=None, room_temp_rate_15m=None, outside_delta_3h=None),
        datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc),
    )
    assert row["occupancy"] == 0
    assert row["room_temp_rate_15m"] == 0
    assert row["outside_delta_3h"] == 0


# ------------------------------------------------------------------- predict()


def test_predict_without_models_uses_linear_fallback(rtm):
    out = rtm.predict("owner_suite", _raw(room_temp=70.0, room_temp_rate_15m=0.02))
    assert out["prediction_source"] == "fallback_linear"
    assert out["t15"] == pytest.approx(70.0 + 0.02 * 15)
    assert out["t30"] == pytest.approx(70.0 + 0.02 * 30)
    assert out["t60"] == pytest.approx(70.0 + 0.02 * 60)


def test_predict_without_models_treats_missing_rate_as_flat(rtm):
    out = rtm.predict("owner_suite", _raw(room_temp=70.0, room_temp_rate_15m=None))
    assert out["t60"] == pytest.approx(70.0)


def test_predict_returns_none_for_non_numeric_room_temp(rtm):
    assert rtm.predict("owner_suite", _raw(room_temp="unavailable")) is None
    assert rtm.predict("owner_suite", _raw(room_temp=None)) is None


class _StubModel:
    """Stands in for a fitted GradientBoostingRegressor; returns a fixed delta."""

    def __init__(self, delta):
        self.delta = delta
        self.calls = 0

    def predict(self, X):
        self.calls += 1
        return [self.delta]


def test_predict_adds_model_delta_to_current_temp(rtm):
    """The model predicts a DELTA; predict() must add it to the current temp."""
    rtm.models["owner_suite"] = {15: _StubModel(0.5), 30: _StubModel(1.0), 60: _StubModel(2.5)}
    rtm.meta["owner_suite"] = {"feature_cols": None, "trained_at": "2026-07-09T00:00:00"}

    out = rtm.predict("owner_suite", _raw(room_temp=72.0))

    assert out["prediction_source"] == "gbr_model"
    assert out["t15"] == pytest.approx(72.5)
    assert out["t30"] == pytest.approx(73.0)
    assert out["t60"] == pytest.approx(74.5)


def test_predict_surfaces_cv_metrics_and_trained_at(rtm):
    rtm.models["owner_suite"] = {h: _StubModel(0.0) for h in model.HORIZONS}
    rtm.meta["owner_suite"] = {
        "feature_cols": None,
        "trained_at": "2026-07-09T00:00:00",
        "rmse_60m_cv_mean": 1.23,
        "n_samples": 4242,
    }
    out = rtm.predict("owner_suite", _raw())
    assert out["rmse_60m_cv_mean"] == 1.23
    assert out["trained_at"] == "2026-07-09T00:00:00"
    assert out["n_training_samples"] == 4242


def test_predict_selects_only_trained_feature_cols(rtm):
    """feature_cols drives the vector, so extra candidate features are ignored."""
    pytest.importorskip("pandas")
    captured = {}

    class _Capturing:
        def predict(self, X):
            captured["n"] = len(X[0])
            return [1.0]

    cols = ["room_temp", "cloud_cover", "sun_elevation"]
    rtm.models["owner_suite"] = {h: _Capturing() for h in model.HORIZONS}
    rtm.meta["owner_suite"] = {"feature_cols": cols}

    out = rtm.predict("owner_suite", _raw(room_temp=72.0))

    assert captured["n"] == len(cols)
    assert out["t60"] == pytest.approx(73.0)


# -------------------------------------------------- _build_training_data (pandas)


def _install_fake_influx(rtm, monkeypatch, numeric: dict, hvac=None):
    """Point the model's InfluxDB reads at in-memory pandas Series."""
    import pandas as pd

    monkeypatch.setattr(rtm, "_influx_client", lambda: object())
    monkeypatch.setattr(rtm, "_query_generic", lambda _c, entity_id, **kw: numeric.get(entity_id))
    monkeypatch.setattr(
        rtm, "_query_categorical",
        lambda _c, entity_id, **kw: (hvac if hvac is not None else pd.Series(dtype=object)),
    )


def _index(n=240):
    import pandas as pd
    return pd.date_range("2026-06-01", periods=n, freq="5min", tz="UTC")


def _series(idx, value):
    import pandas as pd
    return pd.Series([value] * len(idx), index=idx, dtype=float)


def _base_numeric(idx, **overrides):
    data = {
        "sensor.owner_suite_tph_temperature": _series(idx, 72.0),
        "sensor.bedroom_temperature": _series(idx, 74.0),
        "sensor.owner_suite_tph_humidity": _series(idx, 45.0),
        "sensor.bedroom_room_confidence": _series(idx, 100.0),
        "sensor.outside_temperature": _series(idx, 80.0),
        "sensor.outside_humidity": _series(idx, 50.0),
        "sensor.tomorrow_io_the_brewery_cloud_cover": _series(idx, 40.0),
        "sensor.pinehotties_wind_speed": _series(idx, 5.0),
        "sensor.pinehotties_hourly_rain": _series(idx, 0.0),
        "sensor.pinehotties_uv_index": _series(idx, 3.0),
    }
    data.update(overrides)
    return data


def test_room_temp_is_mean_of_member_sensors(rtm, monkeypatch):
    pytest.importorskip("pandas")
    idx = _index()
    _install_fake_influx(rtm, monkeypatch, _base_numeric(idx))

    df, _ = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])

    assert df is not None
    # mean(72, 74) == 73
    assert df["room_temp"].round(3).eq(73.0).all()


def test_room_temp_uses_single_member_when_other_has_no_history(rtm, monkeypatch):
    pytest.importorskip("pandas")
    idx = _index()
    numeric = _base_numeric(idx)
    numeric["sensor.bedroom_temperature"] = None  # ecobee not yet recording

    _install_fake_influx(rtm, monkeypatch, numeric)
    df, _ = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])

    assert df is not None
    assert df["room_temp"].round(3).eq(72.0).all()


def test_humidity_sensors_list_is_averaged(rtm, monkeypatch):
    pytest.importorskip("pandas")
    idx = _index()
    numeric = _base_numeric(idx)
    numeric["sensor.second_humidity"] = _series(idx, 55.0)
    rtm.rooms["owner_suite"]["humidity_sensors"] = [
        "sensor.owner_suite_tph_humidity", "sensor.second_humidity",
    ]

    _install_fake_influx(rtm, monkeypatch, numeric)
    df, _ = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])

    assert df["room_humidity"].round(3).eq(50.0).all()  # mean(45, 55)


def test_humidity_sensor_singular_key_is_backwards_compatible(rtm, monkeypatch):
    pytest.importorskip("pandas")
    idx = _index()
    cfg = dict(rtm.rooms["owner_suite"])
    cfg.pop("humidity_sensors")
    cfg["humidity_sensor"] = "sensor.owner_suite_tph_humidity"

    _install_fake_influx(rtm, monkeypatch, _base_numeric(idx))
    df, _ = rtm._build_training_data("owner_suite", cfg)

    assert df["room_humidity"].round(3).eq(45.0).all()


def test_junk_zero_outside_humidity_blanks_the_paired_temperature(rtm, monkeypatch):
    """outside_* emit a literal 0 when the weather source drops; drop those rows."""
    pytest.importorskip("pandas")
    idx = _index()
    numeric = _base_numeric(idx)
    hum = _series(idx, 50.0)
    temp = _series(idx, 80.0)
    hum.iloc[100] = 0.0   # junk marker
    temp.iloc[100] = 0.0  # junk temperature that must not be learned
    numeric["sensor.outside_humidity"] = hum
    numeric["sensor.outside_temperature"] = temp

    _install_fake_influx(rtm, monkeypatch, numeric)
    df, _ = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])

    # The junk 0 was blanked and forward-filled from the previous good sample.
    assert (df["outside_temp"] > 0).all()
    assert (df["outside_humidity"] > 0).all()


def test_real_subzero_outside_temp_survives_the_junk_filter(rtm, monkeypatch):
    """A genuine winter -5°F reading carries real humidity and must be kept."""
    pytest.importorskip("pandas")
    idx = _index()
    numeric = _base_numeric(idx)
    numeric["sensor.outside_temperature"] = _series(idx, -5.0)
    numeric["sensor.outside_humidity"] = _series(idx, 70.0)

    _install_fake_influx(rtm, monkeypatch, numeric)
    df, _ = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])

    assert df is not None and len(df) > 0
    assert df["outside_temp"].eq(-5.0).all()


def test_coverage_filter_drops_a_sensor_with_no_history_without_emptying_the_set(rtm, monkeypatch):
    """A brand-new sensor (all-NaN) must be dropped, not collapse training."""
    pytest.importorskip("pandas")
    idx = _index()
    numeric = _base_numeric(idx)
    numeric["sensor.pinehotties_wind_speed"] = None
    numeric["sensor.pinehotties_hourly_rain"] = None
    numeric["sensor.pinehotties_uv_index"] = None

    _install_fake_influx(rtm, monkeypatch, numeric)
    df, _ = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])

    assert df is not None and len(df) > 0, "no-history sensors collapsed the training set"
    for stem in ("wind_speed", "precipitation", "uv_index"):
        assert stem not in df.columns
        for h in model.HORIZONS:
            assert f"{stem}_{h}m" not in df.columns
    # Well-covered features survive.
    assert "cloud_cover" in df.columns
    assert "room_temp" in df.columns


def test_coverage_filter_keeps_a_mostly_populated_column(rtm, monkeypatch):
    pytest.importorskip("pandas")
    import numpy as np
    idx = _index()
    numeric = _base_numeric(idx)
    wind = _series(idx, 5.0)
    wind.iloc[:20] = np.nan  # ~92% coverage, above MIN_COVERAGE
    numeric["sensor.pinehotties_wind_speed"] = wind

    _install_fake_influx(rtm, monkeypatch, numeric)
    df, _ = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])

    assert "wind_speed" in df.columns


def test_targets_are_future_minus_current_temperature(rtm, monkeypatch):
    """The model learns a delta, not an absolute temperature."""
    pytest.importorskip("pandas")
    import numpy as np
    idx = _index()
    numeric = _base_numeric(idx)
    # Ramp both members by 0.1°F per 5-min slot -> mean also ramps 0.1/slot.
    ramp = np.arange(len(idx)) * 0.1
    import pandas as pd
    numeric["sensor.owner_suite_tph_temperature"] = pd.Series(72.0 + ramp, index=idx)
    numeric["sensor.bedroom_temperature"] = pd.Series(72.0 + ramp, index=idx)

    _install_fake_influx(rtm, monkeypatch, numeric)
    df, y = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])

    # T+60 == 12 slots ahead == +1.2°F
    assert y["delta_60"].reindex(df.index).round(3).eq(1.2).all()
    assert y["delta_15"].reindex(df.index).round(3).eq(0.3).all()


def test_fold_assignment_is_isoweek_modulo_five(rtm, monkeypatch):
    pytest.importorskip("pandas")
    idx = _index()
    _install_fake_influx(rtm, monkeypatch, _base_numeric(idx))
    df, _ = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])

    expected = df.index.isocalendar().week % 5
    assert df["fold"].tolist() == list(expected)
    assert df["fold"].between(0, 4).all()


def test_insufficient_history_returns_none(rtm, monkeypatch):
    pytest.importorskip("pandas")
    idx = _index(n=5)  # below min_training_samples=10
    _install_fake_influx(rtm, monkeypatch, _base_numeric(idx))
    df, y = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])
    assert df is None and y is None


def test_no_room_temp_history_returns_none(rtm, monkeypatch):
    pytest.importorskip("pandas")
    idx = _index()
    numeric = _base_numeric(idx)
    numeric["sensor.owner_suite_tph_temperature"] = None
    numeric["sensor.bedroom_temperature"] = None

    _install_fake_influx(rtm, monkeypatch, numeric)
    df, y = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])
    assert df is None and y is None


# ------------------------------------------------------------- train/infer parity


def test_every_trained_feature_can_be_produced_at_inference(rtm, monkeypatch):
    """The whole point of sharing feature code: inference must be able to supply
    every column training selected, or predict() would KeyError."""
    pytest.importorskip("pandas")
    idx = _index()
    _install_fake_influx(rtm, monkeypatch, _base_numeric(idx))

    df, _ = rtm._build_training_data("owner_suite", rtm.rooms["owner_suite"])
    feature_cols = [c for c in df.columns if c != "fold" and not c.startswith("delta_")]

    row = rtm._assemble_row(_raw(), datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc))

    missing = sorted(set(feature_cols) - set(row))
    assert not missing, f"inference cannot supply trained features: {missing}"
