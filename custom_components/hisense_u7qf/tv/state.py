"""State models and telemetry parsers for Hisense VIDAA TV."""

from __future__ import annotations

import contextlib
from typing import Any

from ..firmware_u4 import HDR_FLAG_ID, integer_value
from ..picture_context import HDR_BUSINESS_ID, MODE_BUSINESS_ID, invalidate_picture, picture_context
from .settings import find_menu_item_by_name, parse_settings_payload
from .transitions import confirm_transitions


def apply_state_update(client: Any, data: Any) -> None:
    """Updates client runtime state attributes from TV state payload."""
    if not isinstance(data, dict):
        return
    old_source = picture_context(client)[0]
    old_hdr = client.hdr_mode

    statetype = str(data.get("statetype", "")).lower()
    if data.get("_retained", False):
        client._power_state_live = False
    elif statetype in (
        "on",
        "off",
        "fake_sleep_0",
        "fake_sleep_1",
        "screen_saver",
        "screensaver",
        "remote_launcher",
        "sourceswitch",
        "app",
        "livetv",
    ) or ("is_power_on" in data and data["is_power_on"] in (0, 1, "0", "1")):
        client._power_state_live = True
    if "sourceid" in data or "sourcename" in data or statetype == "livetv":
        client._picture_active_app = None
        client.current_app = None
        client.current_app_id = None
    elif statetype == "app":
        client._picture_active_app = "app:" + str(data.get("appid") or data.get("appname") or data.get("name") or data.get("url") or "unknown")
    elif statetype == "remote_launcher":
        client._picture_active_app = "home"
    # Match fake_sleep_0 exactly: fake_sleep_1 means the TV is waking up (immediately
    # followed by remote_launcher) and must be reported ON, not off.
    if "off" in statetype or statetype == "fake_sleep_0":
        client.state = "off"
    elif statetype == "fake_sleep_1":
        client.state = "fake_sleep_1"
    elif data.get("is_power_on") in (0, "0", False) and "is_power_on" in data:
        client.state = "off"
    elif statetype in ("screen_saver", "screensaver"):
        client.state = "screensaver"
    elif statetype in ("on", "remote_launcher", "sourceswitch", "app", "livetv") or data.get("is_power_on") in (
        1,
        "1",
        True,
    ):
        client.state = "on"

    if "sourcename" in data:
        client.current_source = data["sourcename"]
    elif "sourceid" in data:
        sid_str = str(data["sourceid"])
        if sid_str.upper() == "TV" or statetype == "livetv":
            client.current_source = "TV"
        else:
            sources = getattr(client, "sources", [])
            matched_name = None
            if sources:
                for s in sources:
                    if isinstance(s, dict) and str(s.get("sourceid", "")).strip().lower() == sid_str.strip().lower():
                        matched_name = s.get("sourcename") or s.get("displayname")
                        break
            client.current_source = matched_name or sid_str
    elif statetype == "livetv":
        client.current_source = "TV"

    if "sourceid" in data:
        client.current_source_id = str(data["sourceid"])
    elif statetype == "livetv":
        client.current_source_id = "TV"
    if "appname" in data or (statetype == "app" and "name" in data):
        client.current_app = data.get("appname") or data.get("name")
    if "appid" in data:
        client.current_app_id = str(data["appid"])
    if "channel_name" in data:
        client.current_channel = data["channel_name"]
    if "program_title" in data:
        client.current_program = data["program_title"]
    if "channel_num" in data:
        client.channel_number = str(data["channel_num"])
    if "audio_output" in data:
        client.audio_output_mode = str(data["audio_output"])
    if "hdr_mode" in data:
        client.hdr_mode = str(data["hdr_mode"])
    if client.picture_settings_version == "U4" and (
        old_source != picture_context(client)[0] or old_hdr != client.hdr_mode
    ):
        invalidate_picture(client)
        client.get_picture_settings()
    if "audio_format" in data:
        client.audio_format = str(data["audio_format"])
    if "devicename" in data or "device_name" in data or "friendly_name" in data:
        name = data.get("devicename") or data.get("device_name") or data.get("friendly_name")
        if name and str(name).strip() and str(name).strip() != "Renderer":
            client.device_name = str(name).strip()
    if "sleep_time" in data:
        with contextlib.suppress(ValueError, TypeError):
            client.sleep_timer = int(data["sleep_time"])

    if not data.get("_retained", False):
        confirm_transitions(client, data)


def apply_device_info_update(client: Any, data: Any) -> None:
    """Updates client device information attributes from TV device info payload."""
    if not isinstance(data, dict):
        return

    name = (
        data.get("devicename")
        or data.get("device_name")
        or data.get("friendly_name")
        or data.get("tv_name")
        or data.get("name")
    )
    if name and str(name).strip() and str(name).strip() != "Renderer":
        client.device_name = str(name).strip()

    model = data.get("model_name") or data.get("model_code") or data.get("model") or data.get("modelNumber") or data.get("devicemsg")
    if model and str(model).strip():
        client.model_name = str(model).strip()

    mfg = data.get("manufacturer") or data.get("brand")
    if mfg and str(mfg).strip():
        client.manufacturer = str(mfg).strip()

    fw = data.get("firmware_version") or data.get("sw_version") or data.get("version") or data.get("softwareVersion")
    if fw and str(fw).strip():
        client.firmware_version = str(fw).strip()


