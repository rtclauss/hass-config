from __future__ import annotations

from pathlib import Path

from water_meter import calibrate
from water_meter.config import CalibrationConfig, save_calibration_config


def test_write_config_uses_defaults_when_no_existing_file(tmp_path: Path) -> None:
    config_path = tmp_path / "calibration.json"

    config = calibrate.write_config(config_path, roi=(1, 2, 3, 4), digit_boxes=[(1, 2, 3, 4)])

    assert config.decimal_places == 0
    assert config.low_confidence_ok_indexes == ()
    assert config.nominal_interval_seconds == 600.0


def test_write_config_preserves_every_existing_field_on_recalibration(tmp_path: Path) -> None:
    # Regression test: recalibrating (redrawing the ROI/digit boxes after a
    # camera move) used to silently reset decimal_places and
    # low_confidence_ok_indexes to their dataclass defaults instead of
    # carrying them over from the existing config, like every other field
    # here already does. On the real deployed meter (decimal_places=1) this
    # would make every raw reading 10x too large and leave the reader
    # permanently rejecting against its own baseline.
    config_path = tmp_path / "calibration.json"
    existing = CalibrationConfig(
        roi=(10, 20, 30, 40),
        digit_boxes=((10, 20, 5, 5),),
        digit_count=1,
        excluded_digit_indexes=(0,),
        warmup_seconds=2.5,
        frames_to_grab=6,
        frames_to_discard=3,
        max_gallons_per_interval=250.0,
        stuck_after_hours=12.0,
        history_limit=100,
        ssocr_args=("-d", "8"),
        decimal_places=1,
        low_confidence_ok_indexes=(0, 1),
        nominal_interval_seconds=300.0,
    )
    save_calibration_config(config_path, existing)

    # Simulate rerunning `calibrate` after the camera moved: new ROI/boxes,
    # same config file.
    config = calibrate.write_config(
        config_path, roi=(11, 21, 31, 41), digit_boxes=[(11, 21, 6, 6)]
    )

    assert config.roi == (11, 21, 31, 41)  # the new geometry was applied
    assert config.decimal_places == 1  # ...but everything else survived
    assert config.low_confidence_ok_indexes == (0, 1)
    assert config.nominal_interval_seconds == 300.0
    assert config.excluded_digit_indexes == (0,)
    assert config.warmup_seconds == 2.5
    assert config.frames_to_grab == 6
    assert config.frames_to_discard == 3
    assert config.max_gallons_per_interval == 250.0
    assert config.stuck_after_hours == 12.0
    assert config.history_limit == 100
    assert config.ssocr_args == ("-d", "8")
