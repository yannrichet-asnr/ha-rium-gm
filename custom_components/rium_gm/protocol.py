"""Décodage des trames série du RiumGM et conversion en débit de dose.

Deux générations coexistent (source : application OpenRadiation) :

* Rium « v1 » : trame binaire de 12 octets, toutes les ~2 s
      C1 00 | id (u32 BE) | coups (u16 BE) | délai (u16 BE, 1/10 s) | temp (i16 BE, 1/10 °C)
* Rium « v2 » : trame ASCII de 32 octets, champs séparés par des virgules, toutes les ~1 s
      champ[1] = id, champ[3] = coups, champ[4] = temp ×10, champ[5] = tension batterie ×100

Le séparateur entre trames v2 n'est pas documenté : fin de ligne supposée,
avec repli sur des blocs de 32 octets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

V1_HEADER = b"\xc1\x00"
V1_LEN = 12
V2_LEN = 32
_MAX_BUFFER = 512
_V2_RE = re.compile(rb"[0-9A-Za-z.\-]*(,[0-9A-Za-z.\- ]*){5,}")


@dataclass(frozen=True)
class RiumFrame:
    version: int
    device_id: str
    hits: int
    temperature: float | None
    period: float | None = None          # s (v1 : champ délai)
    battery_voltage: float | None = None  # V (v2)


def cps_to_usv_h(cps: float) -> float:
    """Étalonnage « groundLevel » du RiumGM (tube J305) utilisé par OpenRadiation."""
    x = cps * 60 - 4
    return max(0.0, (3.751e-8 * x * x + 0.00965 * x) * 0.85)


def battery_percent(voltage: float) -> float:
    """Formule OpenRadiation (Rium v2)."""
    return max(0.0, min(100.0, 227.27 * voltage - 840.9))


def parse_v1(frame: bytes) -> RiumFrame | None:
    if len(frame) != V1_LEN or frame[:2] != V1_HEADER:
        return None
    temp = int.from_bytes(frame[10:12], "big", signed=True) / 10
    delay = int.from_bytes(frame[8:10], "big") / 10
    if not -40 <= temp <= 85:  # filtre anti-faux-synchronisme
        return None
    return RiumFrame(
        version=1,
        device_id=str(int.from_bytes(frame[2:6], "big")),
        hits=int.from_bytes(frame[6:8], "big"),
        temperature=temp,
        period=delay,
    )


def parse_v2(text: bytes) -> RiumFrame | None:
    fields = text.strip(b"\x00\r\n ").decode("ascii", "replace").split(",")
    if len(fields) < 6:
        return None
    try:
        return RiumFrame(
            version=2,
            device_id=fields[1].strip(),
            hits=int(float(fields[3])),
            temperature=float(fields[4]) / 10,
            battery_voltage=float(fields[5]) / 100,
        )
    except ValueError:
        return None


class RiumStreamParser:
    """Découpe un flux d'octets arbitraire en trames v1/v2."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[RiumFrame]:
        self._buf += data
        out: list[RiumFrame] = []
        while True:
            frame = self._next()
            if frame is None:
                break
            out.append(frame)
        if len(self._buf) > _MAX_BUFFER:
            del self._buf[: len(self._buf) - _MAX_BUFFER]
        return out

    def _next(self) -> RiumFrame | None:
        buf = self._buf
        while buf:
            # v1 : en-tête binaire
            idx = buf.find(V1_HEADER)
            nl = min((i for i in (buf.find(b"\n"), buf.find(b"\r")) if i >= 0), default=-1)
            if idx == 0:
                if len(buf) < V1_LEN:
                    return None
                frame = parse_v1(bytes(buf[:V1_LEN]))
                if frame:
                    del buf[:V1_LEN]
                    return frame
                del buf[:1]
                continue
            # v2 : ligne ASCII terminée
            if nl >= 0 and (idx < 0 or nl < idx):
                line = bytes(buf[:nl])
                del buf[: nl + 1]
                if line.strip() and (frame := parse_v2(line)):
                    return frame
                continue
            # v2 sans séparateur : bloc de 32 octets ASCII
            if idx < 0 and len(buf) >= V2_LEN and _V2_RE.fullmatch(bytes(buf[:V2_LEN]).strip(b"\x00 ")):
                frame = parse_v2(bytes(buf[:V2_LEN]))
                del buf[:V2_LEN]
                if frame:
                    return frame
                continue
            if idx > 0 and (nl < 0 or idx < nl) and not _V2_RE.match(bytes(buf[:idx])):
                del buf[:idx]  # octets parasites avant un en-tête v1
                continue
            return None
        return None
