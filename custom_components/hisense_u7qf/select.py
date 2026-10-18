"""Select platform for Hisense VIDAA TV integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import HisenseTvClient
from .const import (
    CONF_ENABLE_PICTURE_CONTROLS,
    CONF_ENABLE_SOUND_CONTROLS,
    DEFAULT_ENABLE_PICTURE_CONTROLS,
    DEFAULT_ENABLE_SOUND_CONTROLS,
    DOMAIN,
)
from .entity import HisenseVidaaEntity
from .firmware_u4 import model_setting_choices, uses_u4_model_table
from .input_select import HisenseU7QFInputSelect
from .motion import MOTION_BUSINESS_ID, MOTION_LABELS_KEY, MOTION_VALUES_KEY, labels_from_options, motion_item
from .picture_modes import current_mode_label, firmware_mode_choices, mode_bank
from .picture_readiness import picture_ready

if TYPE_CHECKING:
    from . import HisenseVidaaConfigEntry
from .tv.settings import (
    DEFAULT_MENU_ID_PICTURE_MODE,
    DEFAULT_MENU_ID_SOUND_MODE,
    STANDARD_PICTURE_MODES,
    STANDARD_SOUND_MODES,
    find_menu_item_by_name,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

class HisenseVidaaPictureModeSelect(HisenseVidaaEntity, SelectEntity):
    """Hisense VIDAA Picture Mode selector."""

    _attr_translation_key = "picture_mode"

    def __init__(
        self,
        client: HisenseTvClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(client=client, entry=entry)
        self._attr_unique_id = f"{self._entry_id}_picture_mode"
        self._current_mode = "Standard"

    @property
    def unique_id(self) -> str:
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        ready = super().available and bool(self._client and self._client.connected) and picture_ready(self._client)
        if getattr(self._client, "picture_settings_version", None) == "U4":
            return ready and bool(firmware_mode_choices(self._client))
        return ready

    async def async_added_to_hass(self) -> None:
        self._client.register_picture_callback(self._handle_picture_update)

    async def async_will_remove_from_hass(self) -> None:
        self._client.unregister_picture_callback(self._handle_picture_update)

    @property
    def options(self) -> list[str]:
        if getattr(self._client, "picture_settings_version", None) == "U4":
            return list(firmware_mode_choices(self._client))
        pm_item = find_menu_item_by_name(self._client.picture_settings, "Picture Mode", DEFAULT_MENU_ID_PICTURE_MODE)
        if pm_item and pm_item.options:
            return pm_item.options
        if getattr(self._client, "picture_settings_version", None) == "U4":
            return []
        return STANDARD_PICTURE_MODES

    @property
    def current_option(self) -> str | None:
        if getattr(self._client, "picture_settings_version", None) == "U4":
            return current_mode_label(self._client)
        if self._client.picture_mode:
            return self._client.picture_mode
        return self._current_mode

    def _handle_picture_update(self, data: dict[str, Any]) -> None:
        if self._client.picture_mode:
            self._current_mode = self._client.picture_mode
        self.schedule_update_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change picture mode option."""
        if getattr(self._client, "picture_settings_version", None) == "U4" and option not in self.options:
            raise ValueError("Picture mode choices have not been reported by this firmware")
        if getattr(self._client, "picture_settings_version", None) == "U4":
            from .picture_context import guarded_picture_command, picture_context

            expected = (picture_context(self._client), self._client._picture_generation)
            await self.hass.async_add_executor_job(
                guarded_picture_command, self._client, expected, self._client.set_picture_mode, option
            )
            await self.hass.async_add_executor_job(self._client.get_picture_settings)
        else:
            self._current_mode = option
            await self.hass.async_add_executor_job(self._client.set_picture_mode, option)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        if getattr(self._client, "picture_settings_version", None) != "U4":
            return {}
        source, signal = mode_bank(self._client)
        return {
            "source": source,
            "signal_profile": signal,
            "raw_mode": self._client.picture_mode,
            "mode_names_available": bool(firmware_mode_choices(self._client)),
            "mapping_source": "N0712 frontend" if uses_u4_model_table(self._client) else "reported metadata",
        }


