"""Fixed 50U7QF transport; universal protocol code is a temporary internal dependency."""

import json
from uuid import uuid4

from .client import HisenseTvClient
from .compatibility import runtime_options
from .firmware_u4 import model_setting_choices
from .picture_context import picture_context
from .picture_readiness import cancel_picture_refresh, defer_picture
from .protocol.certs import bundled_app_cert_paths
from .remote_keys import SUPPORTED_KEYS
from .screen import init_screen_actions, screen_action


class U7QFClient(HisenseTvClient):
    """Static MQTT credentials, shared app mTLS, independent MQTT session ID."""

    def __init__(self, ip, mac=None, **kwargs):
        # Pairing/token generations and certificate discovery are deliberately
        # excluded from the public integration contract.
        for key in (
            "username",
            "password",
            "access_token",
            "refresh_token",
            "auth_profile",
            "certfile",
            "keyfile",
            "ca_cert",
            "use_ssl",
            "verify_ssl",
            "refresh_in_standby",
        ):
            kwargs.pop(key, None)
        options = runtime_options(kwargs.pop("compatibility_options", None), None)
        cert, key = bundled_app_cert_paths()
        kwargs["client_id"] = kwargs.get("client_id") or f"ha-u7qf-{uuid4().hex[:16]}"
        super().__init__(
            ip,
            mac,
            **kwargs,
            username="hisenseservice",
            password="multimqttservice",
            access_token="multimqttservice",
            auth_profile="legacy",
            certfile=cert,
            keyfile=key,
            use_ssl=True,
            verify_ssl=False,
            refresh_in_standby=False,
            compatibility_options=options,
        )

        self._picture_ready_after = 0.0
        self._picture_refresh_timer = None
        self._u7qf_picture_guard = True
        init_screen_actions(self)

    def _dispatch_connected(self):
        defer_picture(self)
        super()._dispatch_connected()

    def _dispatch_disconnected(self):
        cancel_picture_refresh(self)
        self._picture_ready_after = float("inf")
        super()._dispatch_disconnected()

    def _dispatch_state_update(self, data):
        with self._action_lock:
            before = (picture_context(self)[0], self.state)
            # Invalidate readiness before notifying HA about the new source.
            if isinstance(data, dict) and (
                ("sourcename" in data and data["sourcename"] != self.current_source)
                or ("sourceid" in data and str(data["sourceid"]) != self.current_source_id)
                or data.get("statetype") in ("app", "remote_launcher", "on", "off", "fake_sleep_0", "fake_sleep_1")
            ):
                defer_picture(self)
            super()._dispatch_state_update(data)
            if before != (picture_context(self)[0], self.state):
                self._dispatch("picture", {})

    def disconnect(self):
        cancel_picture_refresh(self)
        super().disconnect()

    def turn_on(self, mac_targets=None):
        if not self._compatibility_options.get("enable_wol", True):
            raise ValueError("Wake-on-LAN is disabled in integration options")
        with self._navigation_lock:
            return super().turn_on(mac_targets)

    def turn_off(self):
        with self._navigation_lock:
            return super().turn_off()

    def change_source(self, source_id, source_name=None):
        with self._navigation_lock:
            return super().change_source(source_id, source_name)

    def set_picture_setting(self, menu_id, menu_value):
        """Keep raw HA services away from calibration and service parameters."""
        if self.picture_settings_version != "U4":
            raise ValueError("The U4 picture API has not been reported by the TV")
        item = self.picture_settings.get(int(menu_id))
        if item is None:
            raise ValueError("Picture field was not reported by the TV")
        business = item.raw_data.get("menu_biz_id")
        value = int(menu_value)
        ordinary = {
            "de.loewe.sl2.i32.video.backlight",
            "de.loewe.sl2.i32.video.brightness",
            "de.loewe.sl2.i32.video.contrast",
        }
        if business in ordinary:
            allowed = range(101)
        elif business == "de.loewe.sl2.i32.video.game.mode.enable":
            source = picture_context(self)[0]
            allowed = (0, 1) if source.upper().startswith("HDMI") or source == "AVS" else ()
        else:
            allowed = model_setting_choices(self, business).values()
        if value not in allowed:
            raise ValueError("This field/value is not an approved U7QF user control")
        return super().set_picture_setting(menu_id, value)

    def launch_app(self, app_id, app_name, url):
        """Use the TV's own app ID, URL and store type, not fabricated aliases."""
        matches = [app for app in self.apps if isinstance(app, dict) and (
            (app_id and str(app.get("appId") or app.get("app_id")) == str(app_id))
            or (not app_id and str(app.get("name") or app.get("appName") or "").lower() == str(app_name).lower())
        )]
        if len(matches) != 1:
            raise ValueError("Only an application reported by this TV can be launched")
        app = matches[0]
        canonical_url = str(app.get("url") or app.get("appUrl") or "")
        if url and str(url) != canonical_url:
            raise ValueError("Custom app URLs/deep links have not been verified on U7QF")
        payload = {
            "appId": str(app.get("appId") or app.get("app_id")),
            "name": str(app.get("name") or app.get("appName")),
            "url": canonical_url,
            "urlType": 37,
            "storeType": app.get("storeType", 0),
        }
        with self._navigation_lock, self._action_lock:
            if self._pending_source or self._pending_power:
                raise ValueError("A source/power transition is pending")
            self._publish_checked(self.topicTVUIBasepath + "actions/launchapp", json.dumps(payload))

    def set_volume(self, volume):
        with self._action_lock:
            self._publish_checked(self.topicTVPSBasepath + "actions/changevolume", str(max(0, min(100, int(volume)))))

    def _publish_checked(self, topic, payload):
        if not self.connected or not self.mqtt_client:
            raise ValueError("TV MQTT connection is not available")
        result = self.mqtt_client.publish(topic, payload)
        if getattr(result, "rc", 0) != 0:
            raise ValueError("TV command publish failed; command was not retried")

    def set_sound_setting(self, menu_id, menu_value):
        raise ValueError("Sound-setting writes are not supported by this U7QF integration")

    def send_text_input(self, text, action="insert"):
        raise ValueError("Text input has not been verified on U7QF")

    def get_device_fingerprint(self, timeout=2.0):
        """Keep identity from the UPnP capability block available to entities."""
        fingerprint = super().get_device_fingerprint(timeout)
        for key, attribute in (("model_name", "model_name"), ("firmware_version", "firmware_version")):
            value = fingerprint.get(key)
            if isinstance(value, str) and value.strip() and value != "Renderer":
                setattr(self, attribute, value.strip())
        return fingerprint

    def screen_off(self):
        return screen_action(self, off=True)

    def screen_on(self):
        return screen_action(self, off=False)

    async def async_start_auth(self):
        """Static credentials are ready; PIN challenge probing remains explicit."""
        self.define_topic_paths()

    def check_and_refresh_token(self, force=False, margin_seconds=0):
        """This firmware uses static credentials and does not renew tokens."""
        return False

    def send_key(self, key):
        """Power commands must pass the observed-state guard, even from services."""
        with self._navigation_lock, self._action_lock:
            if key == "KEY_BACK":
                key = "KEY_BACKS"
            if key not in SUPPORTED_KEYS:
                raise ValueError(f"Key {key} is not present in the U7QF network remote map")
            if key == "KEY_POWER":
                return self.turn_off()
            return self._publish_checked(self.topicRemoBasepath + "actions/sendkey", key)
