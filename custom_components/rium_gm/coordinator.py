"""Coordinateur : publication des états à cadence limitée, envoi OpenRadiation optionnel."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import CONF_OR_PERIOD, DEFAULT_OR_PERIOD, DOMAIN, VERSION
from .openradiation import OpenRadiationPublisher
from .protocol import RiumFrame
from .reader import RiumAggregator, RiumSerialReader, RiumState

_LOGGER = logging.getLogger(__name__)


class RiumCoordinator(DataUpdateCoordinator[RiumState]):
    """Le lecteur série alimente l'agrégateur en continu ; le coordinateur
    publie l'état toutes les `scan_interval` secondes (évite d'écrire une
    valeur par seconde dans l'historique)."""

    def __init__(
        self, hass: HomeAssistant, port: str, window: int, scan_interval: int,
        openradiation: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN} {port}", update_interval=timedelta(seconds=scan_interval)
        )
        self.port = port
        self.aggregator = RiumAggregator(window)
        self.reader = RiumSerialReader(port, self.aggregator, self._on_frame)
        self.publisher: OpenRadiationPublisher | None = None
        self._or_period = DEFAULT_OR_PERIOD
        self._unsub: CALLBACK_TYPE | None = None
        if openradiation and openradiation.get("enabled"):
            self.publisher = OpenRadiationPublisher(async_get_clientsession(hass), openradiation, VERSION)
            self._or_period = openradiation.get(CONF_OR_PERIOD, DEFAULT_OR_PERIOD)

    def start(self) -> None:
        self.reader.start()
        if self.publisher:
            self._unsub = async_track_time_interval(
                self.hass, self._publish, timedelta(seconds=self._or_period), name="rium_gm openradiation"
            )

    async def stop(self) -> None:
        if self._unsub:
            self._unsub()
        await self.reader.stop()

    def _on_frame(self, frame: RiumFrame | None) -> None:
        if self.publisher:
            if frame is not None:
                self.publisher.accumulator.add(frame, dt_util.utcnow())
            elif not self.aggregator.state.connected:
                self.publisher.accumulator.reset()  # période incomplète : abandon
        # changement de connexion : publication immédiate
        if self.data is None or self.data.connected != self.aggregator.state.connected:
            self.async_set_updated_data(self.aggregator.state)

    async def _publish(self, now: datetime) -> None:
        assert self.publisher
        await self.publisher.flush(dt_util.utcnow())
        self.async_update_listeners()

    async def _async_update_data(self) -> RiumState:
        return self.aggregator.state
