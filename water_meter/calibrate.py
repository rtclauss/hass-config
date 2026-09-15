from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import capture, ocr
from .config import (
    DEFAULT_FRAMES_TO_DISCARD,
    DEFAULT_FRAMES_TO_GRAB,
    DEFAULT_LIGHT_WARMUP_SECONDS,
    DEFAULT_NOMINAL_INTERVAL_SECONDS,
    CalibrationConfig,
    connection_config_from_env,
    load_calibration_config,
    save_calibration_config,
)

LOG = logging.getLogger(__name__)


def capture_reference_frame(output_path: Path) -> None:
    """Step 1, run on the Pi: grab one frame with the light forced on.

    The Pi runs Raspberry Pi OS Lite (headless, no display), so this step
    only captures - drawing boxes happens afterwards on a workstation that
    actually has a screen (step below).
    """
    connection = connection_config_from_env()
    capture.set_light(connection, on=True)
    try:
        import time

        time.sleep(DEFAULT_LIGHT_WARMUP_SECONDS)
        frame = capture.grab_stable_frame(
            connection.camera_device,
            frames_to_grab=DEFAULT_FRAMES_TO_GRAB,
            frames_to_discard=DEFAULT_FRAMES_TO_DISCARD,
        )
    finally:
        capture.set_light(connection, on=False)
    capture.save_image(frame, output_path)
    LOG.info("Saved reference frame to %s - copy it to a workstation for step 2", output_path)


def pick_boxes_interactively(image_path: Path) -> tuple[tuple[int, int, int, int], list[tuple[int, int, int, int]]]:
    """Step 2, run on a workstation with a display.

    Uses OpenCV's built-in interactive rectangle selector (cv2.selectROI) -
    drag with the mouse, Enter/Space to confirm, Esc to stop adding boxes.
    No custom drawing UI needed.
    """
    import cv2

    image = cv2.imread(str(image_path))
    if image is None:
        raise SystemExit(f"Could not read image: {image_path}")

    print("Draw the overall digit-strip ROI, then press Enter/Space.")
    roi = cv2.selectROI("Water meter ROI", image, showCrosshair=True)
    cv2.destroyWindow("Water meter ROI")
    x, y, w, h = (int(v) for v in roi)
    if w == 0 or h == 0:
        raise SystemExit("No ROI selected")
    roi_crop = image[y : y + h, x : x + w]

    print(
        "Now draw a box around each digit, left-to-right, pressing Enter/Space after "
        "each one. Press Esc (without dragging) when you've boxed every digit."
    )
    digit_boxes: list[tuple[int, int, int, int]] = []
    while True:
        box = cv2.selectROI("Digit box (Esc when done)", roi_crop, showCrosshair=True)
        bx, by, bw, bh = (int(v) for v in box)
        if bw == 0 or bh == 0:
            break
        digit_boxes.append((x + bx, y + by, bw, bh))
    cv2.destroyWindow("Digit box (Esc when done)")

    return (x, y, w, h), digit_boxes


def write_config(
    config_path: Path,
    roi: tuple[int, int, int, int],
    digit_boxes: list[tuple[int, int, int, int]],
) -> CalibrationConfig:
    existing: CalibrationConfig | None = None
    if config_path.exists():
        try:
            existing = load_calibration_config(config_path)
        except (OSError, ValueError):
            existing = None

    config = CalibrationConfig(
        roi=roi,
        digit_boxes=tuple(digit_boxes),
        digit_count=len(digit_boxes),
        excluded_digit_indexes=existing.excluded_digit_indexes if existing else (),
        warmup_seconds=existing.warmup_seconds if existing else DEFAULT_LIGHT_WARMUP_SECONDS,
        frames_to_grab=existing.frames_to_grab if existing else DEFAULT_FRAMES_TO_GRAB,
        frames_to_discard=existing.frames_to_discard if existing else DEFAULT_FRAMES_TO_DISCARD,
        max_gallons_per_interval=existing.max_gallons_per_interval if existing else 500.0,
        stuck_after_hours=existing.stuck_after_hours if existing else 24.0,
        history_limit=existing.history_limit if existing else 200,
        ssocr_args=existing.ssocr_args if existing else (),
        # Every field here must be preserved from `existing`, not left to
        # CalibrationConfig's dataclass defaults - a rerun against this
        # documented meter's config would otherwise silently drop
        # decimal_places (1), making every raw reading 10x too large and
        # leaving the reader permanently rejecting against its own baseline.
        decimal_places=existing.decimal_places if existing else 0,
        low_confidence_ok_indexes=existing.low_confidence_ok_indexes if existing else (),
        nominal_interval_seconds=(
            existing.nominal_interval_seconds if existing else DEFAULT_NOMINAL_INTERVAL_SECONDS
        ),
    )
    save_calibration_config(config_path, config)
    return config


def test_read(image_path: Path, config: CalibrationConfig) -> str:
    import cv2

    image = cv2.imread(str(image_path))
    digit_crops = capture.crop_boxes(image, config.digit_boxes)
    return ocr.read_digits(image_path, digit_crops, config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the water meter ROI and digit boxes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser(
        "capture-only", help="Run on the Pi: grab one reference frame with the light on."
    )
    capture_parser.add_argument("-o", "--output", type=Path, required=True)

    calibrate_parser = subparsers.add_parser(
        "calibrate", help="Run on a workstation: draw the ROI and digit boxes."
    )
    calibrate_parser.add_argument("--image", type=Path, required=True)
    calibrate_parser.add_argument("--write-config", type=Path, required=True)
    calibrate_parser.add_argument(
        "--test", action="store_true", help="Run a test OCR pass against --image after writing config."
    )

    args = parser.parse_args()
    logging.basicConfig(level="INFO")

    if args.command == "capture-only":
        capture_reference_frame(args.output)
        return

    roi, digit_boxes = pick_boxes_interactively(args.image)
    config = write_config(args.write_config, roi, digit_boxes)
    LOG.info("Wrote calibration to %s: roi=%s digits=%d", args.write_config, config.roi, config.digit_count)

    if args.test:
        digits = test_read(args.image, config)
        print(f"Test read: {digits!r} - confirm this matches the physical meter.")


if __name__ == "__main__":
    main()
