"""One-time migration of navigation controls on automatic dashboards."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Hide existing navigation buttons once, keeping IDs and user choices."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        from .button import NAVIGATION_COMMANDS

        registry = er.async_get(hass)
        navigation_ids = {f"{entry.entry_id}_remote_{command}" for command in NAVIGATION_COMMANDS}
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
            if (
                entity.domain == "button"
                and entity.unique_id in navigation_ids
                and entity.hidden_by is None
            ):
                registry.async_update_entity(entity.entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION)
        hass.config_entries.async_update_entry(entry, minor_version=2)
    return True
