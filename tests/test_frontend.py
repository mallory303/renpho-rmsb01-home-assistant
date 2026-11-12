"""Tests for Lovelace card serving and HA 2026.11 resource registration."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from tests.helpers import ROOT, load_module


class FakeResources:
    """Current storage collection API: intentionally has no async_create()."""

    def __init__(self):
        self.items = [
            {"id": "stale", "url": "/local/renpho-rmsb01-card.js?v=old"},
            {"id": "other", "url": "/local/other-card.js"},
        ]
        self.loaded = False

    async def async_load(self):
        self.loaded = True

    def async_items(self):
        return self.items

    async def async_delete_item(self, item_id):
        self.items = [item for item in self.items if item["id"] != item_id]

    async def async_create_item(self, data):
        item = {
            "id": "created",
            "url": data["url"],
            "type": data["res_type"],
        }
        self.items.append(item)
        return item


class FakeBus:
    def __init__(self):
        self.listeners = []

    def async_listen_once(self, event, callback):
        self.listeners.append((event, callback))


class FakeHass:
    def __init__(self, config_dir, resources):
        self.config = SimpleNamespace(path=lambda name: str(Path(config_dir) / name))
        self.data = {"lovelace": SimpleNamespace(resources=resources)}
        self.bus = FakeBus()

    async def async_add_executor_job(self, function):
        return function()


def load_frontend():
    """Load frontend.py with only the HA interfaces it uses."""
    root = ModuleType("homeassistant")
    root.__path__ = []
    components = ModuleType("homeassistant.components")
    components.__path__ = []
    frontend_module = ModuleType("homeassistant.components.frontend")
    frontend_module.add_extra_js_url = lambda hass, url: None
    const = ModuleType("homeassistant.const")
    const.EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    components.frontend = frontend_module
    root.components = components
    root.const = const
    root.core = core
    modules = {
        "homeassistant": root,
        "homeassistant.components": components,
        "homeassistant.components.frontend": frontend_module,
        "homeassistant.const": const,
        "homeassistant.core": core,
    }
    with patch.dict(sys.modules, modules):
        return load_module("frontend")


class FrontendTest(unittest.IsolatedAsyncioTestCase):
    async def test_copy_hash_and_current_resource_api_are_idempotent(self):
        frontend = load_frontend()
        resources = FakeResources()
        with tempfile.TemporaryDirectory() as config_dir:
            hass = FakeHass(config_dir, resources)
            await frontend.async_setup_card(hass)
            await frontend.async_setup_card(hass)

            target = Path(config_dir) / "www" / "renpho-rmsb01-card.js"
            source = (
                ROOT
                / "custom_components"
                / "renpho_rmsb01"
                / "www"
                / "renpho-rmsb01-card.js"
            )
            self.assertEqual(target.read_bytes(), source.read_bytes())

        card_resources = [
            item for item in resources.items if "renpho-rmsb01-card.js" in item["url"]
        ]
        self.assertEqual(len(card_resources), 1)
        self.assertEqual(card_resources[0]["id"], "created")
        self.assertEqual(card_resources[0]["type"], "module")
        self.assertRegex(
            card_resources[0]["url"],
            r"^/local/renpho-rmsb01-card\.js\?v=[0-9a-f]{8}$",
        )
        self.assertFalse(any(item["id"] == "stale" for item in resources.items))
        self.assertTrue(any(item["id"] == "other" for item in resources.items))
        self.assertTrue(resources.loaded)


if __name__ == "__main__":
    unittest.main()
