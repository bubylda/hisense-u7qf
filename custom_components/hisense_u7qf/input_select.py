"""Discovered input choices, using one guarded ID-only command."""

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError

from .compatibility import selectable_sources
from .entity import HisenseVidaaEntity
from .tv.navigation import resolve_source


class HisenseU7QFInputSelect(HisenseVidaaEntity, SelectEntity):
    _attr_translation_key = "input"
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, client, entry):
        super().__init__(client, entry)
        self._attr_unique_id = f"{self._entry_id}_input"

    def _choices(self):
        sources = selectable_sources(self._client)
        choices = {}
        for source in sources:
            if "sourceid" not in source:
                continue
            name = str(source.get("sourcename") or source["sourceid"])
            display = source.get("displayname")
            label = (
                f"{display} ({name})"
                if self._options.get("enable_cec_names", True) and display and display != name
                else name
            )
            if label in choices:
                label = f"{label} ({source['sourceid']})"
            choices[label] = source
        return choices

    @property
    def options(self):
        return list(self._choices())

    @property
    def current_option(self):
        # P0219 broadcasts symbolic sourceid="HDMI3" while sourcelist gives
        # numeric ID6. Resolve the observed identifier against the live list.
        source_id, _ = resolve_source(
            self._client.sources, str(self._client.current_source_id or self._client.current_source or "")
        )
        return next(
            (label for label, source in self._choices().items() if str(source["sourceid"]) == str(source_id)), None
        )

    @property
    def available(self):
        return self._client.connected and bool(self._choices())

    async def async_select_option(self, option):
        source = self._choices().get(option)
        if not self.available or source is None:
            raise HomeAssistantError("Select an input reported by this television")
        try:
            await self.hass.async_add_executor_job(
                self._client.change_source, str(source["sourceid"]), source.get("sourcename")
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_added_to_hass(self):
        self._client.register_sourcelist_callback(self._update)
        self._client.register_state_callback(self._update)
        self._client.register_connected_callback(self._update)
        self._client.register_disconnected_callback(self._update)

    async def async_will_remove_from_hass(self):
        self._client.unregister_sourcelist_callback(self._update)
        self._client.unregister_state_callback(self._update)
        self._client.unregister_connected_callback(self._update)
        self._client.unregister_disconnected_callback(self._update)

    def _update(self, *args):
        self.schedule_update_ha_state()
