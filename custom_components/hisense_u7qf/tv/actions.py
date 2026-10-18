"""TV actions and command execution for Hisense VIDAA TV."""

from __future__ import annotations

import contextlib
import json
import logging
import time
from typing import TYPE_CHECKING

from ..compatibility import policy, selectable_sources
from .navigation import (
    get_next_cycled_source,
    match_app,
    resolve_command_key,
    resolve_source,
)
from .settings import (
    get_picture_settings,
    get_sound_settings,
    set_backlight,
    set_brightness,
    set_contrast,
    set_picture_mode,
    set_picture_setting,
    set_sound_mode,
    set_sound_setting,
)
from .transitions import begin_transition

if TYPE_CHECKING:
    from ..client import HisenseTvClient

_LOGGER = logging.getLogger(__name__)


def query_initial_state(client: HisenseTvClient, min_interval: float = 3.0) -> None:
    """Queries initial state, volume, source list, app list, and settings from TV."""
    if not (client.connected and client.mqtt_client):
        return

    now = time.time()
    with getattr(client, "_query_lock", contextlib.nullcontext()):
        last_time = getattr(client, "_last_initial_query_time", 0.0)
        if now - last_time < min_interval:
            _LOGGER.debug(
                "[%s] Suppressing duplicate query_initial_state call (%.2fs since last query)",
                client.ip,
                now - last_time,
            )
            return
        client._last_initial_query_time = now

        # The TV already broadcasts its live state automatically on
        # /remoteapp/mobile/broadcast/ui_service/state upon MQTT connect.
        # Do NOT publish actions/gettvstate: on VIDAA firmware, gettvstate
        # is the pairing challenge trigger that commands the TV to pop up a PIN.
        client.mqtt_client.publish(client.topicTVUIBasepath + "actions/capability", "")
        time.sleep(0.05)
        client.mqtt_client.publish(client.topicTVPSBasepath + "actions/getvolume", "")
        time.sleep(0.05)
        client.mqtt_client.publish(client.topicTVUIBasepath + "actions/sourcelist", "")
        time.sleep(0.05)
        client.mqtt_client.publish(client.topicTVUIBasepath + "actions/applist", "")
        time.sleep(0.05)
        client.mqtt_client.publish(client.topicTVPSBasepath + "actions/getdeviceinfo", "")
        time.sleep(0.05)
        client.mqtt_client.publish(client.topicTVPSBasepath + "actions/gettvinfo", "")
        controls = getattr(client, "_compatibility_options", {})
        if policy(client).extended_discovery or controls.get("enable_picture_controls"):
            client.get_picture_settings()
        if policy(client).extended_discovery or controls.get("enable_sound_controls"):
            client.get_sound_settings()


def show_message(client: HisenseTvClient, message: str, title: str | None = None, duration: int = 5) -> bool:
    """Displays an on-screen toast popup notification on the TV."""
    if not client.connected or not client.mqtt_client:
        _LOGGER.debug("[%s] Cannot show toast message: TV MQTT client not connected", getattr(client, "ip", "unknown"))
        return False

    payload_dict = {
        "message": message,
        "title": title or "",
        "duration": duration,
        "type": "notify",
    }
    payload = json.dumps(payload_dict)
    client.mqtt_client.publish(client.topicTVUIBasepath + "actions/showmessage", payload)
    client.mqtt_client.publish(client.topicTVUIBasepath + "actions/toast", payload)
    return True


def send_key(client: HisenseTvClient, key: str) -> None:
    """Publishes a raw keypress event to the TV."""
    if client.connected and client.mqtt_client:
        client.mqtt_client.publish(client.topicRemoBasepath + "actions/sendkey", key)


def send_command(client: HisenseTvClient, command: str) -> bool:
    """Sends a key command to the TV, automatically resolving known key aliases."""
    if not command:
        return False
    cmd_clean = command.strip().lower()
    if cmd_clean.startswith("app:"):
        app_target = command.split(":", 1)[1].strip()
        return client._launch_app_by_name(app_target)
    if cmd_clean.startswith("source:"):
        src_target = command.split(":", 1)[1].strip()
        return client._change_source_by_name_or_id(src_target)
    if cmd_clean in (
        "input",
        "source",
        "cycle_source",
        "input_cycle",
        "source_cycle",
        "key_input",
        "key_source",
    ):
        return client.cycle_source()
    if cmd_clean in ("input_menu", "source_menu", "key_input_menu", "key_source_menu"):
        client.send_key("KEY_MENU")
        return True

    key_to_send = resolve_command_key(command)
    client.send_key(key_to_send)
    return True


def cycle_source(client: HisenseTvClient) -> bool:
    """Cycles to the next available input source."""
    next_source = get_next_cycled_source(selectable_sources(client), client.current_source)
    if not next_source:
        raise ValueError("No discovered input sources are available")

    sid, sname = next_source
    client.change_source(sid, sname)
    return True


