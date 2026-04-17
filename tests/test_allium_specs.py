from __future__ import annotations

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
            "rule EnterAsleepHouseModeFromBedsideShutdown",
            "rule ApplyGoodnightIntegrity",
            "wait_for_bathroom_visit_or_timeout",
        ],
        "arrival_lighting.allium": [
            "-- allium: 3",
            "external entity ArrivalContext",
            "home_was_empty_before_arrival: Boolean",
            "rule ApplyAdaptiveLightingOnArrival",
            "rule PreserveManualLightingDuringOccupiedArrival",
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
