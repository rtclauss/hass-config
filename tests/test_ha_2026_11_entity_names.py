from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOTS = ("packages", "private_templates", "lovelace", "appdaemon")
DEPRECATED_NAME_READ = re.compile(
    r"state_attr\([^\n]*?['\"]friendly_name['\"]|\.attributes\.friendly_name"
)


def test_user_facing_templates_use_entity_name_helper() -> None:
    matches: list[str] = []

    for root_name in CONFIG_ROOTS:
        for path in (ROOT / root_name).rglob("*"):
            if (
                not path.is_file()
                or "custom_components" in path.parts
                or path.suffix not in {".yaml", ".tmpl", ".disabled", ".py"}
            ):
                continue

            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if DEPRECATED_NAME_READ.search(line):
                    matches.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")

    # friendly_name is retained only for compatibility in 2026.11 and is
    # planned for deprecation, so no config may read it.
    assert matches == []


def test_zigbee2mqtt_topics_use_integration_device_name() -> None:
    # The Zigbee2MQTT friendly_name is an MQTT contract. Home Assistant renames
    # write name_by_user or entity overrides, so topics must come from the
    # integration-supplied device name instead of any HA display name.
    text = (ROOT / "packages/inovelli_led_notifications.yaml").read_text(
        encoding="utf-8"
    )

    assert "zigbee2mqtt/{{ device_attr(repeat.item, 'name') }}/set" in text
    assert "friendly_name" not in text.split("mqtt.publish", 1)[1].split("\n\n", 1)[0]


def test_migrated_templates_keep_entity_id_fallbacks() -> None:
    expected_helpers = {
        "packages/battery_alerts.yaml.disabled": "device_name(entity_id)",
        "private_templates/alerts.yaml.tmpl": "device_name(trigger.from_state.entity_id)",
        "private_templates/media_player.yaml.tmpl": "device_name(trigger.entity_id)",
        "private_templates/plants.yaml.tmpl": "entity_name(plant.entity_id) | default(plant.entity_id, true)",
        "private_templates/weather.yaml.tmpl": "entity_name('sensor.nws_dakota_county_alerts') | default('sensor.nws_dakota_county_alerts', true)",
        "private_templates/zone.yaml.tmpl": "device_name(entity_id)",
    }

    for relative_path, helper in expected_helpers.items():
        assert helper in (ROOT / relative_path).read_text(encoding="utf-8")
