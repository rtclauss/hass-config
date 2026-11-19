"""Regression tests for Tesla scheduled-departure arming (issue #1200).

Home Assistant believed it had armed cabin preconditioning while the vehicle
never received the schedule, and nothing surfaced the failure.

Root cause, established empirically against the live vehicle: Tesla's
`set_scheduled_departure` command requires ALL SEVEN parameters, and answers a
partial payload with `{"result": false, "reason": "missing <name> param"}`,
naming each absent field in turn:

    (no off-peak fields)                 -> missing off_peak_charging_enabled param
    + off_peak_charging_enabled          -> missing off_peak_charging_weekdays_only param
    + off_peak_charging_weekdays_only    -> missing end_off_peak_time param
    + end_off_peak_time                  -> result: true

`teslajsonpy` maps SCHEDULED_DEPARTURE to
`POST api/1/vehicles/{vehicle_id}/command/set_scheduled_departure` and passes
`**kwargs` straight through as the request body with no validation and no
defaults, so an omitted field reaches Tesla genuinely missing.

The planner's "preserve the Tesla-app charging schedule" path — the one taken
at `home` — deliberately omitted all three off-peak fields, so that command was
rejected every time. The failure was invisible because `tesla_custom.api` is
registered with `supports_response=True` and returns Tesla's answer, but the
enable path discarded it and the planner then recorded a managed departure
anyway.

Two guarantees pinned here: every call sends the full parameter set, and a
rejection is never recorded as a successful arm.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAR_PATH = ROOT / "packages" / "car.yaml"

REQUIRED_PARAMS = (
    "enable",
    "departure_time",
    "preconditioning_enabled",
    "preconditioning_weekdays_only",
    "off_peak_charging_enabled",
    "off_peak_charging_weekdays_only",
    "end_off_peak_time",
)


def _scheduled_departure_enable_blocks(text: str) -> list[str]:
    """Return each SCHEDULED_DEPARTURE call block that enables a departure."""
    blocks = []
    for match in re.finditer(r"command: SCHEDULED_DEPARTURE\n(.*?)(?=\n\s*- |\Z)", text, re.DOTALL):
        block = match.group(1)
        if "enable: true" in block:
            blocks.append(block)
    return blocks


def test_every_enable_call_sends_all_seven_required_parameters() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")
    blocks = _scheduled_departure_enable_blocks(text)

    # The protected-location path and the HA-managed off-peak path.
    assert len(blocks) == 2, f"expected 2 enabling calls, found {len(blocks)}"

    for block in blocks:
        missing = [p for p in REQUIRED_PARAMS if f"{p}:" not in block]
        assert not missing, f"SCHEDULED_DEPARTURE call omits required params: {missing}"


def test_protected_location_path_echoes_the_vehicles_own_off_peak_settings() -> None:
    # Preserving the Tesla-app schedule must now mean sending the vehicle's
    # current values back, not omitting the fields.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert "off_peak_charging_enabled: \"{{ tesla_off_peak_charging_enabled }}\"" in text
    assert "off_peak_charging_weekdays_only: \"{{ tesla_off_peak_weekdays_only }}\"" in text
    assert "end_off_peak_time: \"{{ tesla_end_off_peak_time }}\"" in text

    # Those come from the vehicle's own scheduled-departure attributes.
    assert "'Off peak charging weekdays only'" in text
    assert "'End off peak time'" in text


def test_api_response_is_captured_on_both_enable_paths() -> None:
    # tesla_custom.api is registered with supports_response=True; discarding
    # the response is what made the failure silent.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert text.count("response_variable: tesla_departure_api_result") == 2


def test_a_rejected_arm_is_not_recorded_and_is_surfaced() -> None:
    # On rejection the script must stop with an error so the planner never
    # reaches input_boolean.tesla_managed_departure_active, and the reason must
    # reach both the logbook and a persistent notification.
    text = CAR_PATH.read_text(encoding="utf-8")

    assert text.count("- stop: Tesla rejected the scheduled departure") == 2
    assert text.count("error: true") >= 2
    assert text.count("notification_id: tesla_departure_arm_failed") >= 2
    assert "Tesla REJECTED the scheduled departure" in text
    assert "Cabin preconditioning is NOT armed." in text


def test_failure_detection_fails_closed() -> None:
    # An empty or absent response must count as failure, not success. Verified
    # against the live template engine for all four shapes:
    #   {'response': {'result': true}}  -> not failed
    #   {'response': {'result': false, 'reason': ...}} -> failed, reason shown
    #   {'response': {}} -> failed
    #   {} -> failed
    text = CAR_PATH.read_text(encoding="utf-8")

    assert (
        "{{ ((tesla_departure_api_result | default({}, true)).response"
        " | default({}, true)).result" in text
    )
    assert "| default(false) not in [true, 'true', 'True'] }}" in text


def test_stale_arm_failure_notice_is_cleared_on_success() -> None:
    text = CAR_PATH.read_text(encoding="utf-8")

    assert text.count("action: persistent_notification.dismiss") >= 2