class HisenseVidaaSoundModeSelect(HisenseVidaaEntity, SelectEntity):
    """Hisense VIDAA Sound Mode selector."""

    _attr_translation_key = "sound_mode"

    def __init__(
        self,
        client: HisenseTvClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(client=client, entry=entry)
        self._attr_unique_id = f"{self._entry_id}_sound_mode"
        self._current_mode = "Standard"

    @property
    def unique_id(self) -> str:
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and bool(self._client and self._client.connected)

    async def async_added_to_hass(self) -> None:
        self._client.register_sound_callback(self._handle_sound_update)

    async def async_will_remove_from_hass(self) -> None:
        self._client.unregister_sound_callback(self._handle_sound_update)

    @property
    def options(self) -> list[str]:
        sm_item = find_menu_item_by_name(self._client.sound_settings, "Sound Mode", DEFAULT_MENU_ID_SOUND_MODE)
        if sm_item and sm_item.options:
            return sm_item.options
        return STANDARD_SOUND_MODES

    @property
    def current_option(self) -> str | None:
        if self._client.sound_mode:
            return self._client.sound_mode
        return self._current_mode

    def _handle_sound_update(self, data: dict[str, Any]) -> None:
        if self._client.sound_mode:
            self._current_mode = self._client.sound_mode
        self.schedule_update_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change sound mode option."""
        self._current_mode = option
        await self.hass.async_add_executor_job(self._client.set_sound_mode, option)
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HisenseVidaaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hisense VIDAA select platform."""
    client: HisenseTvClient = config_entry.runtime_data.client

    enable_picture = config_entry.options.get(CONF_ENABLE_PICTURE_CONTROLS, DEFAULT_ENABLE_PICTURE_CONTROLS)
    enable_sound = config_entry.options.get(CONF_ENABLE_SOUND_CONTROLS, DEFAULT_ENABLE_SOUND_CONTROLS)

    # Clean up disabled/unsupported entities from entity registry
    entity_reg = er.async_get(hass)
    if not enable_picture:
        unique_id = f"{config_entry.entry_id}_picture_mode"
        if entity_id := entity_reg.async_get_entity_id("select", DOMAIN, unique_id):
            entity_reg.async_remove(entity_id)

    if not enable_sound:
        unique_id = f"{config_entry.entry_id}_sound_mode"
        if entity_id := entity_reg.async_get_entity_id("select", DOMAIN, unique_id):
            entity_reg.async_remove(entity_id)

    # The universal selector used invented remote keys and volume_type is not
    # an audio-output enum. Do not leave its old entity callable after upgrade.
    stale = entity_reg.async_get_entity_id("select", DOMAIN, f"{config_entry.entry_id}_audio_output_select")
    if stale:
        entity_reg.async_remove(stale)

    entities: list[SelectEntity] = [
        HisenseU7QFInputSelect(client, config_entry),
    ]
    if enable_picture:
        entities.append(HisenseVidaaPictureModeSelect(client=client, entry=config_entry))
        entities.append(HisenseVidaaMotionSmoothingSelect(client=client, entry=config_entry))
        entities.append(HisenseVidaaLocalDimmingSelect(client=client, entry=config_entry))
    if enable_sound:
        entities.append(HisenseVidaaSoundModeSelect(client=client, entry=config_entry))

    async_add_entities(entities)


class HisenseVidaaMotionSmoothingSelect(HisenseVidaaEntity, SelectEntity):
    """MEMC selection limited to values actually observed from this television."""

    _attr_translation_key = "motion_smoothing"
    _attr_icon = "mdi:motion-play-outline"

    _business_id = MOTION_BUSINESS_ID
    _storage_key = MOTION_VALUES_KEY
    _labels_key = MOTION_LABELS_KEY
    _suffix = "motion_smoothing"

    def _item(self):
        return motion_item(self._client, self._business_id)

    def __init__(self, client: HisenseTvClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{self._entry_id}_{self._suffix}"
        stored = entry.data.get(self._storage_key, {})
        self._contexts = dict(stored) if isinstance(stored, dict) else {}
        self._known_values = set()
        self._picture_context_key = None
        self._labels = labels_from_options(entry.options.get(self._labels_key, {}))
        self._observe()

    def _observe(self) -> None:
        from .picture_context import context_key

        key = context_key(self._client)
        if key != self._picture_context_key:
            self._picture_context_key = key
            stored = self._contexts.get(key, [])
            self._known_values = {int(v) for v in stored if isinstance(v, (int, str)) and str(v).lstrip("-").isdigit()}
        from .picture_context import live_observed_values

        self._known_values.update(live_observed_values(self._client, self._business_id))
        item = self._item()
        if item:
            try:
                if len(self._known_values) < 64:
                    self._known_values.add(int(item.value))
                    self._contexts[key] = sorted(self._known_values)
            except (ValueError, TypeError):
                pass

    @property
    def available(self) -> bool:
        return (super().available and self._client.connected and self._item() is not None
                and picture_ready(self._client) and bool(self._choices()))

    def _choices(self) -> dict[str, int]:
        self._observe()
        choices = model_setting_choices(self._client, self._business_id)
        if uses_u4_model_table(self._client):
            return choices
        names = {v: self._labels.get(str(v), str(v)) for v in sorted(self._known_values)}
        return {
            f"{name} [{code}]" if list(names.values()).count(name) > 1 else name: code for code, name in names.items()
        }

    @property
    def options(self) -> list[str]:
        return list(self._choices())

    @property
    def current_option(self) -> str | None:
        item = self._item()
        if item is None:
            return None
        return next((name for name, code in self._choices().items() if code == int(item.value)), None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._item()
        return {
            "menu_id": item.menu_id if item else None,
            "business_id": self._business_id,
            "observed_values": sorted(self._known_values),
            "raw_value": item.value if item else None,
            "picture_context": self._picture_context_key,
            "available_values": self._choices(),
            "mapping_source": "N0712 frontend" if uses_u4_model_table(self._client) else "device observations",
        }

    async def async_added_to_hass(self) -> None:
        self._client.register_picture_callback(self._handle_picture)

    async def async_will_remove_from_hass(self) -> None:
        self._client.unregister_picture_callback(self._handle_picture)

    def _handle_picture(self, data: Any) -> None:
        self._observe()
        # Evidence is entry.data, not options: learning a mode must not trigger
        # integration reloads or change pairing/settings.
        values = {**self._contexts}
        if values != self._entry.data.get(self._storage_key, {}) and self.hass:

            def persist():
                self.hass.config_entries.async_update_entry(
                    self._entry, data={**self._entry.data, self._storage_key: values}
                )

            self.hass.loop.call_soon_threadsafe(persist)
        self.schedule_update_ha_state()

    async def async_select_option(self, option: str) -> None:
        self._observe()
        choices = [self._choices()[option]] if option in self._choices() else []
        item = self._item()
        if not self.available or item is None or len(choices) != 1:
            raise ValueError("Select an unambiguous picture value observed from this TV")
        from .picture_context import guarded_picture_command, picture_context

        expected = (picture_context(self._client), self._client._picture_generation)
        await self.hass.async_add_executor_job(
            guarded_picture_command, self._client, expected, self._client.set_picture_setting, item.menu_id, choices[0]
        )
        # A submitted command does not change the observed value. Query the
        # read-only menu for confirmation, without repeating the write.
        await self.hass.async_add_executor_job(self._client.get_picture_settings)


class HisenseVidaaLocalDimmingSelect(HisenseVidaaMotionSmoothingSelect):
    """Local-dimming intensity; raw codes until menu labels are verified."""

    _attr_translation_key = "local_dimming"
    _attr_icon = "mdi:brightness-6"
    _business_id = "de.loewe.sl2.i32.video.autodimming.video"
    _storage_key = "local_dimming_observed_values"
    _labels_key = "local_dimming_labels"
    _suffix = "local_dimming"
