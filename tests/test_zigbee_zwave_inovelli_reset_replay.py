from __future__ import annotations

import re
from pathlib import Path


ZIGBEE_ZWAVE_PATH = Path(__file__).resolve().parents[1] / "packages" / "zigbee_zwave.yaml"


def _script_block(script_id: str) -> str:
    lines = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8").splitlines()
    start = None
    needle = f"  {script_id}:"

    for index, line in enumerate(lines):
        if line == needle:
            start = index
            break

    if start is None:
        raise AssertionError(f"Could not find script id {script_id!r}")

    end = len(lines)
    next_script = re.compile(r"^  [A-Za-z0-9_]+:$")
    for index in range(start + 1, len(lines)):
        if next_script.match(lines[index]):
            end = index
            break

    return "\n".join(lines[start:end])


def _section(block: str, start_marker: str, end_marker: str) -> str:
    start = block.index(start_marker)
    end = block.index(end_marker, start)
    return block[start:end]


def _parse_group_memberships(block: str) -> set[tuple[str, str, int]]:
    section = _section(
        block,
        "inovelli_group_membership_replay:",
        "inovelli_binding_replay:",
    )
    memberships: set[tuple[str, str, int]] = set()
    current_group: str | None = None
    current_device: str | None = None

    for line in section.splitlines():
        if match := re.match(r'\s*-\s+group:\s+"([^"]+)"', line):
            current_group = match.group(1)
            current_device = None
            continue

        if match := re.match(r'\s*-\s+device:\s+"([^"]+)"', line):
            current_device = match.group(1)
            continue

        if match := re.match(r"\s*endpoint:\s+(\d+)", line):
            if current_group is None or current_device is None:
                raise AssertionError(f"Malformed group membership line: {line!r}")
            memberships.add((current_group, current_device, int(match.group(1))))

    return memberships


def _parse_bindings(
    block: str,
) -> set[tuple[str, int, str, int | None, tuple[str, ...]]]:
    section = _section(block, "inovelli_binding_replay:", "    sequence:")
    bindings: set[tuple[str, int, str, int | None, tuple[str, ...]]] = set()
    current: dict[str, object] | None = None

    def flush_current() -> None:
        nonlocal current
        if current is None:
            return

        bindings.add(
            (
                current["from"],
                current["from_endpoint"],
                current["to"],
                current.get("to_endpoint"),
                tuple(current["clusters"]),
            )
        )
        current = None

    for line in section.splitlines():
        if match := re.match(r'\s*-\s+from:\s+"([^"]+)"', line):
            flush_current()
            current = {"from": match.group(1), "clusters": []}
            continue

        if current is None:
            continue

        if match := re.match(r"\s*from_endpoint:\s+(\d+)", line):
            current["from_endpoint"] = int(match.group(1))
            continue

        if match := re.match(r'\s*to:\s+"([^"]+)"', line):
            current["to"] = match.group(1)
            continue

        if match := re.match(r"\s*to_endpoint:\s+(\d+)", line):
            current["to_endpoint"] = int(match.group(1))
            continue

        if match := re.match(r"\s*-\s+([A-Za-z0-9]+)\s*$", line):
            current["clusters"].append(match.group(1))

    flush_current()
    return bindings


def test_reset_script_uses_static_replay_snapshot_instead_of_runtime_capture() -> None:
    block = _script_block("reset_inovelli_switches")

    assert "inovelli_smart_bulb_mode_replay:" in block
    assert "inovelli_output_mode_replay:" in block
    assert "inovelli_switch_type_replay:" in block
    assert "inovelli_group_membership_replay:" in block
    assert "inovelli_binding_replay:" in block
    assert "bridge/request/devices" not in block
    assert "bridge/response/devices" not in block
    assert "captured_inovelli_" not in block


