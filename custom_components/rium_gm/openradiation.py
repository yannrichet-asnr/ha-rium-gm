"""Envoi des mesures vers l'API OpenRadiation (https://github.com/openradiation/openradiation-api).

Agrégation sur une période (défaut 15 min, minimum 10 min comme le script
ASNR OR_RiumGM_fixedbeacon), puis POST sur submit.openradiation.net.
reportContext = "test" (données non enregistrées) tant que le mode
production n'est pas activé.
"""
from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from .protocol import RiumFrame, cps_to_usv_h
from .reader import NOMINAL_PERIOD

_LOGGER = logging.getLogger(__name__)

SUBMIT_URL = "https://submit.openradiation.net/measurements"
CALIBRATION_FUNCTION = "(0.00000003751*(cps*60-4)^2+0.00965*(cps*60-4))*0.85"
MIN_DURATION = 600  # s
MAX_QUEUE = 96      # mesures en attente conservées (24 h à 15 min)
ENVIRONMENTS = ["inside", "city", "countryside", "ontheroad"]
APPARATUS_VERSION = {1: "Rium", 2: "Rium2USB"}  # libellés OpenRadiation
TUBE_TYPE = "J305γβ"


class OpenRadiationError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class PeriodMeasurement:
    start: datetime
    end: datetime
    hits: int
    temperature: float | None
    device_id: str | None
    version: int | None

    @property
    def duration(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def cps(self) -> float:
        return self.hits / self.duration if self.duration > 0 else 0.0


@dataclass
class PeriodAccumulator:
    """Cumul des coups depuis le dernier envoi (remis à zéro sur déconnexion)."""

    hits: int = 0
    nominal: float = 0.0
    first: datetime | None = None
    last: datetime | None = None
    temps: list[float] = field(default_factory=list)
    device_id: str | None = None
    version: int | None = None

    def add(self, frame: RiumFrame, now: datetime) -> None:
        period = NOMINAL_PERIOD[frame.version]
        if self.first is None:
            self.first = now - timedelta(seconds=period)
        self.last = now
        self.hits += frame.hits
        self.nominal += period
        if frame.temperature is not None:
            self.temps.append(frame.temperature)
        self.device_id, self.version = frame.device_id, frame.version

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    def duration(self) -> float:
        if self.first is None or self.last is None:
            return 0.0
        # robuste aux trames reçues en rafale (cf. RiumAggregator)
        return max((self.last - self.first).total_seconds(), self.nominal)

    def pop(self, min_duration: float = MIN_DURATION) -> PeriodMeasurement | None:
        """Renvoie la mesure de la période si elle est assez longue, puis remet à zéro."""
        d = self.duration()
        if d < min_duration or self.last is None:
            return None
        m = PeriodMeasurement(
            start=self.last - timedelta(seconds=d),
            end=self.last,
            hits=self.hits,
            temperature=sum(self.temps) / len(self.temps) if self.temps else None,
            device_id=self.device_id,
            version=self.version,
        )
        self.reset()
        return m


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_payload(m: PeriodMeasurement, cfg: dict[str, Any], version: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "reportUuid": str(uuid.uuid4()),
        "latitude": float(cfg["latitude"]),
        "longitude": float(cfg["longitude"]),
        "value": round(cps_to_usv_h(m.cps), 4),
        "startTime": _iso(m.start),
        "endTime": _iso(m.end),
        "hitsNumber": m.hits,
        "calibrationFunction": CALIBRATION_FUNCTION,
        "apparatusSensorType": "geiger",
        "apparatusTubeType": TUBE_TYPE,
        "manualReporting": False,
        "organisationReporting": f"ha-rium-gm_{version}",
        "reportContext": "routine" if cfg.get("production") else "test",
        "measurementEnvironment": cfg.get("environment", "inside"),
        "measurementHeight": int(cfg.get("height", 1)),
    }
    if m.device_id:
        data["apparatusId"] = f"RIUM_GM_{m.device_id}"
    if m.version in APPARATUS_VERSION:
        data["apparatusVersion"] = APPARATUS_VERSION[m.version]
    if m.temperature is not None:
        data["temperature"] = round(m.temperature)
    if cfg.get("user_id"):
        data["userId"] = cfg["user_id"]
        data["userPwd"] = cfg.get("user_pwd", "")
        data["tags"] = ["home-assistant", "rium-gm"]
    return {"apiKey": cfg["api_key"], "data": data}


async def submit(session: aiohttp.ClientSession, payload: dict[str, Any], url: str = SUBMIT_URL) -> None:
    # La doc annonce application/vnd.api+json mais le serveur (body-parser.json)
    # n'analyse que application/json : sinon HTTP 400 code 100.
    headers = {"Accept": "application/vnd.api+json"}
    try:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status in (200, 201):
                return
            text = (await r.text())[:300]
            raise OpenRadiationError(f"HTTP {r.status}: {text}", retryable=r.status >= 500 or r.status == 429)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise OpenRadiationError(f"réseau : {err}", retryable=True) from err


@dataclass
class PublisherStatus:
    last_success: datetime | None = None
    last_error: str | None = None
    last_report_uuid: str | None = None
    last_value: float | None = None
    pending: int = 0


class OpenRadiationPublisher:
    def __init__(self, session: aiohttp.ClientSession, cfg: dict[str, Any], version: str) -> None:
        self.session = session
        self.cfg = cfg
        self.version = version
        self.accumulator = PeriodAccumulator()
        self.queue: deque[dict[str, Any]] = deque(maxlen=MAX_QUEUE)
        self.status = PublisherStatus()

    async def flush(self, now: datetime) -> None:
        m = self.accumulator.pop()
        if m is not None:
            self.queue.append(build_payload(m, self.cfg, self.version))
        while self.queue:
            payload = self.queue[0]
            try:
                await submit(self.session, payload)
            except OpenRadiationError as err:
                self.status.last_error = str(err)
                _LOGGER.warning("OpenRadiation : %s", err)
                if err.retryable:
                    break  # réessai à la prochaine période
                self.queue.popleft()  # rejet définitif (clé invalide, données refusées)
                continue
            self.queue.popleft()
            d = payload["data"]
            self.status.last_success = now
            self.status.last_report_uuid = d["reportUuid"]
            self.status.last_value = d["value"]
            self.status.last_error = None
            _LOGGER.info("OpenRadiation : mesure %s envoyée (%s µSv/h, %s)", d["reportUuid"], d["value"], d["reportContext"])
        self.status.pending = len(self.queue)
