from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Issue #1175: each Bond ceiling fan exposes a fan and a light entity. The
# registry composes "<device> <entity>", so the device carries the room (Alexa
# has no area context) and the entity says Fan or Light. Voice assistants must
# never hear the same name for both halves of one fixture.
BOND_SPOKEN_NAMES = {
    "fan.den_ceiling": "Den Ceiling Fan",
    "light.den_ceiling": "Den Ceiling Light",
    "fan.office_ceiling_fan": "Office Ceiling Fan",
    "light.office_ceiling": "Office Ceiling Light",
    "fan.guest_room": "Guest Room Ceiling Fan",
    "light.guest_room_ceiling": "Guest Room Ceiling Light",
    "fan.owner_suite": "Owner Suite Ceiling Fan",
    "light.owner_suite_ceiling": "Owner Suite Ceiling Light",
}

CONFIG_ROOTS = ("packages", "private_templates")


def test_bond_spoken_names_are_unique_and_say_fan_or_light() -> None:
    names = list(BOND_SPOKEN_NAMES.values())

    assert len({name.casefold() for name in names}) == len(names)
    for entity_id, name in BOND_SPOKEN_NAMES.items():
        expected_word = "Fan" if entity_id.startswith("fan.") else "Light"
        other_word = "Light" if expected_word == "Fan" else "Fan"
        assert name.endswith(f" {expected_word}"), entity_id
        assert other_word not in name, entity_id


def test_bond_entities_have_no_customize_friendly_name() -> None:
    # A customize friendly_name would mask the registry name that Alexa and
    # Assist use, and friendly_name is slated for deprecation.
    violations: list[str] = []
    for root_name in CONFIG_ROOTS:
        for path in (ROOT / root_name).rglob("*"):
            if not path.is_file() or path.suffix not in {".yaml", ".tmpl"}:
                continue
            rendered_from = ROOT / "private_templates" / f"{path.name}.tmpl"
            if root_name == "packages" and rendered_from.exists():
                continue  # rendered copy; its template is checked instead
            text = path.read_text(encoding="utf-8")
            for entity_id in BOND_SPOKEN_NAMES:
                pattern = re.compile(
                    rf"^    {re.escape(entity_id)}:\n((?:      .*\n)*)", re.MULTILINE
                )
                for match in pattern.finditer(text):
                    if "friendly_name:" in match.group(1):
                        violations.append(f"{path.relative_to(ROOT)}: {entity_id}")

    assert violations == []
