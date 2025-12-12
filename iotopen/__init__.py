# SPDX-License-Identifier: Apache-2.0
# custom_components/iotopen/__init__.py
#
# The IoT Open integration.
#
# - Creates an IoTOpenApiClient + IoTOpenDataUpdateCoordinator per config entry
# - Optionally creates an internal MQTT client (IoTOpenMqttClient) per entry
# - Exposes services to manage DeviceX / FunctionX and their metadata

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

import logging

from aiohttp import ClientSession
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
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

# Key used inside hass.data[DOMAIN] to remember we have registered
# our services and stop-listener exactly once.
KEY_SERVICES_REGISTERED = "_services_registered"
KEY_STOP_LISTENER_REGISTERED = "_stop_listener_registered"


async def async_setup(hass: HomeAssistant, config: Mapping[str, Any]) -> bool:
    """Set up via YAML (not used; config entries only).

    Kept only so the integration can appear even if a user accidentally
    adds a stub in configuration.yaml.
    """
    _LOGGER.debug("IoT Open: async_setup called (YAML config is ignored)")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up IoT Open from a config entry."""
    base_url: str = entry.data[CONF_BASE_URL]
    api_key: str = entry.data[CONF_API_KEY]
    installation_id = int(entry.data[CONF_INSTALLATION_ID])

    _LOGGER.info(
        "Setting up IoT Open entry %s (installation_id=%s, base_url=%s)",
        entry.entry_id,
        installation_id,
        base_url,
    )

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
        # Most likely HTTP / API issues (auth, 4xx/5xx, etc.)
        raise ConfigEntryNotReady(f"IoT Open API error: {err}") from err
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.exception(
            "Unexpected error setting up IoT Open entry %s", entry.entry_id
        )
        raise ConfigEntryNotReady(f"Unexpected error: {err}") from err

    # ------------------------------------------------------------------
    # Optional internal MQTT client (our own, not HA's MQTT integration)
    # + derive MQTT topic prefix from username (box:<client_id>).
    # ------------------------------------------------------------------
    mqtt_client: Optional[IoTOpenMqttClient] = None
    mqtt_prefix: Optional[str] = None

    mqtt_host = entry.data.get(CONF_MQTT_HOST)
    if mqtt_host:
        mqtt_username = entry.data.get(CONF_MQTT_USERNAME) or ""
        mqtt_password = entry.data.get(CONF_MQTT_PASSWORD) or None

        # Try to derive prefix from username "box:2086" -> "2086"
        if ":" in mqtt_username:
            _, suffix = mqtt_username.split(":", 1)
            if suffix.isdigit():
                mqtt_prefix = suffix

        mqtt_client = IoTOpenMqttClient(
            host=mqtt_host,
            port=int(entry.data.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)),
            username=mqtt_username or None,
            password=mqtt_password,
            use_tls=bool(entry.data.get(CONF_MQTT_TLS, False)),
        )
        _LOGGER.info(
            "IoT Open: internal MQTT client configured for host %s:%s (tls=%s, prefix=%s)",
            mqtt_host,
            entry.data.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT),
            entry.data.get(CONF_MQTT_TLS, False),
            mqtt_prefix,
        )
    else:
        _LOGGER.info(
            "IoT Open: MQTT host not configured for entry %s; switches will be read-only",
            entry.entry_id,
        )

    # Runtime data for this entry
    domain_entries: Dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    domain_entries[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "mqtt": mqtt_client,
        "mqtt_prefix": mqtt_prefix,
    }

    # Listen for changes to this entry (future options / migrations).
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    # Ensure services + stop listener registered once
    _ensure_services_registered(hass)
    _ensure_stop_listener_registered(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an IoT Open config entry."""
    _LOGGER.info("Unloading IoT Open entry %s", entry.entry_id)

    domain_entries: Dict[str, Any] = hass.data.get(DOMAIN, {})
    entry_data: Dict[str, Any] = domain_entries.get(entry.entry_id, {})

    # Stop MQTT client (if any) before unloading platforms.
    mqtt_client = entry_data.get("mqtt")
    if mqtt_client is not None and hasattr(mqtt_client, "async_disconnect"):
        try:
            await mqtt_client.async_disconnect()  # type: ignore[func-returns-value]
        except Exception as err:  # pragma: no cover
            _LOGGER.warning(
                "IoT Open: error while disconnecting MQTT client for entry %s: %s",
                entry.entry_id,
                err,
            )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        domain_entries.pop(entry.entry_id, None)
        if not domain_entries:
            # No more active entries – clean up our domain data.
            hass.data.pop(DOMAIN, None)
            _LOGGER.debug("IoT Open: all entries unloaded, domain data cleared")

    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle updates to a config entry by reloading it.

    This gives us a clean path if we later introduce options or need to
    migrate config_entry.data/options without manual restart.
    """
    _LOGGER.debug("Reloading IoT Open config entry %s after update", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


def _ensure_stop_listener_registered(hass: HomeAssistant) -> None:
    """Register a one-time listener to cleanly disconnect MQTT on HA shutdown."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(KEY_STOP_LISTENER_REGISTERED):
        return

    async def _async_handle_hass_stop(_event) -> None:
        """Disconnect all MQTT clients when Home Assistant stops."""
        domain_entries: Dict[str, Any] = hass.data.get(DOMAIN, {})
        _LOGGER.debug("IoT Open: HA is stopping; disconnecting MQTT clients")
        for key, value in list(domain_entries.items()):
            if key.startswith("_"):
                continue
            mqtt_client = value.get("mqtt")
            if mqtt_client is None or not hasattr(mqtt_client, "async_disconnect"):
                continue
            try:
                await mqtt_client.async_disconnect()  # type: ignore[func-returns-value]
            except Exception:  # pragma: no cover
                _LOGGER.debug(
                    "IoT Open: error during shutdown MQTT disconnect for entry %s",
                    key,
                    exc_info=True,
                )

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_handle_hass_stop)
    domain_data[KEY_STOP_LISTENER_REGISTERED] = True


