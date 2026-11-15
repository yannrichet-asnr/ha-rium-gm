"""Configuration : découverte USB automatique ou choix manuel du port série."""
from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

import serial.tools.list_ports
import voluptuous as vol
from homeassistant.components import usb
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector, SelectSelectorConfig, TextSelector, TextSelectorConfig, TextSelectorType,
)
from homeassistant.helpers.service_info.usb import UsbServiceInfo
from homeassistant.util import dt as dt_util

from .const import (
    CONF_OPENRADIATION, CONF_OR_API_KEY, CONF_OR_ENABLED, CONF_OR_ENVIRONMENT, CONF_OR_HEIGHT,
    CONF_OR_LATITUDE, CONF_OR_LONGITUDE, CONF_OR_PERIOD, CONF_OR_PRODUCTION, CONF_OR_USER_ID,
    CONF_OR_USER_PWD, CONF_PORT, CONF_SCAN_INTERVAL, CONF_WINDOW, DEFAULT_OR_PERIOD,
    DEFAULT_SCAN_INTERVAL, DEFAULT_WINDOW, DOMAIN, USB_PID, USB_VID, VERSION,
)
from .openradiation import (
    ENVIRONMENTS, MIN_DURATION, OpenRadiationError, PeriodMeasurement, build_payload, submit,
)

MANUAL = "manual"


def _stable_path(dev: str) -> str:
    """Préférer /dev/serial/by-id/... (stable entre redémarrages) à /dev/ttyACMx."""
    try:
        return usb.get_serial_by_id(dev)
    except Exception:  # noqa: BLE001
        return dev


class RiumConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._port: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return RiumOptionsFlow()

    async def async_step_usb(self, discovery_info: UsbServiceInfo) -> ConfigFlowResult:
        port = await self.hass.async_add_executor_job(_stable_path, discovery_info.device)
        await self.async_set_unique_id(discovery_info.serial_number or port)
        self._abort_if_unique_id_configured(updates={CONF_PORT: port})
        self._port = port
        self.context["title_placeholders"] = {"port": port}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Rium GM", data={CONF_PORT: self._port})
        self._set_confirm_only()
        return self.async_show_form(step_id="confirm", description_placeholders={"port": self._port})

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_PORT] == MANUAL:
                return await self.async_step_manual()
            return await self._create(user_input[CONF_PORT])

        ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)
        choices = {
            p.device: f"{p.device} - {p.description}"
            + (" [Rium]" if (p.vid, p.pid) == (USB_VID, USB_PID) else "")
            for p in sorted(ports, key=lambda p: (p.vid, p.pid) != (USB_VID, USB_PID))
        }
        choices[MANUAL] = "Saisie manuelle…"
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required(CONF_PORT): vol.In(choices)}), errors=errors
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if os.path.exists(user_input[CONF_PORT]):
                return await self._create(user_input[CONF_PORT])
            errors[CONF_PORT] = "port_not_found"
        return self.async_show_form(
            step_id="manual", data_schema=vol.Schema({vol.Required(CONF_PORT): str}), errors=errors
        )

    async def _create(self, dev: str) -> ConfigFlowResult:
        port = await self.hass.async_add_executor_job(_stable_path, dev)
        await self.async_set_unique_id(port)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Rium GM", data={CONF_PORT: port})


class RiumOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        o = self.config_entry.options
        orc = o.get(CONF_OPENRADIATION, {})
        if user_input is not None:
            orc = user_input.get(CONF_OPENRADIATION, {})
            if orc.get(CONF_OR_ENABLED):
                if not orc.get(CONF_OR_API_KEY):
                    errors["base"] = "api_key_required"
                elif orc.get(CONF_OR_USER_ID) and not orc.get(CONF_OR_USER_PWD):
                    errors["base"] = "password_required"
                else:
                    errors.update(await self._validate_openradiation(orc))
            if not errors:
                return self.async_create_entry(data=user_input)

        hc = self.hass.config
        or_schema = vol.Schema({
            vol.Required(CONF_OR_ENABLED, default=orc.get(CONF_OR_ENABLED, False)): bool,
            vol.Optional(CONF_OR_API_KEY, description={"suggested_value": orc.get(CONF_OR_API_KEY)}): str,
            vol.Required(CONF_OR_PRODUCTION, default=orc.get(CONF_OR_PRODUCTION, False)): bool,
            vol.Required(CONF_OR_LATITUDE, default=orc.get(CONF_OR_LATITUDE, round(hc.latitude, 3))):
                vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
            vol.Required(CONF_OR_LONGITUDE, default=orc.get(CONF_OR_LONGITUDE, round(hc.longitude, 3))):
                vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
            vol.Required(CONF_OR_ENVIRONMENT, default=orc.get(CONF_OR_ENVIRONMENT, "inside")): SelectSelector(
                SelectSelectorConfig(options=ENVIRONMENTS, translation_key="environment")
            ),
            vol.Required(CONF_OR_HEIGHT, default=orc.get(CONF_OR_HEIGHT, 1)):
                vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
            vol.Required(CONF_OR_PERIOD, default=orc.get(CONF_OR_PERIOD, DEFAULT_OR_PERIOD)):
                vol.All(vol.Coerce(int), vol.Range(min=MIN_DURATION, max=86400)),
            vol.Optional(CONF_OR_USER_ID, description={"suggested_value": orc.get(CONF_OR_USER_ID)}): str,
            vol.Optional(CONF_OR_USER_PWD, description={"suggested_value": orc.get(CONF_OR_USER_PWD)}):
                TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        })
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_WINDOW, default=o.get(CONF_WINDOW, DEFAULT_WINDOW)):
                    vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                vol.Required(CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=600)),
                vol.Required(CONF_OPENRADIATION): section(or_schema, {"collapsed": not orc.get(CONF_OR_ENABLED)}),
            }),
        )

    async def _validate_openradiation(self, orc: dict[str, Any]) -> dict[str, str]:
        """Envoi d'une mesure fictive en reportContext=test (non enregistrée par l'API)."""
        now = dt_util.utcnow()
        m = PeriodMeasurement(start=now - timedelta(minutes=10), end=now, hits=0,
                              temperature=None, device_id=None, version=None)
        payload = build_payload(m, {**orc, CONF_OR_PRODUCTION: False}, VERSION)
        try:
            await submit(async_get_clientsession(self.hass), payload)
        except OpenRadiationError as err:
            if "HTTP 401" in str(err) or "HTTP 403" in str(err):
                return {"base": "invalid_auth"}
            if err.retryable:
                return {"base": "cannot_connect"}
            return {"base": "rejected"}
        return {}