def test_reset_script_replays_current_live_switch_modes_readably() -> None:
    block = _script_block("reset_inovelli_switches")

    assert 'option: "Disabled"' in block
    assert "select.deck_flood_lights_smartbulbmode" in block
    assert "select.owner_suite_bathroom_vanity_smartbulbmode" in block
    assert 'option: "On/Off"' in block
    assert "select.garage_overhead_switch_outputmode" in block
    assert 'option: "3-Way Aux Switch"' in block
    assert "select.garage_overhead_switch_switchtype" in block
    assert "select.hall_foyer_switch_switchtype" in block


def test_reset_script_does_not_restore_deck_flood_lights_smart_bulb_mode() -> None:
    block = _script_block("reset_inovelli_switches")
    smart_bulb_section = _section(
        block,
        'inovelli_smart_bulb_mode_replay:',
        'inovelli_output_mode_replay:',
    )

    smart_bulb_option, disabled_option = smart_bulb_section.split('        - option: "Disabled"', 1)

    assert "select.deck_flood_lights_smartbulbmode" not in smart_bulb_option
    assert "select.deck_flood_lights_smartbulbmode" in disabled_option


def test_reset_script_replays_current_live_group_memberships_and_bindings() -> None:
    block = _script_block("reset_inovelli_switches")

    expected_memberships = {
        ("Basement/Great Room", "Basement/Great Room East and Middle Switch", 1),
        ("Basement/Great Room", "Basement/Great Room Landing Switch 2", 1),
        ("Basement/Great Room", "Basement/Great Room West Switch", 1),
        ("Basement/Great Room", "Basement/Landing Switch", 1),
        ("Basement/Great Room", "Basement/North Hallway Switch", 1),
        ("Deck/All", "Deck/Kitchen Door", 2),
        ("Deck/Hue", "Deck/Kitchen Door", 1),
        ("Den/Floods", "Den/Flood Switch", 1),
        ("Dining Room/Over Table", "Dining Room/Table Switch", 1),
        ("Dining Room/Over Table", "Dining Room/Wall Switch", 1),
        ("Hall/All", "Hall/Foyer Switch", 1),
        ("Hall/All", "Hall/Garage Laundry Switch", 1),
        ("Hall/All", "Hall/Transition Switch", 1),
        ("Hall/All", "Hall/Upstairs/Switch", 1),
        ("Kitchen/All", "Kitchen/Bay Switch", 1),
        ("Kitchen/All", "Kitchen/Switch", 1),
        ("Outside/Front Hue", "Outside/Front Lights", 1),
        ("Owner Suite/Bathroom/Lights", "Owner Suite/Bathroom/Shower Switch", 1),
        ("Owner Suite/Bathroom/Lights", "Owner Suite/Bathroom/Tub Switch", 1),
    }
    expected_bindings = {
        (
            "Basement/Bathroom/Shower Switch",
            2,
            "Basement/Bathroom Shower",
            1,
            ("genLevelCtrl", "genOnOff"),
        ),
        (
            "Basement/Great Room East and Middle Switch",
            2,
            "Basement/Great Room",
            None,
            ("genLevelCtrl", "genOnOff"),
        ),
        (
            "Basement/Great Room Landing Switch 2",
            2,
            "Basement/Great Room",
            None,
            ("genLevelCtrl", "genOnOff"),
        ),
        (
            "Basement/Great Room West Switch",
            2,
            "Basement/Great Room",
            None,
            ("genLevelCtrl", "genOnOff"),
        ),
        (
            "Basement/Landing Switch",
            2,
            "Basement/Great Room",
            None,
            ("genLevelCtrl", "genOnOff"),
        ),
        (
            "Basement/North Hallway Switch",
            2,
            "Basement/Great Room",
            None,
            ("genLevelCtrl", "genOnOff"),
        ),
        ("Deck/Kitchen Door", 2, "Deck/Hue", None, ("genLevelCtrl", "genOnOff")),
        (
            "Den/Flood Switch",
            2,
            "Den/Floods",
            None,
            ("genLevelCtrl", "genOnOff", "genScenes"),
        ),
        ("Den/Flood Switch", 2, "Den/Lamp", 1, ("genLevelCtrl", "genOnOff")),
        (
            "Dining Room/Table Switch",
            2,
            "Dining Room/Over Table",
            None,
            ("genLevelCtrl", "genOnOff", "genScenes"),
        ),
        (
            "Dining Room/Wall Switch",
            2,
            "Dining Room/Over Table",
            None,
            ("genLevelCtrl", "genOnOff", "genScenes"),
        ),
        ("Hall/Foyer Switch", 2, "Hall/All", None, ("genLevelCtrl", "genOnOff")),
        (
            "Hall/Garage Laundry Switch",
            2,
            "Hall/All",
            None,
            ("genLevelCtrl", "genOnOff"),
        ),
        (
            "Hall/Transition Switch",
            3,
            "Hall/Transition",
            11,
            ("genLevelCtrl", "genOnOff"),
        ),
        ("Hall/Upstairs/Switch", 2, "Hall/All", None, ("genLevelCtrl", "genOnOff")),
        ("Kitchen/Bay Switch", 2, "Kitchen/Bay Light", 11, ("genLevelCtrl", "genOnOff")),
        (
            "Kitchen/Sink Overhead Switch",
            2,
            "Kitchen/Sink Overhead",
            11,
            ("genLevelCtrl", "genOnOff"),
        ),
        ("Kitchen/Switch", 2, "Kitchen/All", None, ("genLevelCtrl", "genOnOff")),
        (
            "Outside/Front Lights",
            2,
            "Outside/Front Hue",
            None,
            ("genLevelCtrl", "genOnOff"),
        ),
        (
            "Owner Suite/Bathroom/Shower Switch",
            2,
            "Owner Suite/Bathroom/Lights",
            None,
            ("genLevelCtrl", "genOnOff"),
        ),
        (
            "Owner Suite/Bathroom/Tub Switch",
            2,
            "Owner Suite/Bathroom/Lights",
            None,
            ("genLevelCtrl", "genOnOff"),
        ),
    }

    assert _parse_group_memberships(block) == expected_memberships
    assert _parse_bindings(block) == expected_bindings