def launch_app_by_name(client: HisenseTvClient, name_or_id: str) -> bool:
    """Launches an app by name or app ID from cached applist."""
    matched = match_app(client.apps, name_or_id)
    if matched:
        client.launch_app(matched["appId"], matched["name"], matched["url"])
        return True

    target_clean = name_or_id.strip().lower()
    if target_clean in ("netflix", "app_netflix"):
        client.send_key("KEY_NETFLIX")
        return True
    if target_clean in ("youtube", "app_youtube"):
        client.send_key("KEY_YOUTUBE")
        return True
    if target_clean in ("prime", "prime video", "app_prime"):
        client.send_key("KEY_PRIME")
        return True

    return False


def change_source_by_name_or_id(client: HisenseTvClient, target: str) -> bool:
    """Switches to source by name (e.g. HDMI1, TV) or numeric sourceid."""
    sid, sname = resolve_source(client.sources, target)
    client.change_source(sid or target.strip(), sname)
    return True


def set_volume(client: HisenseTvClient, volume: int) -> None:
    """Sets the absolute volume on the TV (0–100)."""
    if client.connected and client.mqtt_client:
        client.mqtt_client.publish(client.topicTVPSBasepath + "actions/changevolume", str(volume))


def change_source(client: HisenseTvClient, source_id: str, source_name: str | None = None) -> None:
    """Switches the active input source on the TV."""
    if not client.connected or not client.mqtt_client:
        raise ConnectionError("MQTT is not connected; source command was not sent")

    options = policy(client)
    if options.source_switch_strategy == "disabled":
        raise ValueError("Source switching is disabled by the compatibility profile")
    if options.source_switch_strategy == "remote_keys":
        raise ValueError("No remote-key source sequences validated for this firmware")
    if client.state not in ("on", "screensaver") or client._pending_power:
        raise ValueError("TV power/readiness is not confirmed")
    # Resolve only against actual TV data, preserving zero-valued IDs.
    target = str(source_id).strip().lower()
    matches = [
        src
        for src in selectable_sources(client)
        if target in {str(src.get(k, "")).strip().lower() for k in ("sourceid", "sourcename", "displayname")}
    ]
    if len(matches) != 1 or matches[0].get("sourceid") is None:
        raise ValueError("Unknown, hidden, or ambiguous source ID")
    src = matches[0]
    sid = str(src["sourceid"])
    sname = str(src.get("sourcename") or src.get("displayname") or "")
    with client._action_lock:
        if client._pending_source:
            raise ValueError("A source change is awaiting confirmation")
        pending = begin_transition(
            client, "source", {"sourceid": sid, "sourcename": sname}, client.source_confirmation_timeout
        )
        payload = {"sourceid": sid}
        if options.source_switch_strategy in ("mqtt_id_name", "upstream_default") and sname:
            payload["sourcename"] = sname
        try:
            result = client.mqtt_client.publish(client.topicTVUIBasepath + "actions/changesource", json.dumps(payload))
            if getattr(result, "rc", 0) != 0:
                pending["outcome"] = "publish_failed"
                raise ConnectionError("Source publish failed; command will not be retried")
        except Exception:
            pending["outcome"] = "publish_failed_or_ambiguous"
            raise


def launch_app(client: HisenseTvClient, app_id: str, app_name: str, url: str) -> None:
    """Launches an installed Smart TV application."""
    if client.connected and client.mqtt_client:
        payload = json.dumps(
            {
                "appId": app_id,
                "name": app_name,
                "url": url,
                "urlType": 37,
                "appName": app_name,
                "appUrl": url,
            }
        )
        client.mqtt_client.publish(client.topicTVUIBasepath + "actions/launchapp", payload)


def send_text_input(client: HisenseTvClient, text: str, action: str = "insert") -> None:
    """Sends virtual keyboard string input to active on-screen input/search field."""
    if client.connected and client.mqtt_client:
        payload = json.dumps({"text": text, "action": action})
        client.mqtt_client.publish(client.topicTVPSBasepath + "actions/txtinputdata", payload)
        client.mqtt_client.publish(client.topicTVPSBasepath + "actions/bwsinputdata", payload)


def turn_on_tv(
    client: HisenseTvClient,
    mac_targets: list[str] | None = None,
) -> None:
    """Powers on or wakes the TV safely and idempotently."""
    with client._action_lock:
        if client.is_on or client._pending_power:
            return
        pending = begin_transition(client, "power", "on", client.power_confirmation_timeout)
        targets = mac_targets or ([client.mac] if client.mac else [])
        if targets:
            if not client.send_wake_on_lan(targets, ip=client.ip):
                pending["outcome"] = "wol_failed"
        elif policy(client).power_on_strategy == "wol_only":
            client._pending_power = None
            raise ValueError("Configure a MAC address for Wake-on-LAN")
        if policy(client).power_on_strategy == "upstream_default" and client.connected and client.state == "off":
            client.send_key("KEY_POWER")
        # MQTT reconnects through its existing background loop; no power toggle
        # is queued for a delayed connect and no optimistic state is assigned.


