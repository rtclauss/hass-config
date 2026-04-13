from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "inventory.md"


def _clean_cell(value: str) -> str:
    value = value.strip().strip("`")
    if value.startswith("FYRTUR battery pack"):
        return "FYRTUR battery pack"
    return value


def _normalize_header(value: str) -> str:
    value = value.lower()
    for old, new in (
        (" / ", "_"),
        (" ", "_"),
        ("-", "_"),
    ):
        value = value.replace(old, new)
    return value


def _normalize_battery_family(value: str) -> str:
    value = _clean_cell(value)
    if value == "FYRTUR battery pack":
        return "FYRTUR battery pack (BRAUNIT)"
    return value


def _table_rows(heading: str) -> list[dict[str, str]]:
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    marker = f"## {heading}\n"
    start = text.index(marker) + len(marker)

    lines: list[str] = []
    in_table = False
    for line in text[start:].splitlines():
        if line.startswith("|"):
            lines.append(line)
            in_table = True
            continue
        if in_table:
            break

    if len(lines) < 3:
        raise AssertionError(f"Could not parse markdown table for heading {heading!r}")

    headers = [_normalize_header(cell.strip()) for cell in lines[0].split("|")[1:-1]]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def test_inventory_rows_cover_issue_201_and_202_updates() -> None:
    rows = _table_rows("Inventory")
    inventory = {(row["brand"], row["model"]): row for row in rows}

    expected = {
        ("Aqara", "Motion Sensor (RTCGQ11LM)"): ("6", "CR2450", "1"),
        ("Xiaomi", "Motion Sensor (RTCGQ01LM)"): ("2", "CR2450", "1"),
        ("Aqara", "Cube Controller (MKZQ01LM / MFKZQ01LM)"): ("8", "CR2450", "1"),
        ("Aqara", "Vibration Sensor (DJT11LM)"): ("2", "CR2032", "1"),
        ("Aqara", "Temperature and Humidity Sensor (WSDCGQ11LM)"): ("6", "CR2032", "1"),
        ("Ecolink", "Firefighter (FFZB1-SM-ECO)"): ("4", "CR123A", "1"),
        ("Aqara", "Door and Window Sensor (MCCGQ11LM)"): ("3", "CR1632", "1"),
        ("Xiaomi", "Door and Window Sensor (MCCGQ01LM)"): ("1", "CR1632", "1"),
        ("Aqara", "Wireless Mini Switch (WXKG11LM)"): ("1", "CR2032", "1"),
        ("Xiaomi", "Mi Wireless Switch (WXKG01LM)"): ("1", "CR2032", "1"),
        ("Aqara", "Water Leak Sensor (SJCGQ11LM)"): ("4", "CR2032", "1"),
        ("IKEA", "BADRING water leakage sensor"): ("4", "AAA", "1"),
        ("IKEA", "BILRESA remote control with smart scroll wheel"): ("2", "AAA", "2"),
        ("IKEA", "SYMFONISK sound remote"): ("2", "CR2032", "1"),
        ("IKEA", "PARASOLL door/window sensor"): ("4", "AAA", "1"),
    }

    for key, (quantity, battery, cells_per_device) in expected.items():
        row = inventory.get(key)
        assert row is not None, f"Missing inventory row for {key!r}"
        assert row["quantity"] == quantity
        assert _clean_cell(row["battery"]) == battery
        assert row["cells_device"] == cells_per_device


def test_configured_battery_rows_cover_live_battery_devices() -> None:
    rows = _table_rows("Configured Battery Devices")
    configured = {(row["brand"], row["model"]): row for row in rows}

    expected = {
        ("Aqara", "Motion Sensor (RTCGQ11LM)"): ("6", "CR2450", "1"),
        ("Aqara", "Motion and Light Sensor P2"): ("1", "CR2450", "1"),
        ("Aqara", "Cube Controller (MKZQ01LM / MFKZQ01LM)"): ("1", "CR2450", "1"),
        ("Aqara", "Temperature and Humidity Sensor (WSDCGQ11LM)"): ("8", "CR2032", "1"),
        ("Aqara", "Vibration Sensor (DJT11LM)"): ("1", "CR2032", "1"),
        ("Aqara", "Water Leak Sensor (SJCGQ11LM)"): ("1", "CR2032", "1"),
        ("Aqara", "Door and Window Sensor (MCCGQ11LM)"): ("6", "CR1632", "1"),
        ("Xiaomi", "Mi Wireless Switch (WXKG01LM)"): ("1", "CR2032", "1"),
        ("IKEA", "PARASOLL door/window sensor"): ("20", "AAA", "1"),
        ("IKEA", "RODRET wireless dimmer"): ("1", "AAA", "1"),
        ("IKEA", "SOMRIG shortcut button"): ("2", "AAA", "1"),
        ("IKEA", "TRADFRI remote control"): ("2", "CR2032", "1"),
        ("IKEA", "SYMFONISK sound remote, gen 2"): ("2", "AAA", "2"),
        ("IKEA", "FYRTUR roller blind, block-out"): ("2", "FYRTUR battery pack", "1"),
        ("SmartThings", "Arrival sensor"): ("1", "AA", "2"),
        ("Schlage", "Encode Plus Smart WiFi Deadbolt (BE499WB)"): ("1", "AA", "4"),
        ("ecobee Inc.", "Remote occupancy and temperature sensor (EBERS41)"): ("5", "CR2477", "1"),
        ("Xiaomi", "MiFlora plant sensor"): ("12", "CR2032", "1"),
    }

    for key, (quantity, battery, cells_per_device) in expected.items():
        row = configured.get(key)
        assert row is not None, f"Missing configured battery row for {key!r}"
        assert row["quantity"] == quantity
        assert _clean_cell(row["battery"]) == battery
        assert row["cells_device"] == cells_per_device


