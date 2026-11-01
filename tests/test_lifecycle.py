"""Exercise real lifecycle modules without HA or a network connection."""

import asyncio
import importlib
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "hisense_u7qf"
PACKAGE = "lifecycle_test_integration"


def package(name, path):
    module = ModuleType(name)
    module.__path__ = [str(path)]
    return module


class FlowBase:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        pass

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}


class FakeMqtt:
    def __init__(self, owner):
        self.owner = owner
        self.running = False

    def reconnect_delay_set(self, **kwargs):
        pass

    def connect_async(self, *args):
        self.owner.connected = self.owner.connect_success

    def loop_start(self):
        self.running = True

    def subscribe(self, *args):
        pass

    def publish(self, topic, payload):
        if self.owner.challenge and topic.endswith("gettvstate"):
            self.owner._auth_future.set_result("")


class FakeClient:
    instances = []
    connect_success = False
    challenge = False

    def __init__(self, ip, mac=None, **kwargs):
        self.ip = ip
        self.mac = mac
        self.client_id = uuid4().hex
        self.username = self.password = "mock"
        self.connected = False
        self.mqtt_client = None
        self.transports = []
        self.topicMobiBasepath = "mobile/"
        self.topicTVUIBasepath = "tv/"
        self.instances.append(self)

    async def async_start_auth(self):
        pass

    def create_mqtt_client(self, *args):
        mqtt = FakeMqtt(self)
        self.transports.append(mqtt)
        return mqtt

    def disconnect(self):
        self.connected = False
        if self.mqtt_client:
            self.mqtt_client.running = False
        self.mqtt_client = None


