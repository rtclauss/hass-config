"""The retained-topic utility must keep broker secrets out of public source."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "clean_mqtt_topics.sh"


def test_cleanup_requires_explicit_apply_and_private_config(tmp_path: Path) -> None:
    result = subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 2

    result = subprocess.run(
        ["sh", str(SCRIPT), "--apply"],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


def test_cleanup_uses_mosquitto_private_config_and_retained_only(tmp_path: Path) -> None:
    config = tmp_path / "mqtt.conf"
    config.write_text("-h 192.0.2.10\n-u example-user\n-P synthetic-password\n")
    args_file = tmp_path / "args.txt"
    stub = tmp_path / "mosquitto_sub"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$MQTT_TEST_ARGS_FILE"\n')
    stub.chmod(0o700)

    result = subprocess.run(
        ["sh", str(SCRIPT), "--apply"],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "MQTT_CLIENT_CONFIG": str(config),
            "MQTT_TEST_ARGS_FILE": str(args_file),
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert args_file.read_text().splitlines() == [
        "-o", str(config), "-t", "#", "--remove-retained", "--retained-only", "--quiet"
    ]
    assert "synthetic-password" not in SCRIPT.read_text()
