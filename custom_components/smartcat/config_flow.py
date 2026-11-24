"""Config flow for Smart Cat."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BACKFILL_DAYS,
    CONF_LITTER_THRESHOLD,
    CONF_RETENTION_DAYS,
    CONF_WASTE_THRESHOLD,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_LITTER_THRESHOLD,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_WASTE_THRESHOLD,
    DOMAIN,
    LITTERROBOT_DOMAIN,
)


def _options_schema(options: dict[str, Any]) -> vol.Schema:
    def number(key: str, default: int, lo: int, hi: int, unit: str) -> tuple:
        return (
            vol.Required(key, default=options.get(key, default)),
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=lo, max=hi, step=1, unit_of_measurement=unit,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        )

    return vol.Schema(
        dict(
            [
                number(CONF_WASTE_THRESHOLD, DEFAULT_WASTE_THRESHOLD, 10, 100, "%"),
                number(CONF_LITTER_THRESHOLD, DEFAULT_LITTER_THRESHOLD, 0, 100, "%"),
                number(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS, 1, 3650, "days"),
                number(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS, 0, 36500, "days"),
            ]
        )
    )


class SmartCatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Smart Cat on top of the Whisker integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create the single entry; options can be changed later."""
        if not self.hass.config_entries.async_entries(LITTERROBOT_DOMAIN):
            return self.async_abort(reason="whisker_missing")
        if user_input is not None:
            return self.async_create_entry(
                title="Smart Cat",
                data={},
                options={k: int(v) for k, v in user_input.items()},
            )
        return self.async_show_form(step_id="user", data_schema=_options_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SmartCatOptionsFlow()


class SmartCatOptionsFlow(OptionsFlow):
    """Thresholds, backfill depth and retention."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit options."""
        if user_input is not None:
            return self.async_create_entry(data={k: int(v) for k, v in user_input.items()})
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(dict(self.config_entry.options))
        )
