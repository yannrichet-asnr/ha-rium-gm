"""Coordinateur : publication des états à cadence limitée."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .reader import RiumAggregator, RiumSerialReader, RiumState

_LOGGER = logging.getLogger(__name__)


class RiumCoordinator(DataUpdateCoordinator[RiumState]):
    """Le lecteur série alimente l'agrégateur en continu ; le coordinateur
    publie l'état toutes les `scan_interval` secondes (évite d'écrire une
    valeur par seconde dans l'historique)."""

    def __init__(self, hass: HomeAssistant, port: str, window: int, scan_interval: int) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN} {port}", update_interval=timedelta(seconds=scan_interval)
        )
        self.port = port
        self.aggregator = RiumAggregator(window)
        self.reader = RiumSerialReader(port, self.aggregator, self._on_frame)

    def _on_frame(self) -> None:
        # changement de connexion : publication immédiate
        if self.data is None or self.data.connected != self.aggregator.state.connected:
            self.async_set_updated_data(self.aggregator.state)

    async def _async_update_data(self) -> RiumState:
        return self.aggregator.state
