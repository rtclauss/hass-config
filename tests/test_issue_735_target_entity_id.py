from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDITED_PACKAGES = [
    ROOT / "packages" / "fans.yaml",
    ROOT / "packages" / "holidays.yaml",
    ROOT / "packages" / "zone.yaml",
    ROOT / "packages" / "media_player.yaml",
    ROOT / "packages" / "tv.yaml",
]

TARGETABLE_ACTIONS = {
    "fan.turn_on",
    "fan.turn_off",
    "input_boolean.turn_off",
    "input_boolean.turn_on",
    "input_select.select_option",
    "light.turn_off",
    "media_player.media_next_track",
    "media_player.media_pause",
    "media_player.media_play_pause",
    "media_player.play_media",
    "media_player.select_source",
    "media_player.shuffle_set",
    "media_player.turn_on",
    "media_player.volume_set",
    "scene.turn_on",
    "script.turn_on",
    "vacuum.return_to_base",
}


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _action_from_line(line: str) -> str | None:
    stripped = line.strip()
    for prefix in ("- action: ", "action: ", "- service: ", "service: "):
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix).strip().strip('"')
    return None


def _block_for_action(lines: list[str], start: int) -> list[str]:
    base_indent = _indent(lines[start])
    block = [lines[start]]

    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and _indent(line) <= base_indent:
            break
        block.append(line)

    return block


def _data_block_has_entity_id(block: list[str]) -> bool:
    for index, line in enumerate(block):
        if line.strip() != "data:":
            continue

        data_indent = _indent(line)
        for child in block[index + 1 :]:
            stripped = child.strip()
            if stripped and not stripped.startswith("#") and _indent(child) <= data_indent:
                break
            if stripped.startswith("entity_id:"):
                return True

    return False


def test_targetable_services_do_not_put_entity_id_under_data() -> None:
    offenders: list[str] = []

    for package_path in AUDITED_PACKAGES:
        lines = package_path.read_text().splitlines()
        for index, line in enumerate(lines):
            action = _action_from_line(line)
            if action not in TARGETABLE_ACTIONS:
                continue

            if _data_block_has_entity_id(_block_for_action(lines, index)):
                line_number = index + 1
                offenders.append(f"{package_path.relative_to(ROOT)}:{line_number}: {action}")

    assert offenders == []
