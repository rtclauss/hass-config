from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "appdaemon_sync", ROOT / "scripts" / "appdaemon_sync.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_load_agents_local_parses_markdown_sections(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.local.md"
    agents.write_text(
        """
# Local Runtime Targets

## Home Assistant

- host: `10.24.1.11`
- user: `hassio`
- password: `ssh-password`

## Home Assistant Samba

- user: `hassio`
- password: `pass`
- share: `addon_configs`
""".strip()
    )

    sections = MODULE.load_agents_local(tmp_path)

    assert sections["Home Assistant"]["host"] == "10.24.1.11"
    assert sections["Home Assistant Samba"]["password"] == "pass"
    assert sections["Home Assistant Samba"]["share"] == "addon_configs"


def test_resolve_addon_dir_auto_detects_single_match(tmp_path: Path) -> None:
    (tmp_path / "a0d7b954_appdaemon").mkdir()
    (tmp_path / "core_matter_server").mkdir()

    addon_dir = MODULE.resolve_addon_dir(tmp_path, None)

    assert addon_dir.name == "a0d7b954_appdaemon"


def test_build_rsync_command_includes_delete_and_excludes() -> None:
    command = MODULE.build_rsync_command(
        Path("/source"),
        Path("/dest"),
        delete=True,
        dry_run=True,
        itemize=True,
    )

    assert command[:4] == ["rsync", "-a", "-n", "--itemize-changes"]
    assert "--delete" in command
    assert "__pycache__/" in command
    assert "compiled/" in command
    assert command[-2:] == ["/source/", "/dest/"]
