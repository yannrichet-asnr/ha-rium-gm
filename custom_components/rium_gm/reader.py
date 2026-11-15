"""Lecture continue du port série et agrégation des comptages."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import serial_asyncio_fast

from .const import BAUDRATE, RECONNECT_DELAY
from .protocol import RiumFrame, RiumStreamParser, battery_percent, cps_to_usv_h

_LOGGER = logging.getLogger(__name__)

# Période d'intégration d'une trame (OpenRadiation : hitsPeriod 2000 ms / 1000 ms)
NOMINAL_PERIOD = {1: 2.0, 2: 1.0}


@dataclass
class RiumState:
    connected: bool = False
    version: int | None = None
    device_id: str | None = None
    cps: float | None = None
    dose_rate: float | None = None
    temperature: float | None = None
    battery: float | None = None
    total_hits: int = 0
    window_s: float = 0.0


class RiumAggregator:
    """Taux de comptage sur fenêtre glissante, horodatée à la réception."""

    def __init__(self, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.window = window
        self._clock = clock
        self._events: deque[tuple[float, int, float]] = deque()
        self._start: float | None = None
        self.state = RiumState()

    def add(self, frame: RiumFrame) -> None:
        now = self._clock()
        if self._start is None:
            # La première trame couvre une période antérieure non mesurée : l'ignorer
            # pour le taux, mais la compter dans le cumul.
            self._start = now
        else:
            self._events.append((now, frame.hits, NOMINAL_PERIOD[frame.version]))
        s = self.state
        s.version, s.device_id = frame.version, frame.device_id
        s.total_hits += frame.hits
        s.temperature = frame.temperature
        if frame.battery_voltage is not None:
            s.battery = round(battery_percent(frame.battery_voltage))
        self._recompute(now)

    def _recompute(self, now: float) -> None:
        while self._events and self._events[0][0] <= now - self.window:
            self._events.popleft()
        assert self._start is not None
        # Durée de comptage = max(temps écoulé, somme des périodes nominales) :
        # robuste aux trames reçues en rafale (tampon USB, reconnexion).
        span = max(min(self.window, now - self._start), sum(p for *_, p in self._events))
        s = self.state
        s.window_s = span
        if span <= 0:
            return
        cps = sum(h for _, h, _ in self._events) / span
        s.cps = round(cps, 3)
        s.dose_rate = round(cps_to_usv_h(cps), 4)


class RiumSerialReader:
    def __init__(self, port: str, aggregator: RiumAggregator, on_frame: Callable[[RiumFrame | None], None]) -> None:
        self.port = port
        self.agg = aggregator
        self._on_frame = on_frame
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._run(), name=f"rium_gm {self.port}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            writer = None
            try:
                reader, writer = await serial_asyncio_fast.open_serial_connection(
                    url=self.port, baudrate=BAUDRATE
                )
                _LOGGER.info("Rium connecté sur %s", self.port)
                self.agg.state.connected = True
                self._on_frame(None)
                parser = RiumStreamParser()
                while True:
                    data = await reader.read(256)
                    if not data:
                        raise ConnectionError("fin de flux")
                    _LOGGER.debug("brut %s", data.hex())
                    for frame in parser.feed(data):
                        self.agg.add(frame)
                        self._on_frame(frame)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnexion quelle que soit l'erreur
                _LOGGER.warning("Rium %s : %s, nouvelle tentative dans %ss", self.port, err, RECONNECT_DELAY)
            finally:
                if writer is not None:
                    writer.close()
                if self.agg.state.connected:
                    self.agg.state.connected = False
                    self._on_frame(None)
            await asyncio.sleep(RECONNECT_DELAY)
