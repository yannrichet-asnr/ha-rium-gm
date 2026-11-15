"""Configuration : découverte USB automatique ou choix manuel du port série."""
from __future__ import annotations

import os
from typing import Any

import serial.tools.list_ports
import voluptuous as vol
from homeassistant.components import usb
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.service_info.usb import UsbServiceInfo

from .const import (
    CONF_PORT, CONF_SCAN_INTERVAL, CONF_WINDOW, DEFAULT_SCAN_INTERVAL, DEFAULT_WINDOW,
    DOMAIN, USB_PID, USB_VID,
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
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_WINDOW, default=o.get(CONF_WINDOW, DEFAULT_WINDOW)):
                    vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                vol.Required(CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=600)),
            }),
        )
