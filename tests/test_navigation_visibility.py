"""Navigation stays callable without filling the automatic dashboard."""

import sys
from types import SimpleNamespace
import unittest

from test_lifecycle import ModuleTests, PACKAGE


class FakeEntity:
    _attr_entity_registry_visible_default = True

    def __init__(self, client, entry):
        self._client = client
        self._entry_id = entry.entry_id
        self._model = "50U7QF"

    @property
    def available(self):
        return True


class Registry:
    def __init__(self):
        self.entries = []
        self.changes = []

    def async_update_entity(self, entity_id, **kwargs):
        row = next(item for item in self.entries if item.entity_id == entity_id)
        self.changes.append(entity_id)
        for key, value in kwargs.items():
            setattr(row, key, value)


class NavigationVisibilityTests(ModuleTests, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.registry = Registry()
        self.updated_entries = []
        self.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=self.update_entry))
        helpers = sys.modules["homeassistant.helpers"]
        helpers.entity_registry = SimpleNamespace(
            async_get=lambda hass: self.registry,
            async_entries_for_config_entry=lambda registry, entry_id: [item for item in registry.entries if item.config_entry_id == entry_id],
            RegistryEntryHider=SimpleNamespace(INTEGRATION="integration", USER="user"),
        )
        sys.modules.update({
            "homeassistant.components.button": SimpleNamespace(ButtonEntity=type("ButtonEntity", (), {})),
            "homeassistant.const": SimpleNamespace(EntityCategory=SimpleNamespace(DIAGNOSTIC="diagnostic")),
            "homeassistant.exceptions": SimpleNamespace(HomeAssistantError=RuntimeError),
            "homeassistant.helpers.entity_platform": SimpleNamespace(AddEntitiesCallback=object),
            f"{PACKAGE}.entity": SimpleNamespace(HisenseVidaaEntity=FakeEntity),
        })
        sys.modules[f"{PACKAGE}.discovery"].get_tv_timestamp = lambda *args: None
        self.button = self.load("button")

    def update_entry(self, entry, **kwargs):
        self.updated_entries.append(kwargs)
        for key, value in kwargs.items():
            setattr(entry, key, value)

    def row(self, suffix, *, entity_id=None, entry_id="tv", hidden_by=None):
        item = SimpleNamespace(
            domain="button",
            config_entry_id=entry_id,
            unique_id=f"{entry_id}_{suffix}",
            entity_id=entity_id or f"button.{suffix}",
            hidden_by=hidden_by,
        )
        self.registry.entries.append(item)
        return item

    def test_navigation_is_hidden_but_keeps_its_entity_id(self):
        client = SimpleNamespace(connected=True, is_on=True)
        for command in self.button.NAVIGATION_COMMANDS:
            with self.subTest(command=command):
                button = self.button.HisenseVidaaNavigationButton(client, SimpleNamespace(entry_id="tv"), command)
                self.assertFalse(button._attr_entity_registry_visible_default)
                self.assertEqual(button._attr_unique_id, f"tv_remote_{command}")
                self.assertTrue(button.available)

    async def test_hidden_navigation_can_still_send_commands(self):
        commands = []
        client = SimpleNamespace(connected=True, is_on=True, send_key=commands.append)
        button = self.button.HisenseVidaaNavigationButton(client, SimpleNamespace(entry_id="tv"), "left")

        async def execute(fn, *args):
            return fn(*args)

        button.hass = SimpleNamespace(async_add_executor_job=execute)
        await button.async_press()
        self.assertEqual(commands, ["KEY_LEFT"])

    def test_screen_buttons_do_not_inherit_hidden_navigation_default(self):
        for off in (False, True):
            button = self.button.HisenseU7QFScreenButton(SimpleNamespace(), SimpleNamespace(entry_id="tv"), off)
            self.assertTrue(button._attr_entity_registry_visible_default)

    async def test_migration_hides_existing_renamed_navigation_once(self):
        migration = self.load("migration")
        nav = self.row("remote_left", entity_id="button.renamed_left")
        screen = self.row("screen_off")
        diagnostic = self.row("force_reconnect")
        user_hidden = self.row("remote_ok", hidden_by="user")
        other_tv = self.row("remote_right", entry_id="other")
        entry = SimpleNamespace(entry_id="tv", version=1, minor_version=1)
        self.assertTrue(await migration.async_migrate_entry(self.hass, entry))
        self.assertEqual(nav.hidden_by, "integration")
        self.assertEqual(self.registry.changes, ["button.renamed_left"])
        self.assertIsNone(screen.hidden_by)
        self.assertIsNone(diagnostic.hidden_by)
        self.assertEqual(user_hidden.hidden_by, "user")
        self.assertIsNone(other_tv.hidden_by)
        self.assertEqual(entry.minor_version, 2)
        # A later explicit user choice must survive reload/migration checks.
        nav.hidden_by = None
        self.assertTrue(await migration.async_migrate_entry(self.hass, entry))
        self.assertIsNone(nav.hidden_by)
        self.assertEqual(len(self.registry.changes), 1)

    async def test_migration_rejects_newer_major_entry_without_changes(self):
        migration = self.load("migration")
        self.row("remote_left")
        entry = SimpleNamespace(entry_id="tv", version=2, minor_version=1)
        self.assertFalse(await migration.async_migrate_entry(self.hass, entry))
        self.assertEqual(self.registry.changes, [])
        self.assertEqual(self.updated_entries, [])
