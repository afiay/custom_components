# SPDX-License-Identifier: MIT
# custom_components/iotopen/config_flow.py

"""Config flow for IoT Open integration."""

from __future__ import annotations

from typing import Any, Dict

import logging
import voluptuous as vol

from aiohttp import ClientSession

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client

from .api import IoTOpenApiClient, IoTOpenApiError
from .const import (
    DOMAIN,
    CONF_BASE_URL,
    CONF_API_KEY,
    CONF_INSTALLATION_ID,
    DEFAULT_BASE_URL,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_TLS,
    DEFAULT_MQTT_PORT,
)

_LOGGER = logging.getLogger(__name__)


async def _async_validate_input(
    hass: HomeAssistant,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate user input by issuing a small API call (HTTP only)."""
    base_url: str = data[CONF_BASE_URL]
    api_key: str = data[CONF_API_KEY]
    installation_id = int(data[CONF_INSTALLATION_ID])

    session: ClientSession = aiohttp_client.async_get_clientsession(hass)
    client = IoTOpenApiClient(
        base_url=base_url,
        api_key=api_key,
        session=session,
    )

    try:
        functions = await client.async_list_functionx(installation_id=installation_id)
    except IoTOpenApiError as err:
        _LOGGER.warning("IoT Open validate_input error: %s", err)
        raise

    if not functions:
        _LOGGER.warning(
            "IoT Open validate_input: no functions for installation %s",
            installation_id,
        )

    return {
        "title": f"IoT Open ({installation_id})",
        "installation_id": installation_id,
    }


class IoTOpenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for IoT Open."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: Dict[str, Any] | None = None,
    ) -> FlowResult:
        errors: Dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input.get(CONF_BASE_URL)}_{user_input.get(CONF_INSTALLATION_ID)}"
            )
            self._abort_if_unique_id_configured()

            try:
                info = await _async_validate_input(self.hass, user_input)
            except IoTOpenApiError as err:
                msg = str(err).lower()
                if "401" in msg or "403" in msg or "invalid" in msg:
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception(
                    "Unexpected error validating IoT Open config"
                )
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_INSTALLATION_ID): int,
                # MQTT connection (optional, for switch control)
                vol.Optional(CONF_MQTT_HOST): str,
                vol.Optional(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT): int,
                vol.Optional(CONF_MQTT_USERNAME): str,
                vol.Optional(CONF_MQTT_PASSWORD): str,
                vol.Optional(CONF_MQTT_TLS, default=False): bool,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Dict[str, Any]) -> FlowResult:
        """Handle reauth when auth fails."""
        self._entry_data = entry_data
        return await self.async_step_reauth_user()

    async def async_step_reauth_user(
        self,
        user_input: Dict[str, Any] | None = None,
    ) -> FlowResult:
        errors: Dict[str, str] = {}

        if user_input is not None:
            new_data = dict(self._entry_data)
            new_data[CONF_API_KEY] = user_input[CONF_API_KEY]

            try:
                await _async_validate_input(self.hass, new_data)
            except IoTOpenApiError:
                errors["base"] = "invalid_auth"
            else:
                entry = await self.async_set_unique_id(
                    f"{new_data[CONF_BASE_URL]}_{new_data[CONF_INSTALLATION_ID]}"
                )
                if entry:
                    self.hass.config_entries.async_update_entry(
                        entry, data=new_data
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        data_schema = vol.Schema({vol.Required(CONF_API_KEY): str})

        return self.async_show_form(
            step_id="reauth_user",
            data_schema=data_schema,
            errors=errors,
        )
