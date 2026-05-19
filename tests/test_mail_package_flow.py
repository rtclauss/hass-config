from pathlib import Path


ZIGBEE_ZWAVE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zigbee_zwave.yaml"


def _package_text() -> str:
    return ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")


def _automation_block(automation_id: str) -> str:
    lines = _package_text().splitlines()
    id_line = f"  - id: {automation_id}"
    start = None

    for index, line in enumerate(lines):
        if line != id_line:
            continue
        for candidate in range(index, -1, -1):
            if lines[candidate].startswith("  - "):
                start = candidate
                break
        if start is not None:
            break

    if start is None:
        raise AssertionError(f"Could not find automation block {automation_id!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - "):
            end = index
            break

    return "\n".join(lines[start:end])


def test_mail_package_state_helper_distinguishes_delivery_outcomes() -> None:
    text = _package_text()

    assert "mail_package_state:" in text
    for option in (
        "idle",
        "mail_delivered",
        "package_delivered",
        "mail_and_package_delivered",
        "retrieved",
        "source_unavailable",
    ):
        assert f"      - {option}" in text
    assert "    initial: idle" not in text


def test_mail_delivery_flow_uses_mail_and_packages_without_spamming() -> None:
    block = _automation_block("mail_delivered")

    for entity_id in (
        "binary_sensor.usps_mail_delivered",
        "binary_sensor.usps_image_updated",
        "binary_sensor.amazon_image_updated",
        "sensor.mail_amazon_packages_delivered",
        "sensor.mail_fedex_delivered",
        "sensor.mail_ups_delivered",
        "sensor.mail_usps_mail",
        "sensor.mail_usps_packages",
    ):
        assert entity_id in block

    assert "mode: queued" in block
    assert "next_delivery_state" in block
    assert "current_delivery_state not in" in block
    assert "next_delivery_state," in block
    assert "'retrieved'" in block


def test_mail_delivery_uses_only_delivered_package_counters() -> None:
    block = _automation_block("mail_delivered")
    package_sources = block[
        block.index("      package_source_entities:") : block.index("      source_entities:")
    ]

    for entity_id in (
        "sensor.mail_amazon_packages_delivered",
        "sensor.mail_fedex_delivered",
        "sensor.mail_ups_delivered",
    ):
        assert entity_id in package_sources

    for scheduled_entity_id in (
        "sensor.mail_amazon_packages",
        "sensor.mail_fedex_packages",
        "sensor.mail_ups_packages",
        "sensor.mail_usps_packages",
    ):
        assert f"        - {scheduled_entity_id}\n" not in package_sources


def test_mailbox_open_marks_retrieval_when_delivery_is_pending() -> None:
    block = _automation_block("mail_delivered")

    assert "id: mailbox-open" in block
    assert "entity_id: input_select.mail_package_state" in block
    assert "option: retrieved" in block
    assert "pending mail/package state cleared" in block
    assert "action: input_boolean.turn_off" in block


def test_mail_delivery_degrades_when_sources_or_cameras_are_unavailable() -> None:
    block = _automation_block("mail_delivered")

    assert "source_unavailable" in block
    assert "states(entity_id) not in ['unavailable', 'unknown']" in block
    assert "delivery_camera" in block
    assert "camera.mail_amazon_delivery_camera" in block
    assert "camera.mail_generic_delivery_camera" in block
    assert 'value_template: "{{ delivery_camera | trim != \'\' }}"' in block


def test_mail_reset_clears_compatibility_boolean_and_rich_state() -> None:
    block = _automation_block("reset_mail_delivery")

    assert "entity_id: input_boolean.mail_delivered" in block
    assert "entity_id: input_select.mail_package_state" in block
    assert "option: idle" in block
