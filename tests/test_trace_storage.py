from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRACE_MINIMUM = 100


def _is_top_level(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not line.startswith((" ", "\t")) and not stripped.startswith("#")


def _top_key(line: str) -> str | None:
    if not _is_top_level(line) or ":" not in line:
        return None
    return line.split(":", 1)[0]


def _section_end(lines: list[str], section_start: int) -> int:
    for index in range(section_start + 1, len(lines)):
        if _is_top_level(lines[index]):
            return index
    return len(lines)


def _automation_blocks(lines: list[str], section_start: int, section_end: int) -> list[tuple[int, int]]:
    starts = [
        index for index in range(section_start + 1, section_end) if lines[index].startswith("  - ")
    ]
    return [
        (start, starts[index + 1] if index + 1 < len(starts) else section_end)
        for index, start in enumerate(starts)
    ]


def _script_blocks(lines: list[str], section_start: int, section_end: int) -> list[tuple[int, int]]:
    starts = []
    for index in range(section_start + 1, section_end):
        line = lines[index]
        stripped = line.strip()
        if (
            line.startswith("  ")
            and not line.startswith("    ")
            and stripped
            and not stripped.startswith("#")
            and stripped.endswith(":")
        ):
            starts.append(index)
    return [
        (start, starts[index + 1] if index + 1 < len(starts) else section_end)
        for index, start in enumerate(starts)
    ]


def _block_name(lines: list[str], start: int, end: int, fallback: str) -> str:
    for line in lines[start:end]:
        stripped = line.strip()
        if stripped.startswith(("- id:", "id:", "- alias:", "alias:")):
            return stripped.split(":", 1)[1].strip().strip('"')
    return fallback


def _stored_traces(lines: list[str], start: int, end: int) -> int | None:
    for index in range(start, end):
        if not lines[index].startswith("    trace:"):
            continue
        for trace_index in range(index + 1, end):
            if lines[trace_index].startswith("    ") and not lines[trace_index].startswith("      "):
                return None
            stripped = lines[trace_index].strip()
            if stripped.startswith("stored_traces:"):
                value = stripped.split(":", 1)[1].strip()
                return int(value) if value.isdigit() else None
    return None


def test_automation_and_script_traces_keep_at_least_100_runs() -> None:
    config_paths = [
        ROOT / "automations.yaml",
        ROOT / "scripts.yaml",
        *sorted((ROOT / "packages").glob("*.yaml")),
    ]
    missing_or_low_trace: list[str] = []

    for path in config_paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for section_start, line in enumerate(lines):
            key = _top_key(line)
            if key not in {"automation", "script"}:
                continue
            section_end = _section_end(lines, section_start)
            if key == "automation":
                blocks = _automation_blocks(lines, section_start, section_end)
            elif line.strip().endswith("{}"):
                blocks = []
            else:
                blocks = _script_blocks(lines, section_start, section_end)

            for start, end in blocks:
                stored_traces = _stored_traces(lines, start, end)
                if stored_traces is None or stored_traces < TRACE_MINIMUM:
                    block_name = _block_name(lines, start, end, "<unnamed>")
                    missing_or_low_trace.append(f"{path.relative_to(ROOT)} {key} {block_name}")

    assert missing_or_low_trace == []