# ---------------------------------------------------------------------------
# Service registration – create/delete devices & functions, assign function->device,
# and generic metadata management.
# ---------------------------------------------------------------------------


def _ensure_services_registered(hass: HomeAssistant) -> None:
    """Register domain services once."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(KEY_SERVICES_REGISTERED):
        return

    # ------------------------------------------------------------------
    # Helper: resolve which config entry / client to use
    # ------------------------------------------------------------------
    def _resolve_entry_data(
        installation_id: Optional[int],
    ) -> Tuple[IoTOpenApiClient, IoTOpenDataUpdateCoordinator]:
        domain_data_inner: Dict[str, Any] = hass.data.get(DOMAIN, {})
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
        data = create_device_schema(dict(call.data))
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id
            if installation_id is not None
            else coordinator.installation_id
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

        # Ensure Home Assistant entities pick up the new device.
        await coordinator.async_request_refresh()

    async def async_handle_delete_device(call: ServiceCall) -> None:
        data = delete_device_schema(dict(call.data))
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id
            if installation_id is not None
            else coordinator.installation_id
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

        await coordinator.async_request_refresh()

    async def async_handle_create_function(call: ServiceCall) -> None:
        data = create_function_schema(dict(call.data))
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id
            if installation_id is not None
            else coordinator.installation_id
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
        data = delete_function_schema(dict(call.data))
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id
            if installation_id is not None
            else coordinator.installation_id
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
        data = assign_function_device_schema(dict(call.data))
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id
            if installation_id is not None
            else coordinator.installation_id
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
        data = set_device_meta_schema(dict(call.data))
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id
            if installation_id is not None
            else coordinator.installation_id
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
        data = set_function_meta_schema(dict(call.data))
        installation_id = data.get("installation_id")
        api, coordinator = _resolve_entry_data(installation_id)

        effective_installation = (
            installation_id
            if installation_id is not None
            else coordinator.installation_id
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

    domain_data[KEY_SERVICES_REGISTERED] = True
    _LOGGER.debug("IoT Open: domain services registered")
