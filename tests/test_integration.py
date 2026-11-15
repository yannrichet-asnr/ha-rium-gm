"""Bout en bout : port série simulé (pty) -> config flow -> entités HA."""
import asyncio
import os
import pty
import struct
from datetime import timedelta
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.usb import UsbServiceInfo
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.rium_gm.const import DOMAIN


def v1(hits, temp=215):
    return b"\xc1\x00" + struct.pack(">IHHh", 4242, hits, 20, temp)


async def _feed(master, n, hits=3):
    for _ in range(n):
        os.write(master, v1(hits))
        await asyncio.sleep(0.05)


async def test_manual_flow_and_sensors(hass: HomeAssistant):
    master, slave = pty.openpty()
    port = os.ttyname(slave)
    await hass.config.async_set_time_zone("UTC")

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"port": "manual"})
    assert result["step_id"] == "manual"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"port": "/dev/nope"})
    assert result["errors"] == {"port": "port_not_found"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"port": port})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    await asyncio.sleep(0.3)
    await _feed(master, 6)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
    await hass.async_block_till_done()

    states = {s.entity_id: s for s in hass.states.async_all()}
    print({k: (v.state, v.attributes.get("unit_of_measurement")) for k, v in states.items()})
    assert states["binary_sensor.rium_gm_connected"].state == "on"
    assert states["sensor.rium_gm_total_counts"].state == "18"
    assert states["sensor.rium_gm_temperature"].state == "21.5"
    # 6 trames v1 reçues en rafale : 18 coups / max(0,3 s ; 6 x 2 s) = 1,5 cps
    assert float(states["sensor.rium_gm_count_rate"].state) == 1.5
    assert float(states["sensor.rium_gm_dose_rate"].state) > 0
    assert states["sensor.rium_gm_dose_rate"].attributes["unit_of_measurement"] == "\u03bcSv/h"
    assert states["sensor.rium_gm_battery"].state == "unavailable"  # v1 : pas de batterie

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    os.close(master)


async def test_usb_discovery(hass: HomeAssistant):
    info = UsbServiceInfo(device="/dev/ttyACM0", vid="03EB", pid="2404",
                          serial_number="ABC", manufacturer="Icohup", description="Rium")
    with patch("custom_components.rium_gm.config_flow._stable_path", return_value="/dev/serial/by-id/rium"), \
         patch("custom_components.rium_gm.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "usb"}, data=info)
        assert result["step_id"] == "confirm"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"port": "/dev/serial/by-id/rium"}
