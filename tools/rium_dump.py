#!/usr/bin/env python3
"""Vérification hors Home Assistant : affiche les octets bruts et les trames décodées.

Usage : pip install pyserial && python3 tools/rium_dump.py /dev/ttyACM0 [--seconds 60]
"""
import argparse
import importlib.util
import pathlib
import sys
import time

import serial

spec = importlib.util.spec_from_file_location(
    "protocol", pathlib.Path(__file__).parents[1] / "custom_components/rium_gm/protocol.py"
)
protocol = importlib.util.module_from_spec(spec)
sys.modules["protocol"] = protocol
spec.loader.exec_module(protocol)

ap = argparse.ArgumentParser()
ap.add_argument("port")
ap.add_argument("--seconds", type=float, default=60)
ap.add_argument("--baud", type=int, default=115200)
a = ap.parse_args()

parser, hits, t0 = protocol.RiumStreamParser(), 0, time.monotonic()
with serial.Serial(a.port, a.baud, timeout=0.5) as ser:
    while (t := time.monotonic() - t0) < a.seconds:
        data = ser.read(256)
        if not data:
            continue
        print(f"{t:7.2f}s raw {data.hex(' ')}")
        for f in parser.feed(data):
            hits += f.hits
            print(f"         {f}")
cps = hits / a.seconds
print(f"\n{hits} coups en {a.seconds:.0f}s -> {cps:.3f} cps -> {protocol.cps_to_usv_h(cps):.4f} µSv/h")
