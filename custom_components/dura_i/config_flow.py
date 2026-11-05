"""Config flow for Dura-i integration."""

from __future__ import annotations

import logging
from typing import Any

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .registers import registers_to_string

_LOGGER = logging.getLogger(__name__)
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("host", default="192.168.1.254", description="Host(s)"): str,
        vol.Required("port", default=502, description="Port"): int,
    }
)


class ModbusHub:
    """Placeholder class to make tests pass.

    TODO Remove this placeholder class and replace with things from your PyPI package.
    """

    def __init__(self, host: str, port: int) -> None:
        """Initialize."""

        self.hosts = host.replace(" ", "").split(sep=",")
        self.port = port

    async def checkHost(self, host, port) -> bool:
        """Test we can read the inverter serial number from the configured host."""
        client = AsyncModbusTcpClient(host=host, port=port)
        try:
            await client.connect()
            if not client.connected:
                _LOGGER.error("Could not connect to Modbus host %s:%s", host, port)
                return False

            response = await client.read_holding_registers(
                address=0x1A10, count=8, device_id=1
            )
            if response.isError():
                _LOGGER.error("No inverter answered on %s:%s: %s", host, port, response)
                return False

            _LOGGER.info(
                "Connected to inverter serial number %s",
                registers_to_string(response.registers),
            )
        except (ModbusException, OSError) as err:
            _LOGGER.error("Checking Modbus host %s:%s failed: %s", host, port, err)
            return False
        finally:
            # Don't leave the adapter holding a connection open.
            client.close()

        return True

    async def authenticate(self) -> bool:
        """Test if we can communicate with the host."""

        for host in self.hosts:
            _LOGGER.info("Scanning for slaves on modbus host %s", host)
            port = self.port
            if ":" in host:
                port = int(host.split(sep=":")[1])
                host = host.split(sep=":")[0]

            if await self.checkHost(host, port) is False:
                return False

        return True


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """

    hub = ModbusHub(data["host"], data["port"])

    if not await hub.authenticate():
        raise CannotConnect

    # Return info that you want to store in the config entry.
    return {"title": "Modbus TCP-RTU on " + data["host"]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dura-i."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        entries = self.hass.config_entries.async_entries(DOMAIN)
        if entries:
            return self.async_abort(reason="already_setup")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: N805
    ) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class OptionsFlowHandler(OptionsFlow):
    """Dura-i Options Flow handler."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        #self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Dura-i Options Flow handler initialiser."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Host and port live in entry.data. Updating everything in one
                # call fires the reload listener once. Options are cleared
                # because nothing uses them (this also drops settings left by
                # older versions).
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=user_input,
                    options={},
                    title="Modbus TCP-RTU on " + user_input["host"],
                )
                return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("host", default=self.config_entry.data["host"]): str,
                    vol.Required("port", default=self.config_entry.data["port"]): int,
                }
            ),
            errors=errors,
        )
