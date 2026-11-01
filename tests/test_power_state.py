"""Exercise MQTT -> client -> subscriber power evidence without a live broker."""

import importlib
import json
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "hisense_u7qf"
PACKAGE = "power_test_integration"


def namespace(name, directory):
    module = ModuleType(name)
    module.__path__ = [str(directory)]
    return module


class PowerStateTests(unittest.TestCase):
    def setUp(self):
        mqtt = ModuleType("paho.mqtt.client")
        self.patcher = patch.dict(sys.modules, {
            PACKAGE: namespace(PACKAGE, ROOT),
            f"{PACKAGE}.tv": namespace(f"{PACKAGE}.tv", ROOT / "tv"),
            f"{PACKAGE}.protocol": namespace(f"{PACKAGE}.protocol", ROOT / "protocol"),
            f"{PACKAGE}.protocol.auth": SimpleNamespace(apply_mqtt_tls=lambda **kwargs: None),
            "paho": SimpleNamespace(mqtt=SimpleNamespace(client=mqtt)),
            "paho.mqtt": SimpleNamespace(client=mqtt),
            "paho.mqtt.client": mqtt,
        })
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        state = importlib.import_module(f"{PACKAGE}.tv.state")
        callbacks = importlib.import_module(f"{PACKAGE}.tv.callbacks")
        connection = importlib.import_module(f"{PACKAGE}.protocol.connection")
        self.actions = importlib.import_module(f"{PACKAGE}.tv.actions")
        self.connection = connection
        client_type = type("Client", (state.TvStateMixin, callbacks.CallbackRegistryMixin,
                                     connection.ConnectionManagerMixin), {})
        self.client = client_type()
        self.client._init_runtime_state()
        self.client._init_callbacks()
        self.client._action_lock = threading.RLock()
        self.client._pending_power = self.client._pending_source = None
        self.client._auth_future = self.client._auth_code_future = self.client._token_future = None
        self.client.ip = "192.0.2.1"
        self.client.topicBrcsBasepath = "/remoteapp/mobile/broadcast/"
        self.client.topicMobiBasepath = "/remoteapp/mobile/test/"
        self.client.topicTVUIBasepath = "/remoteapp/tv/ui_service/test/"
        self.client.topicTVPSBasepath = "/remoteapp/tv/platform_service/test/"
        self.client.compatibility = SimpleNamespace(mqtt_trace=False)
        self.client.connected = True
        self.events = []
        self.client.register_state_callback(lambda data: self.events.append(self.client.state))

    def prepare_initial_query(self):
        sent = []
        self.client.mqtt_client = SimpleNamespace(publish=lambda topic, payload: sent.append((topic, payload)))
        self.client.topic_client_id = "hisenseservice"
        self.client.topicTVUIBasepath = "/remoteapp/tv/ui_service/hisenseservice/"
        compatibility = importlib.import_module(f"{PACKAGE}.compatibility")
        self.client.compatibility = compatibility.CompatibilityOptions()
        return sent

    def receive(self, suffix, data, retained=False, broadcast=False):
        base = self.client.topicBrcsBasepath if broadcast else self.client.topicMobiBasepath
        self.client._on_message(None, None, SimpleNamespace(
            topic=base + suffix, payload=json.dumps(data).encode(), retain=retained,
        ))

    def test_info_reply_confirms_power_and_notifies_subscribers(self):
        for value, expected in [(1, "on"), (0, "off"), ("1", "on"), ("0", "off")]:
            with self.subTest(value=value):
                self.receive("platform_service/data/gettvinfo", {"is_power_on": value})
                self.assertEqual(self.client.state, expected)
                self.assertTrue(self.client._power_state_live)
                self.assertEqual(self.events[-1], expected)

    def test_capability_can_supply_explicit_power(self):
        self.receive("ui_service/data/capability", {"is_power_on": 1})
        self.assertEqual(self.client.state, "on")
        self.assertEqual(self.events, ["on"])

    def test_info_without_power_does_not_invent_it(self):
        self.receive("platform_service/data/gettvinfo", {"model_name": "50U7QF"})
        self.assertEqual(self.client.model_name, "50U7QF")
        self.assertEqual(self.client.state, "unknown")
        self.assertFalse(self.client._power_state_live)
        self.assertEqual(self.events, [])

    def test_unverified_sleep_flag_is_only_diagnostic_evidence(self):
        self.receive("platform_service/data/gettvinfo", {"fake_sleep_state": 0})
        self.assertEqual(self.client.state, "unknown")
        self.assertFalse(self.client._power_state_live)

    def test_retained_on_followed_by_source_reply_cannot_confirm_power(self):
        self.receive("ui_service/state", {"statetype": "sourceswitch", "sourcename": "HDMI3"},
                     retained=True, broadcast=True)
        self.receive("ui_service/data/sourcelist", [{"sourceid": "6", "sourcename": "HDMI3"}])
        self.assertEqual(self.client.state, "unknown")
        self.assertFalse(self.client._power_state_live)
        self.assertEqual(self.events, [])

    def test_retained_info_never_replaces_a_live_observation(self):
        self.receive("ui_service/state", {"statetype": "off"}, broadcast=True)
        self.receive("platform_service/data/gettvinfo", {"is_power_on": 1}, retained=True)
        self.assertEqual(self.client.state, "off")
        self.assertEqual(self.events, ["off"])

    def test_malformed_flag_cannot_become_on_by_truthiness(self):
        for value in [1.0, "true", 2, "", None, [], {}]:
            with self.subTest(value=value):
                self.client.state = "unknown"
                self.client._power_state_live = False
                self.receive("ui_service/data/state", {"is_power_on": value})
                self.assertEqual(self.client.state, "unknown")
                self.assertFalse(self.client._power_state_live)

    def test_unrelated_off_event_is_not_power_off(self):
        self.receive("ui_service/state", {"statetype": "audio_off"}, broadcast=True)
        self.assertEqual(self.client.state, "unknown")

    def test_settings_menu_is_an_explicit_awake_event(self):
        self.receive("ui_service/state", {"statetype": "remote_setting"}, broadcast=True)
        self.assertEqual(self.client.state, "on")
        self.assertTrue(self.client._power_state_live)

    def test_disconnect_revokes_power_evidence(self):
        self.receive("ui_service/state", {"statetype": "sourceswitch"}, broadcast=True)
        self.client._on_disconnect(None, None, 1)
        self.assertEqual(self.client.state, "unknown")
        self.assertFalse(self.client._power_state_live)

    def test_startup_requests_real_state_before_accepting_fresh_reply(self):
        sent = self.prepare_initial_query()
        with patch.object(self.actions.time, "sleep"):
            self.actions.query_initial_state(self.client, min_interval=0)
        self.assertIn(("/remoteapp/tv/ui_service/hisenseservice/actions/gettvstate", "0"), sent)
        # Reproduce the observed P0219 sequence: retained -> fresh sourceswitch.
        self.receive("ui_service/state", {"statetype": "sourceswitch"}, retained=True, broadcast=True)
        self.assertEqual(self.client.state, "unknown")
        self.receive("ui_service/state", {"statetype": "sourceswitch"}, broadcast=True)
        self.assertEqual(self.client.state, "on")
        self.assertTrue(self.client._power_state_live)

    def test_state_request_is_sent_only_once_per_connection(self):
        sent = self.prepare_initial_query()
        with patch.object(self.actions.time, "sleep"):
            self.actions.query_initial_state(self.client, min_interval=0)
            self.actions.query_initial_state(self.client, min_interval=0)
        self.assertEqual([item for item in sent if item[0].endswith("/gettvstate")], [
            ("/remoteapp/tv/ui_service/hisenseservice/actions/gettvstate", "0"),
        ])

    def test_reconnect_allows_one_new_state_request(self):
        sent = self.prepare_initial_query()
        self.client.refresh_token = None
        self.client.query_initial_state = lambda: None
        transport = SimpleNamespace(subscribe=lambda *args: None)
        timer = SimpleNamespace(start=lambda: None)
        with patch.object(self.actions.time, "sleep"), patch.object(self.connection.threading, "Timer", return_value=timer):
            self.actions.query_initial_state(self.client, min_interval=0)
            self.client._on_disconnect(None, None, 1)
            self.client._on_connect(transport, None, None, 0)
            self.actions.query_initial_state(self.client, min_interval=0)
        self.assertEqual(len([item for item in sent if item[0].endswith("/gettvstate")]), 2)

    def test_pairing_and_unverified_routes_do_not_send_automatic_state_request(self):
        for route, pairing in [(None, None), ("other", None), ("hisenseservice", object())]:
            with self.subTest(route=route, pairing=bool(pairing)):
                sent = self.prepare_initial_query()
                self.client.topic_client_id = route
                self.client._auth_future = pairing
                with patch.object(self.actions.time, "sleep"):
                    self.actions.query_initial_state(self.client, min_interval=0)
                self.assertFalse(any(item[0].endswith("/gettvstate") for item in sent))

    def test_turn_on_refreshes_unknown_state_after_startup_probe_was_consumed(self):
        sent = self.prepare_initial_query()
        self.client._state_query_sent = True
        self.client.mac = "00:11:22:33:44:55"
        self.client.power_confirmation_timeout = 30
        self.client._transition_timers = []
        self.client.send_wake_on_lan = lambda *args, **kwargs: True
        timer = SimpleNamespace(start=lambda: None)
        with patch.object(self.connection.threading, "Timer", return_value=timer):
            self.actions.turn_on_tv(self.client)
        self.assertEqual([item for item in sent if item[0].endswith("/gettvstate")], [
            ("/remoteapp/tv/ui_service/hisenseservice/actions/gettvstate", "0"),
        ])
        self.assertEqual(self.client.state, "unknown")
        self.assertFalse(self.client._power_state_live)
        self.receive("ui_service/state", {"statetype": "sourceswitch"}, broadcast=True)
        self.assertEqual(self.client.state, "on")
        self.assertIsNone(self.client._pending_power)

    def test_repeated_turn_on_while_pending_can_read_state_without_repeating_wol(self):
        sent = self.prepare_initial_query()
        self.client._state_query_sent = True
        self.client._pending_power = {"requested": "on", "outcome": "pending"}
        # Any access to the WoL method here would be an erroneous second wake.
        self.actions.turn_on_tv(self.client)
        self.assertEqual(sent, [
            ("/remoteapp/tv/ui_service/hisenseservice/actions/gettvstate", "0"),
        ])
        self.assertEqual(self.client.state, "unknown")


if __name__ == "__main__":
    unittest.main()
