"""Regression test: the Valetudo map guard must not silently swallow a failed
accept/reject PUT.

Background: `packages/vacuum_map_guard.yaml` auto-rejects a pending map change so
the robot keeps its existing room layout (or accepts a new one on request). The
reject/accept REST calls used to fire with only `continue_on_error: true` and no
result check, so if the robot was unreachable the map change stayed pending and
the room layout could be lost on the next cycle — yet the automation reported
success with no signal. This mirrors the Tesla scheduled-departure silent-failure
class (#1200): a state-changing external call whose rejection is ignored.

The guard now captures the REST result and alerts the owner on anything but a 2xx
response (and on a swallowed transport error, which leaves the response variable
undefined), so a failed auto-keep can no longer pass unnoticed.
"""

from __future__ import annotations

from pathlib import Path


GUARD_PATH = Path(__file__).resolve().parents[1] / "packages" / "vacuum_map_guard.yaml"


def _text() -> str:
    return GUARD_PATH.read_text(encoding="utf-8")


def test_map_change_rest_calls_capture_their_result() -> None:
    text = _text()

    # Both automations funnel accept/reject through one templated rest_command
    # whose response is captured, instead of two fire-and-forget calls.
    assert text.count('response_variable: map_change_result') == 2
    assert 'rest_command.valetudo_mainlevel_{{ map_action }}_map_change' in text
    assert 'rest_command.valetudo_upstairs_{{ map_action }}_map_change' in text

    # The old fire-and-forget calls (direct named command with no result check)
    # must be gone from the action sequences.
    for direct in (
        '- action: rest_command.valetudo_mainlevel_accept_map_change',
        '- action: rest_command.valetudo_mainlevel_reject_map_change',
        '- action: rest_command.valetudo_upstairs_accept_map_change',
        '- action: rest_command.valetudo_upstairs_reject_map_change',
    ):
        assert direct not in text


def test_non_2xx_or_missing_result_alerts_the_owner() -> None:
    text = _text()

    # The failure guard fires on a non-2xx status OR an undefined result
    # (the transport error swallowed by continue_on_error).
    assert text.count('map_change_result is defined') == 2
    assert text.count('(map_change_result.status | default(0) | int(0)) >= 200') == 2
    assert text.count('(map_change_result.status | default(0) | int(0)) < 300') == 2

    # Each failure path notifies the owner and is de-duplicated per robot.
    assert text.count('map {{ map_action }} failed') == 2
    assert 'tag: "valetudo-mainlevel-map-guard-failed"' in text
    assert 'tag: "valetudo-upstairs-map-guard-failed"' in text


def test_still_keeps_continue_on_error_so_a_failed_put_does_not_abort() -> None:
    # The REST call must stay non-fatal so the automation reaches its own
    # failure check instead of aborting on the raised transport error.
    text = _text()
    assert text.count('continue_on_error: true') == 2