def test_reset_script_replays_endpoint_1_membership_for_group_bound_switch_sync() -> None:
    block = _script_block("reset_inovelli_switches")

    memberships = _parse_group_memberships(block)
    for device, from_endpoint, group, to_endpoint, _clusters in _parse_bindings(block):
        if from_endpoint != 2 or to_endpoint is not None:
            continue

        assert (group, device, 1) in memberships
        assert (group, device, 2) not in memberships


def test_hall_transition_recovery_replays_led_policy_after_unavailable() -> None:
    text = ZIGBEE_ZWAVE_PATH.read_text(encoding="utf-8")

    block = text.split(
        "replay_hall_transition_inovelli_led_policy_on_recovery:\n",
        1,
    )[1].split(
        "\n  turn_off_owner_suite_inovelli_switch_leds:\n",
        1,
    )[0]

    for token in (
        'from: "unavailable"',
        "number.hall_transition_switch_ledcolorwhenoff",
        "number.hall_transition_switch_ledcolorwhenon",
        "number.hall_transition_switch_ledintensitywhenoff",
        "number.hall_transition_switch_ledintensitywhenon",
        "switch.sleep_mode",
        "sun.sun",
        "script.restore_inovelli_switch_leds_from_trip",
    ):
        assert token in block


def test_reset_script_finishes_with_the_issue_aurora_led_effect() -> None:
    block = _script_block("reset_inovelli_switches")

    assert "aurora_effect: aurora" in block
    assert "aurora_color: 187" in block
    assert "aurora_level: 51" in block
    assert "aurora_duration: 70" in block
    assert 'topic: "zigbee2mqtt/{{ repeat.item }}/set"' in block
    assert "'led_effect': {" in block


def test_reset_script_skips_aurora_notification_while_bed_is_occupied() -> None:
    block = _script_block("reset_inovelli_switches")

    assert "binary_sensor.bayesian_bed_occupancy" in block
    assert 'state: "off"' in block
    assert block.index("binary_sensor.bayesian_bed_occupancy") < block.index(
        'topic: "zigbee2mqtt/{{ repeat.item }}/set"'
    )