def apply_volume_update(client: Any, data: Any) -> None:
    """Updates client volume and mute attributes from TV volume payload."""
    if not isinstance(data, dict):
        return

    vol_type = data.get("volume_type")
    # Volume level updates on master (0), ARC/eARC (1), or unspecifed volume broadcasts
    if vol_type in (0, "0", 1, "1", None):
        if "volume_value" in data:
            with contextlib.suppress(ValueError, TypeError):
                client.volume = int(data["volume_value"])
        elif "volume" in data:
            with contextlib.suppress(ValueError, TypeError):
                client.volume = int(data["volume"])

    # Mute status updates on mute broadcast (2) or explicit is_mute/muted fields
    if vol_type in (2, "2"):
        if "volume_value" in data:
            client.muted = bool(data["volume_value"] in (1, "1", True))
        elif "is_mute" in data:
            client.muted = bool(data["is_mute"] in (1, "1", True))
        elif "muted" in data:
            client.muted = bool(data["muted"])
    elif "is_mute" in data:
        client.muted = bool(data["is_mute"] in (1, "1", True))
    elif "muted" in data:
        client.muted = bool(data["muted"])


def apply_picture_update(client: Any, data: Any) -> None:
    """Updates client picture settings from TV picture settings payload."""
    if isinstance(data, dict) and data.get("pic_setting_version"):
        client.picture_settings_version = str(data["pic_setting_version"])
    items = parse_settings_payload(data)
    full = isinstance(data, dict) and isinstance(data.get("menu_info"), list)
    before = (picture_context(client), integer_value(client, HDR_FLAG_ID))
    if full and client.picture_settings_version == "U4":
        client.picture_settings.clear()
        client.brightness = client.backlight = client.contrast = client.picture_mode = None
    for item in items:
        # Incremental value-only notifications must preserve the original name,
        # business ID and metadata for future source-specific resolution.
        previous = client.picture_settings.get(item.menu_id)
        if previous and not any(k in item.raw_data for k in ("menu_name", "name")):
            previous.value = item.value
            previous.raw_data = {**previous.raw_data, **item.raw_data}
        else:
            client.picture_settings[item.menu_id] = item
    for attribute, label in (("backlight", "Backlight"), ("brightness", "Brightness"), ("contrast", "Contrast")):
        item = find_menu_item_by_name(client.picture_settings, label)
        if item and item.raw_data.get("menu_value_type") not in ("action", "error"):
            with contextlib.suppress(ValueError, TypeError):
                setattr(client, attribute, int(item.value))
    mode = find_menu_item_by_name(client.picture_settings, "Picture Mode")
    if mode:
        client.picture_mode = str(mode.value)
    if client.picture_settings_version == "U4":
        after = (picture_context(client), integer_value(client, HDR_FLAG_ID))
        if before != after:
            client._picture_generation += 1
            if getattr(client, "_u7qf_picture_guard", False):
                from ..picture_readiness import defer_picture

                defer_picture(client)
        client.hdr_mode = after[0][1]
        if full and items:
            client._picture_snapshot.set()
        elif before != after and any(
            i.raw_data.get("menu_biz_id") in (HDR_BUSINESS_ID, MODE_BUSINESS_ID, HDR_FLAG_ID)
            or i.menu_id in (2, 84, 106)
            for i in items
        ):
            invalidate_picture(client)
            client.get_picture_settings()


def apply_sound_update(client: Any, data: Any) -> None:
    """Updates client sound settings from TV sound settings payload."""
    parsed_items = parse_settings_payload(data)
    for item in parsed_items:
        client.sound_settings[item.menu_id] = item
        if "mode" in item.name.lower():
            client.sound_mode = str(item.value)


class TvStateMixin:
    """Mixin holding all live telemetry and settings state for Hisense VIDAA TV."""

    def _init_runtime_state(self) -> None:
        """Initializes all live state variables to clean defaults."""
        self._retained_screen_state: dict[str, Any] | None = None
        self._power_state_live: bool = False
        self._picture_active_app: str | None = None
        self.connected: bool = False
        self.state: str = "unknown"
        self.volume: int = 0
        self.muted: bool = False
        self.sources: list[dict[str, Any]] = []
        self.current_source: str | None = None
        self.current_source_id: str | None = None
        self.apps: list[dict[str, Any]] = []
        self.current_app: str | None = None
        self.current_app_id: str | None = None
        self.current_channel: str | None = None
        self.current_program: str | None = None
        self.channel_number: str | None = None
        self.picture_settings_version: str | None = None
        self.picture_mode: str | None = None
        self.sound_mode: str | None = None
        self.backlight: int | None = None
        self.brightness: int | None = None
        self.contrast: int | None = None
        self.picture_settings: dict[int, Any] = {}
        self.sound_settings: dict[int, Any] = {}
        self.audio_output_mode: str | None = None
        self.hdr_mode: str | None = None
        self.audio_format: str | None = None
        self.sleep_timer: int | None = None
        self.has_notifications: bool = False
        self.device_name: str | None = None
        self.model_name: str | None = None
        self.manufacturer: str | None = None
        self.firmware_version: str | None = None

    @property
    def is_on(self) -> bool:
        """Returns True if the TV is connected and active."""
        return self.state in ("on", "screensaver", "fake_sleep_1")

    @is_on.setter
    def is_on(self, value: bool) -> None:
        """Sets the power state."""
        self.state = "on" if value else "off"
