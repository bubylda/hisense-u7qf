"""The read-only hardware capture exports evidence without auth/device identity."""

import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / "scripts" / "capture_power.py"


class PowerCaptureTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("power_capture", PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_capture_keeps_power_fields_but_omits_identity_and_credentials(self):
        event = self.module.message_event(
            "/remoteapp/mobile/hisenseservice/platform_service/data/gettvinfo",
            b'{"is_power_on":1,"fake_sleep_state":0,"deviceid":"private",'
            b'"token":"secret","new_standby_flag":3,"power_info":{"password":"secret"}}',
            False,
        )
        self.assertEqual(event["fields"], {
            "is_power_on": 1, "fake_sleep_state": 0, "new_standby_flag": 3,
            "power_info": "[non-scalar]",
        })
        self.assertNotIn("private", str(event))
        self.assertNotIn("secret", str(event))
        self.assertFalse(event["retained"])

    def test_authentication_and_other_clients_are_not_exported(self):
        for topic in (
            "/remoteapp/mobile/hisenseservice/ui_service/data/authentication",
            "/remoteapp/mobile/other/platform_service/data/gettvinfo",
        ):
            self.assertIsNone(self.module.message_event(topic, b'{"pin":"1234"}', False))

    def test_retained_sample_stays_marked_as_retained(self):
        event = self.module.message_event(
            "/remoteapp/mobile/broadcast/ui_service/state", b'{"statetype":"fake_sleep_0"}', True,
        )
        self.assertTrue(event["retained"])
        self.assertEqual(event["fields"], {"statetype": "fake_sleep_0"})

    def test_initial_reads_only_publish_information_queries(self):
        sent = []
        class Transport:
            def publish(self, topic, payload):
                sent.append((topic, payload))
        self.module.request_information(Transport())
        self.assertEqual(sent, [
            ("/remoteapp/tv/platform_service/hisenseservice/actions/gettvinfo", ""),
            ("/remoteapp/tv/ui_service/hisenseservice/actions/capability", ""),
        ])

    def test_opt_in_state_query_uses_zero_payload(self):
        sent = []
        class Transport:
            def publish(self, topic, payload):
                sent.append((topic, payload))
        self.module.request_information(Transport(), query_state=True)
        self.assertEqual(sent, [
            ("/remoteapp/tv/ui_service/hisenseservice/actions/gettvstate", "0"),
            ("/remoteapp/tv/platform_service/hisenseservice/actions/gettvinfo", ""),
            ("/remoteapp/tv/ui_service/hisenseservice/actions/capability", ""),
        ])

    def test_direct_gettvstate_reply_is_captured(self):
        event = self.module.message_event(
            "/remoteapp/mobile/hisenseservice/ui_service/data/gettvstate",
            b'{"statetype":"sourceswitch","sourceid":"HDMI3"}', False,
        )
        self.assertIsNotNone(event)
        self.assertEqual(event["fields"], {"statetype": "sourceswitch"})


if __name__ == "__main__":
    unittest.main()
