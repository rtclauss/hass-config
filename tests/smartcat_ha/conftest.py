"""Shared fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request: pytest.FixtureRequest):
    """Enable custom integrations for Home Assistant tests only.

    `recorder_mock` must be set up before `hass`, so request it first when the
    test uses it.
    """
    if "hass" not in request.fixturenames:
        yield
        return
    if "recorder_mock" in request.fixturenames:
        request.getfixturevalue("recorder_mock")
    request.getfixturevalue("enable_custom_integrations")
    yield
