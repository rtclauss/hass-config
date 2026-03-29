from __future__ import annotations

from pathlib import Path


ALERTS_PATH = Path(__file__).resolve().parents[1] / "packages" / "alerts.yaml"


def test_notify_groups_do_not_include_lg_webos_service() -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")

    assert "- name: all" in text
    assert "- name: notify_all" in text
    assert "mobile_app_personal_macbook" in text
    assert "lg_webos_tv_oled65c4aua_dusqljr" not in text
