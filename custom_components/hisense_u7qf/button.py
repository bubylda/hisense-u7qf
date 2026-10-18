"""Diagnostic utility buttons for Hisense VIDAA TV."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import HisenseTvClient
from .const import (
    CONF_ENABLE_PICTURE_CONTROLS,
    CONF_ENABLE_REMOTE,
    CONF_ENABLE_SOUND_CONTROLS,
    DEFAULT_ENABLE_REMOTE,
)
from .discovery import get_tv_timestamp
from .entity import HisenseVidaaEntity
from .tv.aliases import KEY_ALIASES

if TYPE_CHECKING:
    from . import HisenseVidaaConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HisenseVidaaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hisense VIDAA buttons based on a config entry."""
    client: HisenseTvClient = entry.runtime_data.client

    entities: list[ButtonEntity] = [
        HisenseVidaaForceReconnectButton(client, entry),
        HisenseVidaaProbeCapabilitiesButton(client, entry),
    ]

    if not entry.options.get("assume_screen_state", False):
        entities.extend(
            [HisenseU7QFScreenButton(client, entry, off=True), HisenseU7QFScreenButton(client, entry, off=False)]
        )

    if entry.options.get(CONF_ENABLE_REMOTE, DEFAULT_ENABLE_REMOTE):
        entities.extend(HisenseVidaaNavigationButton(client, entry, command) for command in NAVIGATION_COMMANDS)
    async_add_entities(entities)


NAVIGATION_COMMANDS = {
    "up": "mdi:chevron-up",
    "down": "mdi:chevron-down",
    "left": "mdi:chevron-left",
    "right": "mdi:chevron-right",
    "ok": "mdi:checkbox-marked-circle-outline",
    "back": "mdi:keyboard-return",
    "home": "mdi:home-outline",
    "menu": "mdi:menu",
    "exit": "mdi:exit-to-app",
}


class HisenseVidaaNavigationButton(HisenseVidaaEntity, ButtonEntity):
    """A single menu key exposed as a normal device control, not diagnostics."""

    def __init__(self, client: HisenseTvClient, entry: ConfigEntry, command: str) -> None:
        super().__init__(client, entry)
        if command not in NAVIGATION_COMMANDS:
            raise ValueError("Unknown navigation command")
        self._command = command
        self._attr_unique_id = f"{self._entry_id}_remote_{command}"
        self._attr_translation_key = f"remote_{command}"
        self._attr_icon = NAVIGATION_COMMANDS[command]

    @property
    def available(self) -> bool:
        return super().available and self._client.connected and self._client.is_on

    async def async_added_to_hass(self) -> None:
        self._client.register_state_callback(self._handle_update)
        self._client.register_connected_callback(self._handle_update)
        self._client.register_disconnected_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        self._client.unregister_state_callback(self._handle_update)
        self._client.unregister_connected_callback(self._handle_update)
        self._client.unregister_disconnected_callback(self._handle_update)

    def _handle_update(self, *args) -> None:
        self.schedule_update_ha_state()

    async def async_press(self) -> None:
        if not self.available:
            raise ValueError("TV is not ready for a navigation key")
        await self.hass.async_add_executor_job(self._client.send_key, KEY_ALIASES[self._command])


class HisenseVidaaBaseButton(HisenseVidaaEntity, ButtonEntity):
    """Base button for Hisense VIDAA TV."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC


class HisenseVidaaForceReconnectButton(HisenseVidaaBaseButton):
    """Button to force reconnect the MQTT client."""

    _attr_translation_key = "force_reconnect"
    _attr_icon = "mdi:lan-connect"

    def __init__(self, client: HisenseTvClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{self._entry_id}_force_reconnect"

    async def async_press(self) -> None:
        """Handle button press."""
        _LOGGER.info("Manually forcing MQTT reconnection to TV at %s", self._client.ip)
        await self.hass.async_add_executor_job(self._client.disconnect)
        await self.hass.async_add_executor_job(self._client.connect_and_run)


class HisenseVidaaSyncClockButton(HisenseVidaaBaseButton):
    """Button to query and verify the TV's UPnP clock time."""

    _attr_translation_key = "sync_clock"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, client: HisenseTvClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{self._entry_id}_sync_clock"

    async def async_press(self) -> None:
        """Handle button press."""
        tv_ts = await self.hass.async_add_executor_job(get_tv_timestamp, self._client.ip, 2.0)
        if tv_ts:
            _LOGGER.info("Successfully fetched live TV timestamp: %s (Epoch: %d)", self._client.ip, tv_ts)
        else:
            _LOGGER.warning("Could not fetch UPnP timestamp from TV at %s", self._client.ip)


