# SPDX-License-Identifier: MIT
# custom_components/iotopen/__init__.py
#
# The IoT Open integration.
#
# - Creates an IoTOpenApiClient + IoTOpenDataUpdateCoordinator per config entry
# - Optionally creates an internal MQTT client (IoTOpenMqttClient) per entry
# - Exposes services to manage DeviceX / FunctionX and their metadata

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import logging

from aiohttp import ClientSession
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client, config_validation as cv

from .api import IoTOpenApiClient, IoTOpenApiError
from .const import (
    DOMAIN,
    CONF_BASE_URL,
    CONF_API_KEY,
    CONF_INSTALLATION_ID,
    PLATFORMS,
    SERVICE_CREATE_DEVICE,
    SERVICE_DELETE_DEVICE,
    SERVICE_CREATE_FUNCTION,
    SERVICE_DELETE_FUNCTION,
    SERVICE_ASSIGN_FUNCTION_DEVICE,
    SERVICE_SET_DEVICE_META,
    SERVICE_SET_FUNCTION_META,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_TLS,
    DEFAULT_MQTT_PORT,
)
from .coordinator import IoTOpenDataUpdateCoordinator
from .mqtt_client import IoTOpenMqttClient

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """Set up via YAML (not used; config entries only)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up IoT Open from a config entry."""
    base_url: str = entry.data[CONF_BASE_URL]
    api_key: str = entry.data[CONF_API_KEY]
    installation_id = int(entry.data[CONF_INSTALLATION_ID])

    session: ClientSession = aiohttp_client.async_get_clientsession(hass)
    api = IoTOpenApiClient(base_url=base_url, api_key=api_key, session=session)

    coordinator = IoTOpenDataUpdateCoordinator(
        hass,
        api=api,
        installation_id=installation_id,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except IoTOpenApiError as err:
        raise ConfigEntryNotReady(f"IoT Open API error: {err}") from err
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.exception("Unexpected error setting up IoT Open entry")
        raise ConfigEntryNotReady(f"Unexpected error: {err}") from err

    # Optional internal MQTT client (our own, not HA's MQTT integration)
    mqtt_client: Optional[IoTOpenMqttClient] = None
    mqtt_host = entry.data.get(CONF_MQTT_HOST)
    if mqtt_host:
        mqtt_client = IoTOpenMqttClient(
            host=mqtt_host,
            port=int(entry.data.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)),
            username=entry.data.get(CONF_MQTT_USERNAME) or None,
            password=entry.data.get(CONF_MQTT_PASSWORD) or None,
            tls=bool(entry.data.get(CONF_MQTT_TLS, False)),
        )
        _LOGGER.info(
            "IoT Open: internal MQTT client configured for host %s:%s (tls=%s)",
            mqtt_host,
            entry.data.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT),
            entry.data.get(CONF_MQTT_TLS, False),
        )
    else:
        _LOGGER.info(
            "IoT Open: MQTT host not configured; switches will be read-only"
        )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "mqtt": mqtt_client,
    }

    _ensure_services_registered(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an IoT Open config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        domain_entries = hass.data.get(DOMAIN, {})
        domain_entries.pop(entry.entry_id, None)
        if not domain_entries:
            hass.data.pop(DOMAIN, None)

    return unload_ok


# ---------------------------------------------------------------------------
# Service registration – create/delete devices & functions, assign function->device,
# and generic metadata management.
# ---------------------------------------------------------------------------

def _ensure_services_registered(hass: HomeAssistant) -> None:
    """Register domain services once."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_services_registered"):
        return

    # ------------------------------------------------------------------
    # Helper: resolve which config entry / client to use
    # ------------------------------------------------------------------
    def _resolve_entry_data(
        installation_id: Optional[int],
    ) -> Tuple[IoTOpenApiClient, IoTOpenDataUpdateCoordinator]:
        domain_data_inner = hass.data.get(DOMAIN, {})
        chosen_api: Optional[IoTOpenApiClient] = None
        chosen_coord: Optional[IoTOpenDataUpdateCoordinator] = None

        for key, value in domain_data_inner.items():
            if key.startswith("_"):
                continue
            api: IoTOpenApiClient = value["api"]
            coord: IoTOpenDataUpdateCoordinator = value["coordinator"]

            if installation_id is None or installation_id == coord.installation_id:
                chosen_api = api
                chosen_coord = coord
                break

        if chosen_api is None or chosen_coord is None:
            raise IoTOpenApiError(
                "No IoT Open config entry found for requested installation_id"
            )
        return chosen_api, chosen_coord

    # ------------------------------------------------------------------
    # Service schemas
    # ------------------------------------------------------------------

    create_device_schema = vol.Schema(
        {
            vol.Optional("installation_id"): cv.positive_int,
            vol.Required("type"): cv.string,
            vol.Required("name"): cv.string,
            vol.Optional("meta", default={}): {cv.string: cv.match_all},
        }
    )

    delete_device_schema = vol.Schema(
        {
            vol.Optional("installation_id"): cv.positive_int,
            vol.Required("device_id"): cv.positive_int,
        }
    )

    create_function_schema = vol.Schema(
        {
            vol.Optional("installation_id"): cv.positive_int,
            vol.Required("type"): cv.string,
            vol.Required("name"): cv.string,
            vol.Required("topic_read"): cv.string,
            vol.Optional("device_id"): cv.positive_int,
            vol.Optional("meta", default={}): {cv.string: cv.match_all},
        }
    )

    delete_function_schema = vol.Schema(
        {
            vol.Optional("installation_id"): cv.positive_int,
            vol.Required("function_id"): cv.positive_int,
        }
    )

    assign_function_device_schema = vol.Schema(
        {
            vol.Optional("installation_id"): cv.positive_int,
            vol.Required("function_id"): cv.positive_int,
            vol.Required("device_id"): cv.positive_int,
        }
    )

    # Generic metadata services (DeviceX / FunctionX)
    set_device_meta_schema = vol.Schema(
        {
            vol.Optional("installation_id"): cv.positive_int,
            vol.Required("device_id"): cv.positive_int,
            vol.Required("meta_key"): cv.string,
            vol.Required("value"): cv.match_all,
            vol.Optional("protected", default=False): cv.boolean,
            vol.Optional("silent"): cv.boolean,
        }
    )

    set_function_meta_schema = vol.Schema(
        {
            vol.Optional("installation_id"): cv.positive_int,
            vol.Required("function_id"): cv.positive_int,
            vol.Required("meta_key"): cv.string,
            vol.Required("value"): cv.match_all,
            vol.Optional("protected", default=False): cv.boolean,
            vol.Optional("silent"): cv.boolean,
        }
    )

    # ------------------------------------------------------------------
    # Service handlers
    # ------------------------------------------------------------------

    async def async_handle_create_device(call: ServiceCall) -> None:
        data = create_device_schema(call.data)
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id if installation_id is not None else coordinator.installation_id
        )

        meta = dict(data["meta"])
        meta.setdefault("name", data["name"])

        created = await api.async_create_device(
            installation_id=effective_installation,
            type_=data["type"],
            meta=meta,
        )
        _LOGGER.info(
            "Created IoT Open DeviceX id=%s installation=%s type=%s name=%s",
            created.get("id"),
            effective_installation,
            data["type"],
            data["name"],
        )

    async def async_handle_delete_device(call: ServiceCall) -> None:
        data = delete_device_schema(call.data)
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id if installation_id is not None else coordinator.installation_id
        )

        await api.async_delete_device(
            installation_id=effective_installation,
            device_id=data["device_id"],
        )
        _LOGGER.info(
            "Deleted IoT Open DeviceX id=%s installation=%s",
            data["device_id"],
            effective_installation,
        )

    async def async_handle_create_function(call: ServiceCall) -> None:
        data = create_function_schema(call.data)
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id if installation_id is not None else coordinator.installation_id
        )

        meta = dict(data["meta"])
        meta.setdefault("name", data["name"])
        meta.setdefault("topic_read", data["topic_read"])

        device_id = data.get("device_id")
        if device_id is not None:
            # Use meta.device_id as the link to DeviceX
            meta.setdefault("device_id", str(device_id))

        created = await api.async_create_function(
            installation_id=effective_installation,
            type_=data["type"],
            meta=meta,
        )
        _LOGGER.info(
            "Created IoT Open FunctionX id=%s installation=%s type=%s name=%s device_id=%s",
            created.get("id"),
            effective_installation,
            data["type"],
            data["name"],
            device_id,
        )

        # Refresh entities so the new function appears.
        await coordinator.async_request_refresh()

    async def async_handle_delete_function(call: ServiceCall) -> None:
        data = delete_function_schema(call.data)
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id if installation_id is not None else coordinator.installation_id
        )

        await api.async_delete_function(
            installation_id=effective_installation,
            function_id=data["function_id"],
        )
        _LOGGER.info(
            "Deleted IoT Open FunctionX id=%s installation=%s",
            data["function_id"],
            effective_installation,
        )

        await coordinator.async_request_refresh()

    async def async_handle_assign_function_device(call: ServiceCall) -> None:
        data = assign_function_device_schema(call.data)
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id if installation_id is not None else coordinator.installation_id
        )

        # Store the relation as meta.device_id on the FunctionX via the meta API.
        await api.async_set_function_meta(
            installation_id=effective_installation,
            function_id=data["function_id"],
            meta_key="device_id",
            value=data["device_id"],
            protected=False,
        )

        _LOGGER.info(
            "Assigned IoT Open FunctionX id=%s to DeviceX id=%s (installation=%s)",
            data["function_id"],
            data["device_id"],
            effective_installation,
        )

        await coordinator.async_request_refresh()

    async def async_handle_set_device_meta(call: ServiceCall) -> None:
        data = set_device_meta_schema(call.data)
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id if installation_id is not None else coordinator.installation_id
        )

        await api.async_set_device_meta(
            installation_id=effective_installation,
            device_id=data["device_id"],
            meta_key=data["meta_key"],
            value=data["value"],
            protected=data["protected"],
            silent=data.get("silent"),
        )

        _LOGGER.info(
            "Set meta '%s' on DeviceX id=%s (installation=%s)",
            data["meta_key"],
            data["device_id"],
            effective_installation,
        )

    async def async_handle_set_function_meta(call: ServiceCall) -> None:
        data = set_function_meta_schema(call.data)
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id if installation_id is not None else coordinator.installation_id
        )

        await api.async_set_function_meta(
            installation_id=effective_installation,
            function_id=data["function_id"],
            meta_key=data["meta_key"],
            value=data["value"],
            protected=data["protected"],
            silent=data.get("silent"),
        )

        _LOGGER.info(
            "Set meta '%s' on FunctionX id=%s (installation=%s)",
            data["meta_key"],
            data["function_id"],
            effective_installation,
        )

        await coordinator.async_request_refresh()

    # ------------------------------------------------------------------
    # Register all services
    # ------------------------------------------------------------------

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_DEVICE,
        async_handle_create_device,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_DEVICE,
        async_handle_delete_device,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_FUNCTION,
        async_handle_create_function,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_FUNCTION,
        async_handle_delete_function,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ASSIGN_FUNCTION_DEVICE,
        async_handle_assign_function_device,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DEVICE_META,
        async_handle_set_device_meta,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_FUNCTION_META,
        async_handle_set_function_meta,
    )

    domain_data["_services_registered"] = True