class ModuleTests(unittest.TestCase):
    def setUp(self):
        modules = {
            PACKAGE: package(PACKAGE, ROOT),
            f"{PACKAGE}.protocol": package(f"{PACKAGE}.protocol", ROOT / "protocol"),
            f"{PACKAGE}.tv": package(f"{PACKAGE}.tv", ROOT / "tv"),
            "voluptuous": MagicMock(),
            "homeassistant": SimpleNamespace(config_entries=SimpleNamespace(ConfigFlow=FlowBase)),
            "homeassistant.core": SimpleNamespace(HomeAssistant=object, callback=lambda fn: fn),
            "homeassistant.config_entries": SimpleNamespace(ConfigEntry=object),
            "homeassistant.data_entry_flow": SimpleNamespace(AbortFlow=type("AbortFlow", (Exception,), {})),
            "homeassistant.helpers": SimpleNamespace(issue_registry=MagicMock()),
            "homeassistant.helpers.device_registry": SimpleNamespace(format_mac=lambda mac: mac),
            f"{PACKAGE}.crypto": SimpleNamespace(check_certs_exist=lambda *a: True, resolve_certificates=lambda *a: (None, None)),
            f"{PACKAGE}.discovery": SimpleNamespace(get_arp_mac=lambda ip: None),
            f"{PACKAGE}.client": SimpleNamespace(HisenseTvClient=FakeClient),
            f"{PACKAGE}.u7qf_client": SimpleNamespace(U7QFClient=FakeClient),
            f"{PACKAGE}.flow_certs": SimpleNamespace(CertsFlowMixin=type("CertsFlowMixin", (), {"_resolve_ssl_certs": lambda self: True})),
            f"{PACKAGE}.flow_discovery": SimpleNamespace(DiscoveryFlowMixin=type("DiscoveryFlowMixin", (), {})),
            f"{PACKAGE}.options_flow": SimpleNamespace(HisenseVidaaOptionsFlowHandler=object),
            f"{PACKAGE}.protocol.auth": SimpleNamespace(is_token_expired=lambda *a, **kw: False),
        }
        self.patcher = patch.dict(sys.modules, modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def load(self, name):
        return importlib.import_module(f"{PACKAGE}.{name}")


class PairingLifecycleTests(ModuleTests, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeClient.instances = []
        FakeClient.connect_success = False
        FakeClient.challenge = False
        self.entries = []
        self.jobs = []
        loop = asyncio.get_running_loop()

        def executor(fn, *args):
            future = loop.run_in_executor(None, fn, *args)
            self.jobs.append(future)
            return future

        self.hass = SimpleNamespace(
            loop=loop,
            async_add_executor_job=executor,
            config_entries=SimpleNamespace(async_entries=lambda domain: self.entries),
        )
        self.pairing = self.load("protocol.pairing")

        async def yield_once(delay):
            await asyncio.sleep(0)

        self.pairing.asyncio = SimpleNamespace(get_running_loop=asyncio.get_running_loop, sleep=yield_once)
        self.flow_module = self.load("config_flow")

    async def asyncTearDown(self):
        if self.jobs:
            await asyncio.gather(*self.jobs)

    def flow(self, entry=None):
        flow = self.flow_module.HisenseVidaaConfigFlow()
        flow.hass = self.hass
        flow.ip_address = "192.0.2.1"
        flow.mac_address = "00:00:00:00:00:01"
        flow._reauth_entry = entry
        flow.auth_profile = "legacy"
        return flow

    async def test_failed_setup_releases_transport_before_retry(self):
        flow = self.flow()
        for _ in range(2):
            with self.assertRaises(ValueError):
                await flow._async_init_client_and_auth()
            self.assertFalse(any(t.running for c in FakeClient.instances for t in c.transports))

    async def test_failed_reauth_keeps_loaded_runtime_connected(self):
        original = FakeClient("192.0.2.1", "00:00:00:00:00:01")
        original.connected = True
        original.mqtt_client = original.create_mqtt_client()
        original.mqtt_client.loop_start()
        transport = original.mqtt_client
        entry = SimpleNamespace(entry_id="tv", runtime_data=SimpleNamespace(client=original))
        self.entries.append(entry)
        flow = self.flow(entry)
        with self.assertLogs(PACKAGE, level="WARNING"):
            result = await flow.async_step_reauth_confirm({})
        self.assertEqual(result["errors"]["base"], "cannot_connect")
        flow.async_remove()
        await asyncio.gather(*self.jobs)
        self.assertTrue(original.connected)
        self.assertTrue(transport.running)
        self.assertFalse(any(t.running for c in FakeClient.instances[1:] for t in c.transports))

    async def test_replacing_flow_client_closes_its_previous_session(self):
        flow = self.flow()
        previous = flow.client = FakeClient(flow.ip_address)
        previous.mqtt_client = previous.create_mqtt_client()
        previous.mqtt_client.loop_start()
        transport = previous.mqtt_client
        with self.assertRaises(ValueError):
            await flow._async_init_client_and_auth()
        self.assertFalse(transport.running)

    async def test_offline_probe_closes_its_background_loop(self):
        client = FakeClient("192.0.2.1")
        self.assertFalse(await self.pairing.async_probe_pairing_challenge(client, timeout=0))
        self.assertFalse(any(t.running for t in client.transports))

    async def test_connected_probe_keeps_session_for_pin_submission(self):
        FakeClient.connect_success = True
        FakeClient.challenge = True
        client = FakeClient("192.0.2.1")
        self.assertTrue(await self.pairing.async_probe_pairing_challenge(client, timeout=1))
        self.assertTrue(client.mqtt_client.running)
        client.disconnect()

    async def test_cancelled_probe_closes_even_a_connected_session(self):
        FakeClient.connect_success = True
        client = FakeClient("192.0.2.1")

        async def cancel_after_connection(delay):
            if client.connected:
                raise asyncio.CancelledError

        self.pairing.asyncio.sleep = cancel_after_connection
        with self.assertRaises(asyncio.CancelledError):
            await self.pairing.async_probe_pairing_challenge(client)
        self.assertFalse(any(t.running for t in client.transports))


class FakeTimer:
    def __init__(self, interval, function, args=None, kwargs=None):
        self.function, self.args, self.kwargs = function, args or (), kwargs or {}
        self.cancelled = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.function(*self.args, **self.kwargs)


class TokenWatchTests(ModuleTests):
    def setUp(self):
        super().setUp()
        self.module = self.load("protocol.auth_lifecycle")
        self.timers = []

        def timer(*args, **kwargs):
            item = FakeTimer(*args, **kwargs)
            self.timers.append(item)
            return item

        self.module.threading = SimpleNamespace(Lock=threading.Lock, Timer=timer)
        self.client = SimpleNamespace(ip="mock", _maybe_refresh_while_awake=lambda: None)
        self.manager = self.module.TokenLifecycleManager(self.client)

    def test_stop_during_tick_prevents_reschedule(self):
        self.client._maybe_refresh_while_awake = self.manager.stop_token_watch
        self.manager.start_token_watch()
        self.timers[0].fire()
        self.assertEqual(len(self.timers), 1)
        self.assertIsNone(self.manager.token_watch)

    def test_tick_from_stopped_generation_cannot_replace_restarted_watch(self):
        self.manager.start_token_watch()
        stale = self.timers[0]
        self.manager.stop_token_watch()
        self.manager.start_token_watch()
        active = self.manager.token_watch
        stale.fire()
        self.assertIs(self.manager.token_watch, active)
        self.assertEqual(len(self.timers), 2)

    def test_live_tick_reschedules_and_explicit_restart_is_allowed(self):
        self.manager.start_token_watch()
        self.timers[0].fire()
        self.assertEqual(len(self.timers), 2)
        self.manager.stop_token_watch()
        self.assertTrue(self.timers[1].cancelled)
        self.manager.start_token_watch()
        self.assertEqual(len(self.timers), 3)


class ActivityTests(ModuleTests):
    def test_unknown_and_standby_are_not_activity(self):
        sys.modules.update({
            "homeassistant.components.binary_sensor": SimpleNamespace(BinarySensorDeviceClass=SimpleNamespace(CONNECTIVITY="connectivity", RUNNING="running"), BinarySensorEntity=type("BinarySensorEntity", (), {})),
            "homeassistant.const": SimpleNamespace(EntityCategory=SimpleNamespace(DIAGNOSTIC="diagnostic")),
            "homeassistant.helpers.entity_platform": SimpleNamespace(AddEntitiesCallback=object),
            f"{PACKAGE}.entity": SimpleNamespace(HisenseVidaaEntity=type("Entity", (), {"__init__": lambda self, client, entry: self.__dict__.update(_client=client, _entry_id=entry.entry_id)})),
        })
        module = self.load("binary_sensor")
        for connected, state, expected in [(True, "unknown", None), (True, "off", False), (True, "on", True), (False, "on", None), (True, "screensaver", True)]:
            with self.subTest(connected=connected, state=state):
                client = SimpleNamespace(connected=connected, state=state, is_on=state in ("on", "screensaver", "fake_sleep_1"))
                sensor = module.HisenseVidaaInUseBinarySensor(client, SimpleNamespace(entry_id="tv"))
                self.assertEqual(sensor.is_on, expected)
