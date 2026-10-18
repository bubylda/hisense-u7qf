"""Only user-facing choices for the U7QF integration."""

from typing import Any

import voluptuous as vol
from homeassistant import config_entries

from .compatibility import runtime_options


class HisenseVidaaOptionsFlowHandler(config_entries.OptionsFlow):
    """Transport, model policy and certificate selection are fixed internally."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            allowed = {
                k: user_input[k]
                for k in (
                    "enable_wol",
                    "include_apps_in_sources",
                    "enable_cec_names",
                    "hide_tuner_sources",
                    "assume_screen_state",
                )
                if k in user_input
            }
            return self.async_create_entry(
                title="", data=runtime_options({**self.config_entry.options, **allowed}, None)
            )
        defaults = {
            "enable_wol": True,
            "include_apps_in_sources": True,
            "enable_cec_names": True,
            "hide_tuner_sources": True,
            "assume_screen_state": False,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(key, default=self.config_entry.options.get(key, value)): bool
                    for key, value in defaults.items()
                }
            ),
        )
