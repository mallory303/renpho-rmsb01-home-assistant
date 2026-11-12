"""Serve and register the optional Renpho Lovelace card."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
CARD_FILENAME = "renpho-rmsb01-card.js"


async def async_setup_card(hass: HomeAssistant) -> None:
    """Copy the card to /local and register its versioned resource."""

    def _copy_card() -> str:
        source = Path(__file__).parent / "www" / CARD_FILENAME
        target = Path(hass.config.path("www")) / CARD_FILENAME
        data = source.read_bytes()
        if not target.exists() or target.read_bytes() != data:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return hashlib.md5(data).hexdigest()[:8]

    card_hash = await hass.async_add_executor_job(_copy_card)
    card_url = f"/local/{CARD_FILENAME}?v={card_hash}"
    add_extra_js_url(hass, card_url)

    async def _register_resource() -> None:
        """Register the card for storage-mode dashboards, removing old hashes."""
        lovelace = hass.data.get("lovelace")
        if lovelace is None:
            _LOGGER.debug("Lovelace is not ready; will retry card registration")
            return
        try:
            resources = lovelace.resources
            await resources.async_load()
            for resource in list(resources.async_items()):
                url = resource.get("url", "")
                if CARD_FILENAME in url and not url.startswith(card_url):
                    await resources.async_delete_item(resource["id"])
                    _LOGGER.info("Removed stale Renpho card resource %s", url)
            if not any(
                resource.get("url", "").startswith(card_url)
                for resource in resources.async_items()
            ):
                await resources.async_create_item({"res_type": "module", "url": card_url})
                _LOGGER.info("Registered Renpho card resource %s", card_url)
        except Exception:
            _LOGGER.exception(
                "Could not auto-register the Renpho card; add %s as a module resource",
                card_url,
            )

    if hass.data.get("lovelace") is not None:
        await _register_resource()

    async def _on_started(_event) -> None:
        await _register_resource()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)
