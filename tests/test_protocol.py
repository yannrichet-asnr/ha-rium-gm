import asyncio
import os
import pty
import struct

import pytest

from custom_components.rium_gm.protocol import (
    RiumStreamParser, cps_to_usv_h, parse_v1, parse_v2,
)
from custom_components.rium_gm.reader import RiumAggregator, RiumSerialReader


def v1(dev=123456, hits=3, delay=20, temp=215):
    return b"\xc1\x00" + struct.pack(">IHHh", dev, hits, delay, temp)


V2 = b"R2,00AB12,1,5,231,412,0,0000000"  # 31 octets + séparateur


def test_v1_decode():
    f = parse_v1(v1())
    assert (f.device_id, f.hits, f.period, f.temperature) == ("123456", 3, 2.0, 21.5)


def test_v1_negative_temp():
    assert parse_v1(v1(temp=-55)).temperature == -5.5


def test_v1_rejects_bad_header():
    assert parse_v1(b"\xc2" + v1()[1:]) is None


def test_v2_decode():
    f = parse_v2(V2)
    assert (f.device_id, f.hits, f.temperature, f.battery_voltage) == ("00AB12", 5, 23.1, 4.12)


def test_stream_v1_split_and_garbage():
    p = RiumStreamParser()
    data = b"\x00\xff" + v1(hits=1) + v1(hits=2) + v1(hits=4)
    out = []
    for i in range(0, len(data), 5):  # découpage arbitraire
        out += p.feed(data[i:i + 5])
    assert [f.hits for f in out] == [1, 2, 4]


def test_stream_v2_lines():
    p = RiumStreamParser()
    out = p.feed(V2 + b"\r\n" + V2[:10]) + p.feed(V2[10:] + b"\n")
    assert [f.hits for f in out] == [5, 5]


def test_stream_v2_fixed_blocks():
    p = RiumStreamParser()
    block = V2 + b"\x00"
    assert len(block) == 32
    assert [f.hits for f in p.feed(block * 2)] == [5, 5]


def test_dose_formula():
    assert cps_to_usv_h(0) == 0.0
    # 18 cpm -> (3.751e-8*14² + 0.00965*14)*0.85
    assert cps_to_usv_h(0.3) == pytest.approx((3.751e-8 * 196 + 0.00965 * 14) * 0.85)


def test_aggregator_window():
    t = [0.0]
    agg = RiumAggregator(window=10, clock=lambda: t[0])
    agg.add(parse_v1(v1(hits=99)))  # première trame ignorée pour le taux
    for _ in range(10):
        t[0] += 2
        agg.add(parse_v1(v1(hits=1)))
    s = agg.state
    assert s.total_hits == 109
    assert s.window_s == 10
    assert s.cps == pytest.approx(0.5)  # trames de ]10, 20] : 5 x 1 coup sur 10 s


def test_aggregator_burst():
    t = [0.0]
    agg = RiumAggregator(window=60, clock=lambda: t[0])
    agg.add(parse_v1(v1(hits=0)))
    t[0] = 0.01
    for _ in range(10):  # 10 trames reçues quasi simultanément
        agg.add(parse_v1(v1(hits=2)))
    assert agg.state.cps == pytest.approx(1.0)  # 20 coups / (10 x 2 s)
    

@pytest.mark.asyncio
async def test_reader_over_pty():
    master, slave = pty.openpty()
    agg = RiumAggregator(window=60)
    got = asyncio.Event()
    reader = RiumSerialReader(os.ttyname(slave), agg, lambda: agg.state.total_hits >= 7 and got.set())
    reader.start()
    await asyncio.sleep(0.3)
    for h in (1, 2, 4):
        os.write(master, v1(hits=h))
        await asyncio.sleep(0.05)
    await asyncio.wait_for(got.wait(), 5)
    assert agg.state.connected and agg.state.device_id == "123456"
    await reader.stop()