def test_loose_battery_stock_tracks_spare_aaa_cells() -> None:
    rows = _table_rows("Loose Battery Stock")
    stock = {_clean_cell(row["battery"]): row for row in rows}

    aaa = stock.get("AAA")
    assert aaa is not None
    assert aaa["quantity"] == "8"
    assert "Loose spare cells on hand" in aaa["notes"]


def test_configured_z2m_rows_cover_new_non_battery_devices() -> None:
    rows = _table_rows("Configured Zigbee2MQTT Devices")
    configured = {(row["brand"], row["model"]): row for row in rows}

    expected = {
        ("IKEA", "INSPELNING smart plug"): ("2", "n/a", "0"),
        ("Innr", "E26/24 bulb 1100lm, dimmable, white spectrum"): ("1", "n/a", "0"),
    }

    for key, (quantity, battery, cells_per_device) in expected.items():
        row = configured.get(key)
        assert row is not None, f"Missing configured Zigbee2MQTT row for {key!r}"
        assert row["quantity"] == quantity
        assert _clean_cell(row["battery"]) == battery
        assert row["cells_device"] == cells_per_device


def test_battery_planning_totals_match_inventory_rows() -> None:
    inventory_rows = _table_rows("Inventory")
    configured_rows = _table_rows("Configured Battery Devices")
    battery_rows = _table_rows("Battery Planning")

    actual_inventory: dict[str, int] = {}
    for row in inventory_rows:
        battery = _normalize_battery_family(row["battery"])
        if battery == "n/a":
            continue
        installed = int(row["quantity"]) * int(row["cells_device"])
        actual_inventory[battery] = actual_inventory.get(battery, 0) + installed

    actual_configured: dict[str, int] = {}
    for row in configured_rows:
        battery = _normalize_battery_family(row["battery"])
        if battery == "n/a":
            continue
        installed = int(row["quantity"]) * int(row["cells_device"])
        actual_configured[battery] = actual_configured.get(battery, 0) + installed

    expected_plan = {
        "AAA": ("Rechargeable cylindrical", 16, 27, 16, 59),
        "AA": ("Rechargeable cylindrical", 0, 6, 4, 10),
        "FYRTUR battery pack (BRAUNIT)": ("Rechargeable pack", 0, 2, 1, 3),
        "CR2450": ("Primary coin cell", 16, 8, 6, 30),
        "CR2032": ("Primary coin cell", 16, 25, 11, 52),
        "CR1632": ("Primary coin cell", 4, 6, 3, 13),
        "CR2477": ("Primary coin cell", 0, 5, 3, 8),
        "CR123A": ("Primary cylindrical lithium", 4, 0, 4, 8),
    }

    plan = {
        _normalize_battery_family(row["battery"]): (
            row["kind"],
            int(row["inventory_cells"]),
            int(row["configured_cells"]),
            int(row["swap_charge_overhead"]),
            int(row["total_to_keep_ready"]),
        )
        for row in battery_rows
        if _clean_cell(row["battery"]) != "TOTAL"
    }

    total_row = next(row for row in battery_rows if _clean_cell(row["battery"]) == "TOTAL")

    assert actual_inventory == {
        battery: values[1]
        for battery, values in expected_plan.items()
        if values[1] > 0
    }
    assert actual_configured == {
        battery: values[2]
        for battery, values in expected_plan.items()
        if values[2] > 0
    }
    assert plan == expected_plan
    assert total_row["kind"] == "8 battery families / 4 kinds"
    assert int(total_row["inventory_cells"]) == sum(values[1] for values in expected_plan.values())
    assert int(total_row["configured_cells"]) == sum(values[2] for values in expected_plan.values())
    assert int(total_row["swap_charge_overhead"]) == sum(values[3] for values in expected_plan.values())
    assert int(total_row["total_to_keep_ready"]) == sum(values[4] for values in expected_plan.values())


def test_inventory_documents_battery_assumptions_for_ambiguous_models() -> None:
    text = INVENTORY_PATH.read_text(encoding="utf-8")

    for snippet in (
        "`SYMFONISK` spare inventory row is still counted as the original Zigbee sound remote",
        "`TRADFRI remote control` in Home Assistant is counted as the older `CR2032`-powered remote",
        "`MiFlora plant sensor` assumes the current plant-monitor fleet behind `packages/plants.yaml` still uses the Xiaomi MiFlora / Flower Care battery profile",
        "`SmartThings Arrival sensor` uses the README-documented `2 x AA` battery mod",
        "`Schlage` model `be499WB` from the Home app screenshot is treated as the Encode Plus family, which Schlage documents as using `4 x AA` batteries",
        "`MKZQ01LM` in issue #202 appears to refer to the Aqara cube controller family",
        "`FireFighter` row reflects the Ecolink FireFighter battery family",
    ):
        assert snippet in text


def test_inventory_documents_z2m_decommission_reconciliation_rule() -> None:
    text = INVENTORY_PATH.read_text(encoding="utf-8")

    assert "When a Zigbee2MQTT device is intentionally decommissioned" in text
    assert "Configured Battery Devices" in text
    assert "Configured Zigbee2MQTT Devices" in text
    assert "increment the matching spare row in `Inventory`" in text
    assert "re-check `Battery Planning` totals" in text
