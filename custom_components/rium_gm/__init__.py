"""Intégration Home Assistant pour le détecteur RiumGM connecté en USB."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_PORT, CONF_SCAN_INTERVAL, CONF_WINDOW, DEFAULT_SCAN_INTERVAL, DEFAULT_WINDOW
from .coordinator import RiumCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    opts = {**entry.data, **entry.options}
    coordinator = RiumCoordinator(
        hass,
        entry.data[CONF_PORT],
        opts.get(CONF_WINDOW, DEFAULT_WINDOW),
        opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    coordinator.reader.start()
    await coordinator.async_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        if (coordinator := getattr(entry, "runtime_data", None)) is not None:
            await coordinator.reader.stop()
    return ok


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
