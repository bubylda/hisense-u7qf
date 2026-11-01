"""Media-player control availability without guessing the TV's power state."""

import importlib
from enum import IntFlag, auto
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "hisense_u7qf"
PACKAGE = "media_player_test_integration"


class Features(IntFlag):
    TURN_ON = auto()
    TURN_OFF = auto()
    VOLUME_SET = auto()
    VOLUME_STEP = auto()
    VOLUME_MUTE = auto()
    SELECT_SOURCE = auto()
    PLAY_MEDIA = auto()
    SELECT_SOUND_MODE = auto()
    PLAY = auto()
    PAUSE = auto()
    STOP = auto()
    NEXT_TRACK = auto()
    PREVIOUS_TRACK = auto()


class Entity:
    assumed_state = False

    def schedule_update_ha_state(self):
        pass


class MediaPlayerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        package = ModuleType(PACKAGE)
        package.__path__ = [str(ROOT)]
        tv_package = ModuleType(f"{PACKAGE}.tv")
        tv_package.__path__ = [str(ROOT / "tv")]
        self.patcher = patch.dict(sys.modules, {
            PACKAGE: package,
            f"{PACKAGE}.tv": tv_package,
            f"{PACKAGE}.client": SimpleNamespace(HisenseTvClient=object),
            "homeassistant.components.media_player": SimpleNamespace(
                MediaPlayerDeviceClass=SimpleNamespace(TV="tv"),
                MediaPlayerEntity=type("MediaPlayerEntity", (), {}),
                MediaPlayerEntityFeature=Features,
            ),
            "homeassistant.config_entries": SimpleNamespace(ConfigEntry=object),
            "homeassistant.const": SimpleNamespace(STATE_ON="on", STATE_OFF="off"),
            "homeassistant.core": SimpleNamespace(HomeAssistant=object),
            "homeassistant.exceptions": SimpleNamespace(HomeAssistantError=RuntimeError),
            "homeassistant.helpers.entity": SimpleNamespace(Entity=Entity),
            "homeassistant.helpers.device_registry": SimpleNamespace(CONNECTION_NETWORK_MAC="mac", DeviceInfo=dict),
            "homeassistant.helpers.entity_platform": SimpleNamespace(AddEntitiesCallback=object),
        })
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        state = importlib.import_module(f"{PACKAGE}.tv.state")
        actions = importlib.import_module(f"{PACKAGE}.tv.actions")
        self.client = type("Client", (state.TvStateMixin, actions.TvActionsMixin), {})()
        self.client._init_runtime_state()
        self.client.connected = True
        self.client.current_source = "HDMI3"
        self.client.access_token = "test"
        module = importlib.import_module(f"{PACKAGE}.media_player")
        self.player = module.HisenseVidaaMediaPlayer(self.client, SimpleNamespace(
            entry_id="tv", data={}, title="TV", options={},
        ))
        self.sent = []
        self.client.mqtt_client = SimpleNamespace(publish=lambda topic, payload: self.sent.append((topic, payload)))
        self.client.topicTVPSBasepath = "/tv/platform/"
        self.client.topicTVUIBasepath = "/tv/ui/"
        async def execute(fn, *args):
            return fn(*args)
        self.player.hass = SimpleNamespace(async_add_executor_job=execute, loop=None)

    def test_connected_unknown_power_is_not_assumed_active(self):
        self.assertIsNone(self.player.state)
        self.assertFalse(self.player.assumed_state)
        self.assertTrue(self.player.available)
        self.assertTrue(self.player.supported_features & Features.VOLUME_SET)
        self.assertEqual(self.client.state, "unknown")
        self.assertFalse(self.client.is_on)
        self.assertFalse(self.client._power_state_live)

    def test_disconnect_removes_assumed_controls(self):
        self.client.connected = False
        self.assertFalse(self.player.assumed_state)
        self.assertIsNone(self.player.state)

    def test_known_standby_is_not_assumed_active(self):
        self.client.state = "off"
        self.assertEqual(self.player.state, "off")
        self.assertFalse(self.player.assumed_state)

    def test_known_power_states_use_observed_state(self):
        for state in ("on", "screensaver", "fake_sleep_1"):
            with self.subTest(state=state):
                self.client.state = state
                self.assertEqual(self.player.state, "on")
                self.assertFalse(self.player.assumed_state)

    def test_volume_feedback_does_not_invent_power_state(self):
        self.player._handle_volume_update({"volume_type": "0", "volume_value": "27"})
        self.assertEqual(self.player.volume_level, 0.27)
        self.assertFalse(self.player.assumed_state)
        self.assertEqual(self.client.state, "unknown")
        self.assertFalse(self.client._power_state_live)

    def test_explicit_power_update_restores_normal_media_state(self):
        self.player._handle_state_update({"is_power_on": 1})
        self.assertEqual(self.player.state, "on")
        self.assertFalse(self.player.assumed_state)
        self.player._handle_state_update({"is_power_on": 0})
        self.assertEqual(self.player.state, "off")
        self.assertIsNone(self.player.media_title)

    def test_off_or_invalid_info_reply_does_not_schedule_awake_discovery(self):
        jobs = []
        self.player.hass.loop = SimpleNamespace(call_soon_threadsafe=lambda *args: jobs.append(args))
        for value in (0, "invalid"):
            with self.subTest(value=value):
                self.player._connected_device = "Apple TV"
                self.player._channel_name = "Old channel"
                self.player._channel_num = "1"
                self.player._handle_state_update({"is_power_on": value})
                self.assertEqual(jobs, [])
                self.assertIsNone(self.player._connected_device)
                self.assertIsNone(self.player._channel_name)
                self.assertIsNone(self.player._channel_num)

    def test_repeated_on_info_does_not_repeat_full_discovery_with_empty_app_list(self):
        jobs = []
        self.player.hass.loop = SimpleNamespace(call_soon_threadsafe=lambda *args: jobs.append(args))
        self.player._handle_state_update({"is_power_on": 1})
        self.assertEqual(len(jobs), 1)
        self.player._handle_state_update({"is_power_on": 1})
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
