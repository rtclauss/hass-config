from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIL_PACKAGES_PATH = ROOT / "packages" / "mail_packages.yaml"
ZIGBEE_ZWAVE_PATH = ROOT / "packages" / "zigbee_zwave.yaml"


def _automation_block(automation_id: str) -> str:
    text = MAIL_PACKAGES_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^  - id: {re.escape(automation_id)}\n(.*?)(?=^  - id: |^input_boolean:)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")
    return match.group(0)


def test_mail_delivered_helper_moved_to_mail_package_domain_package() -> None:
    mail_text = MAIL_PACKAGES_PATH.read_text(encoding="utf-8")
    zigbee_text = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")

    assert "input_boolean:\n  mail_delivered:" in mail_text
    assert "id: mail_delivered" not in zigbee_text
    assert re.search(r"^input_boolean:\n(?:  .+\n)*  mail_delivered:", zigbee_text, re.MULTILINE) is None


def test_mail_package_state_helper_distinguishes_delivery_lifecycle() -> None:
    text = MAIL_PACKAGES_PATH.read_text(encoding="utf-8")

    assert "input_select:\n  mail_package_delivery_state:" in text
    for state in ("clear", "expected", "delivered", "still_outside", "retrieved", "unavailable"):
        assert f"      - {state}" in text
    assert "input_button:\n  mail_package_mark_retrieved:" in text
    assert "input_datetime:\n  mail_package_last_delivery:" in text
    assert "mail_package_last_retrieved:" in text


def test_mail_package_delivery_uses_mailbox_and_carrier_sensors_without_duplicate_spam() -> None:
    block = _automation_block("mail_package_delivery_state")

    assert "mode: queued" in block
    assert "trigger: homeassistant" in block
    assert "id: startup_sync" in block
    assert "at: \"01:00:00\"" in block
    assert "id: daily_reset" in block
    assert "entity_id: binary_sensor.mailbox_contact" in block
    assert "sensor.mail_usps_mail" in block
    assert "sensor.mail_usps_packages" in block
    assert "sensor.mail_ups_packages" in block
    assert "sensor.mail_fedex_packages" in block
    assert "sensor.mail_amazon_packages" in block
    assert "sensor.mail_usps_delivered" in block
    assert "sensor.mail_ups_delivered" in block
    assert "sensor.mail_fedex_delivered" in block
    assert "sensor.mail_amazon_packages_delivered" in block
    assert "condition: state\n                entity_id: input_boolean.mail_delivered\n                state: \"off\"" in block
    assert "action: mail_and_packages.update_image" in block
    assert "continue_on_error: true" in block
    assert "option: clear" in block


def test_mail_package_notifications_are_actionable_and_camera_optional() -> None:
    block = _automation_block("mail_package_delivery_state")

    assert "event_type: mobile_app_notification_action" in block
    assert "action: MAIL_PACKAGE_RETRIEVED" in block
    assert "action: MAIL_PACKAGE_STILL_OUTSIDE" in block
    assert "camera_candidates:" in block
    assert "camera.mail_generic_delivery_camera" in block
    assert "camera.mail_amazon_delivery_camera" in block
    assert "camera.mail_usps_camera" in block
    assert "image: \"{{ '/api/camera_proxy/' ~ camera_entity }}\"" in block
    assert "persistent_notification.create" in block
    assert "message: clear_notification" in block


def test_mail_package_still_outside_reminder_escalates_once_after_delivery() -> None:
    block = _automation_block("mail_package_still_outside_reminder")

    assert "mode: single" in block
    assert "to: delivered" in block
    assert "minutes: 30" in block
    assert "option: still_outside" in block
    assert "notification_id: mail-package-delivery" in block
    assert "action: MAIL_PACKAGE_RETRIEVED" in block
