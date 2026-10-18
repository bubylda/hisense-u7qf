"""Regression tests using stdlib only; HA boundaries are isolated test doubles."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "hisense_u7qf"


def load_module(name, dependencies=None):
    package = ModuleType("remote_test_integration")
    package.__path__ = [str(ROOT)]
    spec = importlib.util.spec_from_file_location(f"{package.__name__}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {package.__name__: package, **(dependencies or {})}):
        spec.loader.exec_module(module)
    return module


layout = load_module("remote_layout")


def walk(card):
    yield card
    for child in card.get("cards", []):
        yield from walk(child)


class RemoteLayoutTests(unittest.TestCase):
    def setUp(self):
        self.entities = {
            "remote": "remote.renamed_tv",
            "input": "select.renamed_input",
            "picture_mode": "select.renamed_picture",
            "audio_only_mode": "switch.renamed_audio",
        }

    def test_every_button_has_entity_and_explicit_action(self):
        card = layout.build_remote_card(self.entities)
        for button in (c for c in walk(card) if c["type"] == "button"):
            self.assertEqual(button["entity"], self.entities["remote"])
            self.assertEqual(button["tap_action"]["target"]["entity_id"], button["entity"])
            self.assertEqual(button["hold_action"], {"action": "none"})

    def test_sections_keep_navigation_picture_and_digits_separate(self):
        sections = layout.build_remote_sections(self.entities)
        self.assertEqual(list(sections), ["main", "picture", "keypad"])
        self.assertEqual(sections["picture"]["entities"], [self.entities["picture_mode"]])
        def commands(card):
            return [c["tap_action"]["data"]["command"] for c in walk(card)
                    if c.get("tap_action", {}).get("perform_action") == "remote.send_command"]
        self.assertIn("back", commands(sections["main"]))
        self.assertIn("ok", commands(sections["main"]))
        self.assertNotIn("0", commands(sections["main"]))
        self.assertEqual(commands(sections["keypad"])[:10], [*map(str, range(1, 10)), "0"])
        self.assertCountEqual(commands(sections["main"]) + commands(sections["keypad"]), layout.REMOTE_COMMANDS)

    def test_switch_replaces_both_screen_buttons(self):
        self.entities.update(screen_off="button.screen_off", screen_on="button.screen_on")
        card = layout.build_remote_card(self.entities)
        self.assertFalse(any(c.get("tap_action", {}).get("perform_action") == "button.press" for c in walk(card)))
        self.assertTrue(any(c.get("entities") == [{"entity": "switch.renamed_audio", "name": "Только звук"}]
                            for c in walk(card)))

    def test_without_assumption_explicit_screen_actions_remain(self):
        card = layout.build_remote_card({"remote": "remote.tv", "screen_off": "button.off", "screen_on": "button.on"})
        buttons = [c for c in walk(card) if c.get("tap_action", {}).get("perform_action") == "button.press"]
        self.assertEqual([c["entity"] for c in buttons], ["button.off", "button.on"])

    def test_minimal_registry_omits_optional_cards(self):
        sections = layout.build_remote_sections({"remote": "remote.tv"})
        self.assertEqual(list(sections), ["main", "keypad"])
        self.assertFalse(any(c["type"] in ("entities", "media-control") for c in walk(sections["main"])))


class RemoteServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = SimpleNamespace(connected=False)
        self.entry = SimpleNamespace(entry_id="tv", runtime_data=SimpleNamespace(client=self.client))
        self.entries = [self.entry]
        self.registry_entities = [
            SimpleNamespace(domain="remote", entity_id="remote.renamed", unique_id="tv_remote", disabled_by=None),
            SimpleNamespace(domain="select", entity_id="select.disabled", unique_id="tv_picture_mode", disabled_by="user"),
        ]
        registry = SimpleNamespace(
            async_get=lambda hass: None,
            async_entries_for_config_entry=lambda registry, entry_id: self.registry_entities,
        )
        package = ModuleType("remote_test_integration")
        package.__path__ = [str(ROOT)]
        self.patcher = patch.dict(sys.modules, {
            "remote_test_integration": package,
            "remote_test_integration.const": load_module("const"),
            "remote_test_integration.remote_layout": layout,
            "voluptuous": MagicMock(),
            "homeassistant.core": SimpleNamespace(HomeAssistant=object, ServiceCall=object, SupportsResponse=SimpleNamespace(OPTIONAL=1)),
            "homeassistant.exceptions": SimpleNamespace(ServiceValidationError=RuntimeError),
            "homeassistant.helpers": SimpleNamespace(entity_registry=registry),
        })
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.module = load_module("services")
        handlers = {}
        self.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_loaded_entries=lambda domain: self.entries),
            services=SimpleNamespace(
                has_service=lambda *args: False,
                async_register=lambda domain, name, handler, **kwargs: handlers.update({name: handler}),
            ),
        )
        await self.module.async_setup_services(self.hass)
        self.generate = handlers["get_remote_card"]

    async def test_disconnected_tv_generates_cards_with_registered_ids(self):
        result = await self.generate(SimpleNamespace(data={"entry_id": "tv"}))
        self.assertEqual(result["entity_ids"], {"remote": "remote.renamed"})
        self.assertEqual(list(result["cards"]), ["main", "keypad"])
        self.assertEqual(result["card"]["cards"], list(result["cards"].values()))

    async def test_multiple_tvs_require_explicit_selection(self):
        self.entries.append(SimpleNamespace(entry_id="other", runtime_data=SimpleNamespace(client=SimpleNamespace(connected=False))))
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            await self.generate(SimpleNamespace(data={}))
        result = await self.generate(SimpleNamespace(data={"entry_id": "tv"}))
        self.assertEqual(result["entity_ids"]["remote"], "remote.renamed")

    async def test_missing_remote_has_clear_validation_error(self):
        self.registry_entities.clear()
        with self.assertRaisesRegex(RuntimeError, "Remote entity is not registered"):
            await self.generate(SimpleNamespace(data={"entry_id": "tv"}))


class FakeEntity:
    def __init__(self, client, entry):
        self._client = client
        self._entry_id = entry.entry_id
        self._model = "50U7QF"

    def async_write_ha_state(self):
        pass

    def schedule_update_ha_state(self):
        pass


class ScreenSwitchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        dependencies = {
            "homeassistant.components.switch": SimpleNamespace(SwitchEntity=type("SwitchEntity", (), {})),
            "homeassistant.exceptions": SimpleNamespace(HomeAssistantError=RuntimeError),
            "homeassistant.helpers": SimpleNamespace(entity_registry=MagicMock()),
            "remote_test_integration.const": SimpleNamespace(DOMAIN="hisense_u7qf"),
            "remote_test_integration.entity": SimpleNamespace(HisenseVidaaEntity=FakeEntity),
            "remote_test_integration.model": SimpleNamespace(is_known_model=lambda model: True),
            "remote_test_integration.screen": SimpleNamespace(can_screen_off=lambda client: True, screen_off_error=lambda *args: "blocked"),
        }
        module = load_module("screen_switch", dependencies)
        self.client = SimpleNamespace(connected=True, current_source="HDMI1", is_on=True, model_name="50U7QF",
                                      screen_off=MagicMock(), screen_on=MagicMock())
        self.switch = module.HisenseU7QFAssumedAudioOnlySwitch(self.client, SimpleNamespace(entry_id="tv"))
        async def execute(command):
            command()
        self.switch.hass = SimpleNamespace(async_add_executor_job=execute)

    async def test_successful_commands_enable_toggle_in_both_positions(self):
        self.assertFalse(self.switch.is_on)
        self.assertEqual(self.switch.extra_state_attributes["state_source"], "assumed_screen_on")
        self.assertFalse(self.switch.assumed_state)
        await self.switch.async_turn_on()
        self.assertTrue(self.switch.is_on)
        self.assertFalse(self.switch.assumed_state)
        self.assertEqual(self.switch.extra_state_attributes["state_source"], "assumed_from_commands")
        await self.switch.async_turn_off()
        self.assertFalse(self.switch.is_on)
        self.assertFalse(self.switch.assumed_state)
        self.client.screen_off.assert_called_once()
        self.client.screen_on.assert_called_once()

    async def test_reconnect_discards_assumption(self):
        await self.switch.async_turn_on()
        self.switch._forget_state()
        self.assertFalse(self.switch.is_on)
        self.assertEqual(self.switch.extra_state_attributes["state_source"], "assumed_screen_on")
        self.assertFalse(self.switch.assumed_state)

    async def test_source_change_discards_assumption(self):
        await self.switch.async_turn_on()
        self.client.current_source = "HDMI2"
        self.switch._handle_state()
        self.assertFalse(self.switch.is_on)
        self.assertEqual(self.switch.extra_state_attributes["state_source"], "assumed_screen_on")
        self.assertFalse(self.switch.assumed_state)

    async def test_failed_action_discards_assumption(self):
        await self.switch.async_turn_on()
        self.client.screen_on.side_effect = ValueError("failed")
        with self.assertRaisesRegex(RuntimeError, "failed"):
            await self.switch.async_turn_off()
        self.assertFalse(self.switch.is_on)
        self.assertEqual(self.switch.extra_state_attributes["state_source"], "assumed_screen_on")
        self.assertFalse(self.switch.assumed_state)

    async def test_power_off_discards_assumption(self):
        await self.switch.async_turn_on()
        self.client.is_on = False
        self.switch._handle_state()
        self.assertFalse(self.switch.is_on)
        self.assertEqual(self.switch.extra_state_attributes["state_source"], "assumed_screen_on")
        self.assertFalse(self.switch.assumed_state)

    async def test_disconnected_toggle_is_unavailable_and_sends_no_command(self):
        self.client.connected = False
        self.switch._forget_state()
        self.assertFalse(self.switch.available)
        self.assertFalse(self.switch.is_on)
        self.assertFalse(self.switch.assumed_state)
        with self.assertRaisesRegex(RuntimeError, "connection is not available"):
            await self.switch.async_turn_off()
        self.client.screen_on.assert_not_called()


if __name__ == "__main__":
    unittest.main()