def turn_off_tv(client: HisenseTvClient) -> None:
    """One power toggle only when a live observation confirms ON."""
    with client._action_lock:
        if (
            not client.connected
            or not client.mqtt_client
            or client.state not in ("on", "screensaver")
            or not client._power_state_live
            or client._pending_power
        ):
            return
        begin_transition(client, "power", "off", client.power_confirmation_timeout)
        try:
            result = client.mqtt_client.publish(client.topicRemoBasepath + "actions/sendkey", "KEY_POWER")
            if getattr(result, "rc", 0) != 0:
                raise ConnectionError("Power publish failed; command will not be retried")
        except Exception:
            client.last_command_outcome["outcome"] = "publish_failed_or_ambiguous"
            raise


class TvActionsMixin:
    """Mixin providing TV command execution, settings, and navigation actions."""

    def query_initial_state(self) -> None:
        """Queries initial state, volume, source list, app list, and settings from TV."""
        query_initial_state(self)  # type: ignore[arg-type]

    def turn_on(self, mac_targets: list[str] | None = None) -> None:
        """Powers on or wakes the TV safely and idempotently."""
        turn_on_tv(self, mac_targets=mac_targets)  # type: ignore[arg-type]

    def turn_off(self) -> None:
        """Powers off the TV safely."""
        turn_off_tv(self)  # type: ignore[arg-type]

    def show_message(self, message: str, title: str | None = None, duration: int = 5) -> bool:
        """Displays an on-screen toast popup notification on the TV."""
        return show_message(self, message=message, title=title, duration=duration)  # type: ignore[arg-type]

    def send_key(self, key: str) -> None:
        """Publishes a raw keypress event to the TV."""
        send_key(self, key=key)  # type: ignore[arg-type]

    def send_command(self, command: str) -> bool:
        """Sends a key command to the TV, automatically resolving known key aliases."""
        return send_command(self, command=command)  # type: ignore[arg-type]

    def cycle_source(self) -> bool:
        """Cycles to the next available input source."""
        return cycle_source(self)  # type: ignore[arg-type]

    def _launch_app_by_name(self, name_or_id: str) -> bool:
        """Launches an app by name or app ID from cached applist."""
        return launch_app_by_name(self, name_or_id=name_or_id)  # type: ignore[arg-type]

    def _change_source_by_name_or_id(self, target: str) -> bool:
        """Switches to source by name (e.g. HDMI1, TV) or numeric sourceid."""
        return change_source_by_name_or_id(self, target=target)  # type: ignore[arg-type]

    def set_volume(self, volume: int) -> None:
        """Sets the absolute volume on the TV (0–100)."""
        set_volume(self, volume=volume)  # type: ignore[arg-type]

    def change_source(self, source_id: str, source_name: str | None = None) -> None:
        """Switches the active input source on the TV."""
        change_source(self, source_id=source_id, source_name=source_name)  # type: ignore[arg-type]

    def launch_app(self, app_id: str, app_name: str, url: str) -> None:
        """Launches an installed Smart TV application."""
        launch_app(self, app_id=app_id, app_name=app_name, url=url)  # type: ignore[arg-type]

    def get_picture_settings(self) -> None:
        """Requests current picture settings menu information from the TV."""
        get_picture_settings(self)  # type: ignore[arg-type]

    def set_picture_setting(self, menu_id: int, menu_value: str | int | float) -> None:
        """Changes a specific picture setting value."""
        set_picture_setting(self, menu_id=menu_id, menu_value=menu_value)  # type: ignore[arg-type]

    def set_picture_mode(self, mode: str) -> None:
        """Sets the TV picture mode preset."""
        set_picture_mode(self, mode=mode)  # type: ignore[arg-type]

    def set_backlight(self, level: int) -> None:
        """Sets the TV backlight level (0–100)."""
        set_backlight(self, level=level)  # type: ignore[arg-type]

    def set_brightness(self, level: int) -> None:
        """Sets the TV brightness level (0–100)."""
        set_brightness(self, level=level)  # type: ignore[arg-type]

    def set_contrast(self, level: int) -> None:
        """Sets the TV contrast level (0–100)."""
        set_contrast(self, level=level)  # type: ignore[arg-type]

    def get_sound_settings(self) -> None:
        """Requests current sound settings menu information from the TV."""
        get_sound_settings(self)  # type: ignore[arg-type]

    def set_sound_setting(self, menu_id: int, menu_value: str | int | float) -> None:
        """Changes a specific sound setting value."""
        set_sound_setting(self, menu_id=menu_id, menu_value=menu_value)  # type: ignore[arg-type]

    def set_sound_mode(self, mode: str) -> None:
        """Sets the TV sound mode preset."""
        set_sound_mode(self, mode=mode)  # type: ignore[arg-type]

    def send_text_input(self, text: str, action: str = "insert") -> None:
        """Sends virtual keyboard string input to active on-screen input/search field."""
        send_text_input(self, text=text, action=action)  # type: ignore[arg-type]
