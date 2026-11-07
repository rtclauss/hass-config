from copy import deepcopy

from scripts.repair_dashboard_references import repair_patches


def test_removed_user_cleanup_preserves_hidden_tab_and_other_allowlists() -> None:
    config = {"views": [
        {"path": "vacation", "visible": [{"user": "removed-user"}]},
        {"path": "office", "visible": [{"user": "removed-user"}, {"user": "retained-user"}]},
        {"path": "home", "visible": True},
    ]}
    original = deepcopy(config)
    patches = repair_patches(config, {"removed-user"})
    assert config == original
    assert patches == [
        {"op": "replace", "path": "/views/0/visible", "value": False},
        {"op": "replace", "path": "/views/1/visible", "value": [{"user": "retained-user"}]},
    ]


def test_retired_cleaning_controls_use_existing_guarded_entry_point() -> None:
    config = {"views": [{"path": "cleaning-v2", "sections": [
        {"type": "grid", "column_span": 2, "cards": [
            {"type": "heading", "heading": "Cat-Safe Cleaning Policy"},
            {"type": "button", "tap_action": {"perform_action": "script.vacuum_supervised_clean"}},
        ]},
        {"type": "grid", "cards": [{"type": "heading", "heading": "Clothes"}]},
    ]}]}
    patches = repair_patches(config, set())
    assert len(patches) == 1
    patch = patches[0]
    assert patch["path"] == "/views/0/sections/0/cards"
    start, dock = patch["value"][2:]
    assert start["tap_action"] == {
        "action": "perform-action", "perform_action": "script.vacuum_manual_start", "data": {"robot": "all"}
    }
    assert dock["tap_action"]["perform_action"] == "script.vacuum_dock_all_robots"
    config["views"][0]["sections"][0]["cards"] = patch["value"]
    assert repair_patches(config, set()) == []


def test_unrelated_dashboard_is_untouched() -> None:
    assert repair_patches({"views": [{"path": "home", "sections": []}]}, set()) == []
