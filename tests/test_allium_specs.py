from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = ROOT / "specs"


def test_behavioral_allium_specs_exist_and_are_versioned() -> None:
    specs = {
        "alarm_wakeup.allium": [
            "-- allium: 3",
            "entity HouseModeStateMachine",
            "rule NormalizePhoneWakeupPayload",
            "rule SyncPhoneWakeupAlarm",
            "rule TriggerWeekdayWakeup",
            "rule TriggerWorkdayOwnerSuiteWakeTransitionFromMorningActivity",
            "ensures: house_mode.mode = home",
            "rule OpenBlindsDuringWakeupTransition",
            "rule StartBathroomMorningRoutine",
        ],
        "night_routines.allium": [
            "-- allium: 3",
            "entity HouseModeStateMachine",
            "overnight_exterior_lighting_preserved: Boolean",
            "rule StartBedtimePreparation",
            "rule ScheduleBedtimeAudioRampdown",
            "rule EnterInBedHouseMode",
            "ensures: house.overnight_exterior_lighting_preserved = true",
            "rule ChooseBedtimeAudioFromConfiguredPool",
            "rule TriggerGoodnightFromCPAPSleep",
            "rule ScheduleOwnerSuiteBlindsSunsetPrivacyClose",
            "rule CloseOwnerSuiteBlindsAroundSunset",
            "rule EnterAsleepHouseModeFromBedsideShutdown",
            "rule ApplyGoodnightIntegrity",
            "owner_suite_switch_led_mode: OwnerSuiteSwitchLedMode",
            "enum OwnerSuiteSwitchLedMode { dark | night_red | day }",
            "rule ApplyOwnerSuiteWorkdayMorningLedPolicy",
            "wait_for_bathroom_visit_or_timeout",
        ],
        "arrival_lighting.allium": [
            "-- allium: 3",
            "external entity ArrivalContext",
            "home_was_empty_before_arrival: Boolean",
            "rule ApplyAdaptiveLightingOnArrival",
            "rule PreserveManualLightingDuringOccupiedArrival",
            "ArrivalRoomAdaptiveSwitchStatePreserved",
            "rule SyncSelectedInovelliLedBarsToAdaptiveLighting",
            "manual_control attribute",
        ],
        "z2m_lifecycle.allium": [
            "-- allium: 3",
            "entity ZigbeeDeviceLifecycle",
            "rule RecordDeviceInterviewFailure",
            "rule DetectJoinThenDropFromLeave",
            "rule DetectJoinThenDropFromRosterLoss",
            "rule DetectLeftNetwork",
            "coordinator_issue_hold_window: Duration = 2.minutes",
            "rule DelayTransientCoordinatorMissingRouters",
            "rule NotifyPersistentCoordinatorMissingRouters",
            "rule EscalateOnlyForSystemicBridgeFailures",
            "single_device_churn_never_triggers_host_restart",
            "rule ConfirmForceDeviceDecommission",
            "InventoryMarkdownUpdateRequired",
        ],
    }

    for filename, expected_tokens in specs.items():
        path = SPECS_DIR / filename
        assert path.exists(), f"Missing Allium spec: {filename}"
        text = path.read_text(encoding="utf-8")

        for token in expected_tokens:
            assert token in text, f"{filename} is missing {token!r}"


def test_alarm_wakeup_spec_uses_checker_supported_context_events() -> None:
    text = (SPECS_DIR / "alarm_wakeup.allium").read_text(encoding="utf-8")

    for token in (
        "wakeup_context: WakeupContext",
        "when: OwnerSuiteMorningActivityDetected()",
        "when: BathroomMorningOccupancyDetected()",
        "if target_room = bathroom:",
    ):
        assert token in text

    assert not re.search(r"\bcontext\.", text)
    assert "context.resident_in_bed becomes" not in text
    assert "context.bathroom_occupied becomes" not in text
    assert "target_room == bathroom" not in text
