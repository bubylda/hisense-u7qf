"""Diagnostics support for Hisense VIDAA TV."""

from __future__ import annotations

import contextlib
import time
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .model import is_known_model
from .picture_readiness import picture_ready
from .screen import screen_off_blockers

if TYPE_CHECKING:
    from . import HisenseVidaaConfigEntry

TO_REDACT = {
    "access_token",
    "refresh_token",
    "password",
    "username",
    "client_id",
    "mac_address",
    "mac_wifi",
    "mac_ethernet",
    # the client_id is derived from the MAC and is embedded
    # in every topic basepath, so those keys leak it as well.
    "serial_number",
    "topic_tv_ui",
    "topic_tv_ps",
    "topic_mobile",
    "upnp_raw",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HisenseVidaaConfigEntry | ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None and hasattr(hass, "data") and isinstance(hass.data, dict):
        runtime_data = hass.data.get(DOMAIN, {}).get(getattr(entry, "entry_id", ""))
    if isinstance(runtime_data, dict):
        client = runtime_data.get("client")
    elif runtime_data is not None:
        client = getattr(runtime_data, "client", runtime_data)
    else:
        client = None

    # bound unconditionally - a not-loaded entry (NOT_LOADED /
    # SETUP_RETRY) previously raised UnboundLocalError (HTTP 500) exactly when a
    # bug report was being collected.
    fp = None
    tv_diagnostics = None
    if client:
        now = int(time.time())
        token_expires_in = None
        if client.access_token_time and client.access_token_duration:
            expiry = client.access_token_time + (client.access_token_duration * 86400)
            token_expires_in = expiry - now

        fp = None
        with contextlib.suppress(Exception):
            fp = await hass.async_add_executor_job(client.get_device_fingerprint, 1.5)
        tv_diagnostics = {
            "connected": client.connected,
            "model": (fp or {}).get("model_name") or entry.data.get("model"),
            "firmware": (fp or {}).get("firmware_version") or entry.data.get("sw_version"),
            "recognized_model": is_known_model((fp or {}).get("model_name") or entry.data.get("model")),
            "audio_only_blockers": screen_off_blockers(client, (fp or {}).get("model_name") or entry.data.get("model")),
            "observed_source_id": getattr(client, "current_source_id", None),
            "compatibility": asdict(client.compatibility)
            if is_dataclass(getattr(client, "compatibility", None))
            else None,
            "sources": getattr(client, "sources", []),
            "picture_settings": [
                {
                    "menu_id": item.menu_id,
                    "name": item.name,
                    "value": item.value,
                    "value_type": item.raw_data.get("menu_value_type"),
                    "business_id": item.raw_data.get("menu_biz_id"),
                }
                for item in getattr(client, "picture_settings", {}).values()
            ],
            "picture_settings_version": getattr(client, "picture_settings_version", None),
            "picture_profile_ready": picture_ready(client),
            "research": {
                "observed_source_id": getattr(client, "current_source_id", None),
                "model": getattr(client, "model_name", None),
                "firmware": getattr(client, "firmware_version", None),
            }
            if getattr(getattr(client, "compatibility", None), "enable_research_tools", False)
            else None,
            "pending_power": getattr(client, "_pending_power", None),
            "pending_source": getattr(client, "_pending_source", None),
            "last_command_outcome": getattr(client, "last_command_outcome", None),
            "mqtt_trace": client.trace.recent()
            if getattr(getattr(client, "compatibility", None), "mqtt_trace", False)
            else [],
            "auth_profile": client.auth_profile,
            "source": getattr(client, "current_source", None),
            "current_app": getattr(client, "current_app", None),
            "volume": getattr(client, "volume", None),
            "muted": getattr(client, "muted", False),
            "tv_state": getattr(client, "state", None),
            "access_token_duration_days": client.access_token_duration,
            "access_token_expires_in_seconds": token_expires_in,
            "refresh_token_duration_days": client.refresh_token_duration,
            "has_refresh_token": bool(client.refresh_token),
            "topic_tv_ui": getattr(client, "topicTVUIBasepath", None),
            "topic_tv_ps": getattr(client, "topicTVPSBasepath", None),
            "topic_mobile": getattr(client, "topicMobiBasepath", None),
        }

    # redact the whole payload, not just entry.data: the
    # fingerprint dict carries mac_wifi/mac_ethernet/serial_number and the topic
    # keys embed the MAC-derived client_id.
    return async_redact_data(
        {
            "entry": {
                "entry_id": entry.entry_id,
                "version": getattr(entry, "version", 1),
                "domain": getattr(entry, "domain", DOMAIN),
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
                "pref_disable_new_entities": getattr(entry, "pref_disable_new_entities", False),
                "pref_disable_polling": getattr(entry, "pref_disable_polling", False),
            },
            "client": tv_diagnostics,
            "device_fingerprint": fp,
        },
        TO_REDACT,
    )