class HisenseVidaaProbeCapabilitiesButton(HisenseVidaaBaseButton):
    """Button to actively query and probe live TV picture and sound menu capabilities."""

    _attr_translation_key = "probe_capabilities"
    _attr_icon = "mdi:television-guide"

    def __init__(self, client: HisenseTvClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{self._entry_id}_probe_capabilities"

    async def async_press(self) -> None:
        """Handle button press to probe capabilities."""
        if not self._client.connected:
            _LOGGER.warning("[%s] Cannot probe capabilities: TV is not connected via MQTT", self._client.ip)
            return

        _LOGGER.info("[%s] Probing TV picture and sound menu capabilities over MQTT...", self._client.ip)
        await self.hass.async_add_executor_job(self._client.get_picture_settings)
        await self.hass.async_add_executor_job(self._client.get_sound_settings)
        await asyncio.sleep(2.0)

        pic_supported = bool(self._client.picture_settings)
        sound_supported = bool(self._client.sound_settings)

        _LOGGER.info(
            "[%s] Capability probe complete: Picture Menu: %s (%d items), Sound Menu: %s (%d items)",
            self._client.ip,
            "Supported" if pic_supported else "Unsupported",
            len(self._client.picture_settings) if pic_supported else 0,
            "Supported" if sound_supported else "Unsupported",
            len(self._client.sound_settings) if sound_supported else 0,
        )

        if pic_supported or sound_supported:
            new_options = {
                **self._entry.options,
                CONF_ENABLE_PICTURE_CONTROLS: pic_supported
                or self._entry.options.get(CONF_ENABLE_PICTURE_CONTROLS, False),
                CONF_ENABLE_SOUND_CONTROLS: sound_supported
                or self._entry.options.get(CONF_ENABLE_SOUND_CONTROLS, False),
            }
            self.hass.config_entries.async_update_entry(self._entry, options=new_options)


class HisenseVidaaTriggerReauthButton(HisenseVidaaBaseButton):
    """Button to manually initiate re-pairing and re-authentication with the TV."""

    _attr_translation_key = "trigger_reauth"
    _attr_icon = "mdi:cellphone-key"

    def __init__(self, client: HisenseTvClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{self._entry_id}_trigger_reauth"

    async def async_press(self) -> None:
        """Handle button press to trigger re-authentication flow."""
        _LOGGER.info("[%s] Manually triggering re-pairing flow for TV", self._client.ip)
        self._entry.async_start_reauth(self.hass)


class HisenseU7QFScreenButton(HisenseVidaaNavigationButton):
    """Action buttons: the firmware does not report an Audio Only switch state."""

    def __init__(self, client, entry, off):
        super().__init__(client, entry, "exit")
        self._screen_off = off
        suffix = "screen_off" if off else "screen_on"
        self._attr_unique_id = f"{self._entry_id}_{suffix}"
        self._attr_translation_key = suffix
        self._attr_icon = "mdi:television-off" if off else "mdi:television"

    @property
    def available(self):
        from .model import is_known_model
        from .screen import can_screen_off

        if not self._screen_off:
            return self._client.connected
        return is_known_model(self._client.model_name or self._model) and can_screen_off(self._client)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._client.register_picture_callback(self._handle_update)

    async def async_will_remove_from_hass(self):
        self._client.unregister_picture_callback(self._handle_update)
        await super().async_will_remove_from_hass()

    async def async_press(self):
        if not self.available:
            raise HomeAssistantError("Screen action is not available in this TV context")
        command = self._client.screen_off if self._screen_off else self._client.screen_on
        try:
            await self.hass.async_add_executor_job(command)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
