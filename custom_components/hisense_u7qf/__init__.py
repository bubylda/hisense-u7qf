"""Hisense VIDAA TV custom component integration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, issue_registry as ir

from .compatibility import runtime_options
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_DURATION,
    CONF_ACCESS_TOKEN_TIME,
    CONF_AUTH_PROFILE,
    CONF_CERTFILE,
    CONF_CLIENT_ID,
    CONF_ENABLE_NOTIFY,
    CONF_ENABLE_PICTURE_CONTROLS,
    CONF_ENABLE_REMOTE,
    CONF_IP_ADDRESS,
    CONF_KEYFILE,
    CONF_MAC_ADDRESS,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_REFRESH_IN_STANDBY,
    CONF_REFRESH_TOKEN,
    CONF_REFRESH_TOKEN_DURATION,
    CONF_REFRESH_TOKEN_TIME,
    CONF_USE_SSL,
    CONF_USERNAME,
    DEFAULT_ENABLE_NOTIFY,
    DEFAULT_ENABLE_PICTURE_CONTROLS,
    DEFAULT_ENABLE_REMOTE,
    DEFAULT_REFRESH_IN_STANDBY,
    DEFAULT_USE_SSL,
    DOMAIN,
)
from .services import async_setup_services, async_unload_services
from .u7qf_client import U7QFClient as HisenseTvClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = [
    "media_player",
    "remote",
    "sensor",
    "binary_sensor",
    "button",
    "switch",
    "notify",
    "select",
    "number",
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class HisenseVidaaData:
    """Runtime data for Hisense VIDAA TV integration."""

    client: HisenseTvClient
    platforms: list[str]
    options: dict[str, Any]


type HisenseVidaaConfigEntry = ConfigEntry[HisenseVidaaData]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Hisense VIDAA TV integration services."""
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HisenseVidaaConfigEntry) -> bool:
    """Set up Hisense VIDAA TV from a config entry."""
    # services are registered by async_setup, but
    # async_unload_entry removes them once the last entry goes away and
    # async_setup is never called again (e.g. after an options reload).  Keep
    # the registration idempotent and re-assert it on every setup.
    await async_setup_services(hass)

    from .model import old_integration_active

    if old_integration_active(hass, entry.data[CONF_IP_ADDRESS]):
        raise ConfigEntryNotReady("Disable the old hisense_vidaa entry for this TV before starting Hisense U7QF")

    # Public options cannot select another generation or turn off required TLS.
    effective_options = runtime_options(dict(entry.options), entry.data.get(CONF_MODEL))
    if effective_options != dict(entry.options):
        hass.config_entries.async_update_entry(entry, options=effective_options)
    data = entry.data
    mac = data.get(CONF_MAC_ADDRESS)
    if not mac:
        try:
            from homeassistant.helpers.device_registry import format_mac

            from .discovery import get_arp_mac

            raw_mac = await hass.async_add_executor_job(get_arp_mac, data[CONF_IP_ADDRESS])
            if raw_mac:
                mac = format_mac(raw_mac)
                hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_MAC_ADDRESS: mac},
                    unique_id=entry.unique_id or mac,
                )
        except Exception:
            pass

    use_ssl = entry.options.get(CONF_USE_SSL, data.get(CONF_USE_SSL, DEFAULT_USE_SSL))
    certfile = entry.options.get(CONF_CERTFILE, data.get(CONF_CERTFILE))
    keyfile = entry.options.get(CONF_KEYFILE, data.get(CONF_KEYFILE))

    client = HisenseTvClient(
        ip=data[CONF_IP_ADDRESS],
        compatibility_options=runtime_options(dict(entry.options), data.get(CONF_MODEL)),
        mac=mac,
        client_id=data.get(CONF_CLIENT_ID),
        username=data.get(CONF_USERNAME),
        password=data.get(CONF_PASSWORD),
        access_token=data.get(CONF_ACCESS_TOKEN),
        access_token_time=data.get(CONF_ACCESS_TOKEN_TIME),
        access_token_duration=data.get(CONF_ACCESS_TOKEN_DURATION),
        refresh_token=data.get(CONF_REFRESH_TOKEN),
        refresh_token_time=data.get(CONF_REFRESH_TOKEN_TIME),
        refresh_token_duration=data.get(CONF_REFRESH_TOKEN_DURATION),
        auth_profile=entry.options.get(CONF_AUTH_PROFILE, data.get(CONF_AUTH_PROFILE, "auto")),
        refresh_in_standby=entry.options.get(CONF_REFRESH_IN_STANDBY, DEFAULT_REFRESH_IN_STANDBY),
        certfile=certfile,
        keyfile=keyfile,
        use_ssl=use_ssl,
    )
    client._loop = hass.loop

    # Check for missing certificates and manage Repairs issue
    if use_ssl and (
        not client.certfile
        or not client.keyfile
        or not os.path.isfile(client.certfile)
        or not os.path.isfile(client.keyfile)
    ):
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"certificate_missing_{entry.entry_id}",
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="certificate_missing",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, f"certificate_missing_{entry.entry_id}")

    # Callback to persist token updates in Home Assistant config entry
    def update_entry_tokens(refreshed_client: HisenseTvClient) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: refreshed_client.access_token,
                CONF_ACCESS_TOKEN_TIME: refreshed_client.access_token_time,
                CONF_ACCESS_TOKEN_DURATION: refreshed_client.access_token_duration,
                CONF_REFRESH_TOKEN: refreshed_client.refresh_token,
                CONF_REFRESH_TOKEN_TIME: refreshed_client.refresh_token_time,
                CONF_REFRESH_TOKEN_DURATION: refreshed_client.refresh_token_duration,
            },
        )

    client.register_token_refreshed_callback(lambda c: hass.loop.call_soon_threadsafe(update_entry_tokens, c))

    def _handle_auth_failed(failed_client: HisenseTvClient) -> None:
        """Raise a persistent Repairs issue and start the reauth flow."""
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"auth_token_invalidated_{entry.entry_id}",
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="auth_token_invalidated",
            translation_placeholders={"ip_address": failed_client.ip},
            # gives the fix flow the entry it must re-pair.
            data={"entry_id": entry.entry_id},
        )
        entry.async_start_reauth(hass)

    client.register_auth_failed_callback(lambda c: hass.loop.call_soon_threadsafe(_handle_auth_failed, c))

    # Check and refresh tokens in executor
    updated = await hass.async_add_executor_job(client.check_and_refresh_token)
    if updated:
        update_entry_tokens(client)

    # Start running background thread loop for MQTT client in executor
    platforms_to_setup = [
        "media_player",
        "sensor",
        "binary_sensor",
        "button",
        "switch",
        "select",
    ]
    if entry.options.get(CONF_ENABLE_PICTURE_CONTROLS, DEFAULT_ENABLE_PICTURE_CONTROLS):
        platforms_to_setup.append("number")
    if entry.options.get(CONF_ENABLE_REMOTE, DEFAULT_ENABLE_REMOTE):
        platforms_to_setup.append("remote")
    if entry.options.get(
        CONF_ENABLE_NOTIFY,
        getattr(client, "has_notifications", DEFAULT_ENABLE_NOTIFY),
    ):
        platforms_to_setup.append("notify")

    # Start running background thread loop for MQTT client in executor.
    # connect_and_run builds the TLS context, so a missing/invalid
    # certfile or keyfile raises out of paho's tls_set.  Without this guard the
    # raw traceback escapes setup instead of a clean, retried setup failure.
    try:
        await hass.async_add_executor_job(client.connect_and_run)
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to Hisense TV at {client.ip}: {err}") from err

    from .model import async_refresh_identity

    await async_refresh_identity(hass, entry, client)

    entry.runtime_data = HisenseVidaaData(
        client=client,
        platforms=platforms_to_setup,
        options=dict(entry.options),
    )

    from .screen_switch import remove_inactive_screen_entities

    remove_inactive_screen_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, platforms_to_setup)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up the persistent Repairs issues belonging to a removed entry."""
    # is_persistent issues survive entry removal and would
    # keep showing an unfixable card for a TV that is no longer configured.
    ir.async_delete_issue(hass, DOMAIN, f"certificate_missing_{entry.entry_id}")
    ir.async_delete_issue(hass, DOMAIN, f"auth_token_invalidated_{entry.entry_id}")


async def update_listener(hass: HomeAssistant, entry: HisenseVidaaConfigEntry) -> None:
    """Handle options update."""
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data and runtime_data.options == dict(entry.options):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HisenseVidaaConfigEntry) -> bool:
    """Unload a config entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    platforms = runtime_data.platforms if runtime_data else PLATFORMS
    client = runtime_data.client if runtime_data else None

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        if client:
            await hass.async_add_executor_job(client.disconnect)
        await async_unload_services(hass)
    return unload_ok
