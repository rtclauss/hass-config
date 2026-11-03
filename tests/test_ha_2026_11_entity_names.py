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

    # This value is the Zigbee2MQTT device identifier used in an MQTT topic,
    # not Home Assistant's user-facing entity display name.
    assert matches == [
        "packages/inovelli_led_notifications.yaml:81: "
        "zigbee2mqtt/{{ state_attr(repeat.item, 'friendly_name') }}/set"
    ]


def test_migrated_templates_keep_entity_id_fallbacks() -> None:
    expected_helpers = {
        "packages/battery_alerts.yaml.disabled": "entity_name(entity_id) | default(entity_id, true)",
        "private_templates/alerts.yaml.tmpl": "entity_name(trigger.from_state.entity_id) | default(trigger.from_state.entity_id, true)",
        "private_templates/media_player.yaml.tmpl": "entity_name(trigger.entity_id) | default(trigger.entity_id, true)",
        "private_templates/plants.yaml.tmpl": "entity_name(plant.entity_id) | default(plant.entity_id, true)",
        "private_templates/weather.yaml.tmpl": "entity_name('sensor.nws_dakota_county_alerts') | default('sensor.nws_dakota_county_alerts', true)",
        "private_templates/zone.yaml.tmpl": "entity_name(entity_id) | default(entity_id, true)",
    }

    for relative_path, helper in expected_helpers.items():
        assert helper in (ROOT / relative_path).read_text(encoding="utf-8")
