import json
from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.rium_gm.const import DOMAIN
from custom_components.rium_gm.openradiation import (
    SUBMIT_URL, OpenRadiationPublisher, PeriodAccumulator, PeriodMeasurement, build_payload,
)
from custom_components.rium_gm.protocol import RiumFrame

T0 = datetime(2026, 1, 1, tzinfo=UTC)
CFG = {"api_key": "k" * 32, "latitude": 45.123, "longitude": 5.456, "environment": "inside", "height": 1}


def frame(hits=2, temp=20.0):
    return RiumFrame(version=1, device_id="4242", hits=hits, temperature=temp, period=2.0)


def test_accumulator_min_duration_and_reset():
    acc = PeriodAccumulator()
    for i in range(300):  # 300 trames v1 = 600 s
        acc.add(frame(), T0 + timedelta(seconds=2 * i))
    assert acc.pop(min_duration=601) is None  # pas encore assez long : conservé
    m = acc.pop()
    assert m.hits == 600 and m.duration == pytest.approx(600) and m.cps == pytest.approx(1.0)
    assert m.temperature == 20.0 and m.device_id == "4242"
    assert acc.hits == 0 and acc.pop() is None


def test_accumulator_burst_uses_nominal_period():
    acc = PeriodAccumulator()
    for _ in range(300):
        acc.add(frame(hits=1), T0)  # tout reçu au même instant
    m = acc.pop()
    assert m.duration == pytest.approx(600) and m.cps == pytest.approx(0.5)


def test_payload_matches_api_rules():
    m = PeriodMeasurement(start=T0, end=T0 + timedelta(minutes=15), hits=270,
                          temperature=21.6, device_id="4242", version=2)
    p = build_payload(m, CFG, "0.3.0")
    d = p["data"]
    assert p["apiKey"] == CFG["api_key"]
    assert d["reportContext"] == "test"
    assert d["startTime"] == "2026-01-01T00:00:00Z" and d["endTime"] == "2026-01-01T00:15:00Z"
    assert isinstance(d["temperature"], int) and d["temperature"] == 22  # entier exigé par l'API
    assert isinstance(d["hitsNumber"], int) and isinstance(d["measurementHeight"], int)
    assert d["apparatusSensorType"] == "geiger" and d["apparatusVersion"] == "Rium2USB"
    assert len(d["calibrationFunction"]) <= 100 and len(d["reportUuid"]) == 36
    assert d["value"] == pytest.approx(0.1148, abs=1e-4)
    assert "userId" not in d and "tags" not in d
    p = build_payload(m, {**CFG, "production": True, "user_id": "u", "user_pwd": "p"}, "0.3.0")
    assert p["data"]["reportContext"] == "routine" and p["data"]["userPwd"] == "p"


async def test_publisher_queue_and_retry(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    pub = OpenRadiationPublisher(async_get_clientsession(hass), CFG, "0.3.0")
    for i in range(300):
        pub.accumulator.add(frame(), T0 + timedelta(seconds=2 * i))

    aioclient_mock.post(SUBMIT_URL, status=503)
    await pub.flush(T0)
    assert pub.status.pending == 1 and "503" in pub.status.last_error

    aioclient_mock.clear_requests()
    aioclient_mock.post(SUBMIT_URL, status=201, json={})
    await pub.flush(T0)
    assert pub.status.pending == 0 and pub.status.last_success == T0
    method, url, body, headers = aioclient_mock.mock_calls[-1]
    assert body["data"]["hitsNumber"] == 600 and body["apiKey"] == CFG["api_key"]


async def test_publisher_drops_rejected(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    pub = OpenRadiationPublisher(async_get_clientsession(hass), CFG, "0.3.0")
    for i in range(300):
        pub.accumulator.add(frame(), T0 + timedelta(seconds=2 * i))
    aioclient_mock.post(SUBMIT_URL, status=400, json={"error": {"code": "102"}})
    await pub.flush(T0)
    assert pub.status.pending == 0 and pub.status.last_success is None and "400" in pub.status.last_error


def _entry(hass):
    e = MockConfigEntry(domain=DOMAIN, data={"port": "/dev/null-rium"}, unique_id="/dev/null-rium")
    e.add_to_hass(hass)
    return e


async def _options(hass, entry, orc):
    with __import__("unittest.mock").mock.patch("custom_components.rium_gm.async_setup_entry", return_value=True):
        r = await hass.config_entries.options.async_init(entry.entry_id)
        assert r["type"] is FlowResultType.FORM
        return await hass.config_entries.options.async_configure(
            r["flow_id"], {"window": 120, "scan_interval": 10, "openradiation": orc}
        )


ORC = {"enabled": True, "api_key": "k" * 32, "production": False, "latitude": 45.1, "longitude": 5.4,
       "environment": "city", "height": 1, "period": 900}


async def test_options_validation_ok(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    entry = _entry(hass)
    aioclient_mock.post(SUBMIT_URL, status=201, json={})
    r = await _options(hass, entry, ORC)
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["openradiation"]["api_key"] == "k" * 32
    body = aioclient_mock.mock_calls[-1][2]
    assert body["data"]["reportContext"] == "test"  # validation toujours en mode test


async def test_options_validation_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    entry = _entry(hass)
    r = await _options(hass, entry, {**ORC, "api_key": ""})
    assert r["errors"] == {"base": "api_key_required"}
    aioclient_mock.post(SUBMIT_URL, status=401, json={})
    r = await _options(hass, entry, ORC)
    assert r["errors"] == {"base": "invalid_auth"}
    r = await _options(hass, entry, {**ORC, "enabled": False, "api_key": ""})
    assert r["type"] is FlowResultType.CREATE_ENTRY
