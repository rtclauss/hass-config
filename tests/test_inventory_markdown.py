from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "inventory.md"


def _clean_cell(value: str) -> str:
    return value.strip().strip("`")


def _normalize_header(value: str) -> str:
    value = value.lower()
    for old, new in (
        (" / ", "_"),
        (" ", "_"),
        ("-", "_"),
    ):
        value = value.replace(old, new)
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
    inventory = {
        (row["brand"], row["model"]): row
        for row in rows
    }

    expected = {
        ("Aqara", "Motion Sensor (RTCGQ11LM)"): ("6", "CR2450", "1"),
        ("Xiaomi", "Motion Sensor (RTCGQ01LM)"): ("2", "CR2450", "1"),
        ("Aqara", "Cube Controller (MKZQ01LM / MFKZQ01LM)"): ("8", "CR2450", "1"),
        ("Aqara", "Vibration Sensor (DJT11LM)"): ("2", "CR2032", "1"),
        ("Aqara", "Temperature and Humidity Sensor (WSDCGQ11LM)"): ("6", "CR2032", "1"),
        ("Ecolink", "FireFighter"): ("4", "CR123A", "1"),
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


def test_battery_planning_totals_match_inventory_rows() -> None:
    inventory_rows = _table_rows("Inventory")
    battery_rows = _table_rows("Battery Planning")

    actual_installed: dict[str, int] = {}
    for row in inventory_rows:
        battery = _clean_cell(row["battery"])
        if battery == "n/a":
            continue
        installed = int(row["quantity"]) * int(row["cells_device"])
        actual_installed[battery] = actual_installed.get(battery, 0) + installed

    expected_plan = {
        "AAA": (16, 8, 24),
        "CR2450": (16, 8, 24),
        "CR2032": (16, 8, 24),
        "CR1632": (4, 4, 8),
        "CR123A": (4, 4, 8),
    }

    plan = {
        _clean_cell(row["battery"]): (
            int(row["installed_cells"]),
            int(row["buffer"]),
            int(row["total_to_keep_ready"]),
        )
        for row in battery_rows
    }

    assert actual_installed == {battery: values[0] for battery, values in expected_plan.items()}
    assert plan == expected_plan


def test_inventory_documents_battery_assumptions_for_ambiguous_models() -> None:
    text = INVENTORY_PATH.read_text(encoding="utf-8")

    for snippet in (
        "`SYMFONISK` is counted as the original Zigbee sound remote",
        "`MKZQ01LM` in issue #202 appears to refer to the Aqara cube controller family",
        "`FireFighter` row reflects the Ecolink FireFighter battery family",
    ):
        assert snippet in text
