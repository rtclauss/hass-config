from __future__ import annotations

from pathlib import Path
import sys
import types

import pytest

from water_meter import calibrate, capture, ocr
from water_meter.config import CalibrationConfig, save_calibration_config


def test_write_config_uses_defaults_when_no_existing_file(tmp_path: Path) -> None:
    config_path = tmp_path / "calibration.json"

    config = calibrate.write_config(config_path, roi=(1, 2, 3, 4), digit_boxes=[(1, 2, 3, 4)])

    assert config.decimal_places == 0
    assert config.low_confidence_ok_indexes == ()
    assert config.nominal_interval_seconds == 1200.0


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


def _install_fake_cv2(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.imread = lambda path: "fake-image"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)


def test_test_read_forwards_the_configured_fallback_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression test: --test used to only ever exercise ssocr, since
    # test_read never passed templates_dir/vlm_host through to
    # ocr.read_digits - on the documented glare-affected meter, any ssocr
    # hiccup during --test failed immediately instead of exercising the
    # fallback chain the real deployed reader actually uses.
    _install_fake_cv2(monkeypatch)
    monkeypatch.setattr(capture, "crop_boxes", lambda image, boxes: ["crop"])
    monkeypatch.setattr(capture, "crop_roi", lambda image, roi: "fake-roi-crop")
    saved_images: list[tuple[object, Path]] = []
    monkeypatch.setattr(capture, "save_image", lambda image, path: saved_images.append((image, path)))
    captured: dict = {}

    def _fake_read_digits(image_path: Path, digit_crops: object, config: object, **kwargs: object) -> str:
        captured["image_path"] = image_path
        captured.update(kwargs)
        return "12345678"

    monkeypatch.setattr(ocr, "read_digits", _fake_read_digits)
    config = CalibrationConfig(
        roi=(0, 0, 10, 10),
        digit_boxes=((0, 0, 5, 5),),
        digit_count=1,
        excluded_digit_indexes=(),
        warmup_seconds=0.0,
        frames_to_grab=1,
        frames_to_discard=0,
        max_gallons_per_interval=500.0,
        stuck_after_hours=24.0,
        history_limit=200,
        ssocr_args=(),
    )

    result = calibrate.test_read(
        tmp_path / "reference.jpg",
        config,
        templates_dir=tmp_path / "templates",
        vlm_host="truenas.local:30068",
        vlm_model="qwen3-vl:4b",
        vlm_timeout=480.0,
    )

    assert result == "12345678"
    assert captured["templates_dir"] == tmp_path / "templates"
    assert captured["vlm_host"] == "truenas.local:30068"
    assert captured["vlm_model"] == "qwen3-vl:4b"
    assert captured["vlm_timeout"] == 480.0
    # Regression: must pass the ROI-cropped image to OCR, not the raw
    # reference frame - that's what reader.run_once actually feeds ssocr/the
    # VLM in production (latest_crop.jpg, not the full frame).
    expected_crop_path = tmp_path / "reference_roi_crop.jpg"
    assert captured["image_path"] == expected_crop_path
    assert saved_images == [("fake-roi-crop", expected_crop_path)]
