"""Optional assumed Audio Only state; it is never reported as TV telemetry."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .entity import HisenseVidaaEntity
from .model import is_known_model
from .screen import can_screen_off, screen_off_error


def remove_inactive_screen_entities(hass, entry):
    """Options select the entity types; remove inactive registry entries."""
    registry = er.async_get(hass)
    inactive = (
        (("button", "screen_off"), ("button", "screen_on"))
        if entry.options.get("assume_screen_state", False)
        else (("switch", "audio_only_mode"),)
    )
    for platform, suffix in inactive:
        entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{suffix}")
        if entity_id:
            registry.async_remove(entity_id)


class HisenseU7QFAssumedAudioOnlySwitch(HisenseVidaaEntity, SwitchEntity):
    """ON means the screen-off macro completed, not measured panel state."""

    _attr_translation_key = "audio_only_mode"
    _attr_icon = "mdi:television-off"
    _attr_assumed_state = True

    def __init__(self, client, entry):
        super().__init__(client, entry)
        self._attr_unique_id = f"{self._entry_id}_audio_only_mode"
        self._assumed_audio_only = None
        self._source = client.current_source

    @property
    def is_on(self):
        return self._assumed_audio_only

    @property
    def available(self):
        # Screen-on must remain callable even if the last TV state is unknown.
        return self._client.connected

    @property
    def extra_state_attributes(self):
        return {"state_source": "assumed_from_commands", "screen_state_reported_by_tv": False}

    async def async_turn_on(self, **kwargs):
        if self._assumed_audio_only is True:
            return
        model = self._client.model_name or self._model
        if not is_known_model(model) or not can_screen_off(self._client):
            raise HomeAssistantError(screen_off_error(self._client, model))
        await self._run_action(self._client.screen_off, True)

    async def async_turn_off(self, **kwargs):
        await self._run_action(self._client.screen_on, False)

    async def _run_action(self, command, value):
        if not self.available:
            raise HomeAssistantError("TV MQTT connection is not available")
        source = self._client.current_source
        try:
            await self.hass.async_add_executor_job(command)
        except Exception as err:
            self._assumed_audio_only = None
            self.async_write_ha_state()
            if isinstance(err, ValueError):
                raise HomeAssistantError(str(err)) from err
            raise
        self._assumed_audio_only = (
            value if self._client.connected and (not value or self._client.current_source == source) else None
        )
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        self._client.register_state_callback(self._handle_state)
        self._client.register_disconnected_callback(self._forget_state)
        self._client.register_connected_callback(self._forget_state)
        self._client.register_picture_callback(self._handle_picture)

    async def async_will_remove_from_hass(self):
        self._client.unregister_state_callback(self._handle_state)
        self._client.unregister_disconnected_callback(self._forget_state)
        self._client.unregister_connected_callback(self._forget_state)
        self._client.unregister_picture_callback(self._handle_picture)

    def _forget_state(self, *args):
        self._assumed_audio_only = None
        self.schedule_update_ha_state()

    def _handle_state(self, *args):
        if self._source != self._client.current_source or not self._client.is_on:
            self._assumed_audio_only = None
        self._source = self._client.current_source
        self.schedule_update_ha_state()

    def _handle_picture(self, *args):
        self.schedule_update_ha_state()
