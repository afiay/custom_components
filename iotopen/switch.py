# SPDX-License-Identifier: MIT
# custom_components/iotopen/switch.py

"""Switch platform for IoT Open."""

from __future__ import annotations

from typing import Any, Optional

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import (
    IoTOpenDataUpdateCoordinator,
    IoTOpenFunctionState,
    is_switch_function,
)
from .mqtt_client import IoTOpenMqttClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up IoT Open switches for a config entry."""
    coordinator: IoTOpenDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    entities: list[IoTOpenFunctionSwitch] = []

    for state in coordinator.data.values():
        if not is_switch_function(state):
            continue

        entities.append(
            IoTOpenFunctionSwitch(
                coordinator=coordinator,
                function_id=state.function_id,
                entry_id=entry.entry_id,
            )
        )

    async_add_entities(entities)


class IoTOpenFunctionSwitch(
    CoordinatorEntity[IoTOpenDataUpdateCoordinator],
    SwitchEntity,
):
    """Switch representing one IoT Open FunctionX."""

    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        coordinator: IoTOpenDataUpdateCoordinator,
        function_id: int,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._function_id = function_id
        self._entry_id = entry_id

        state = self._get_state()
        assert state is not None

        self._attr_unique_id = (
            f"iotopen_{state.installation_id}_func_{state.function_id}_switch"
        )
        self._attr_name = state.name

        meta = dict(state.meta or {})
        self._topic_write: Optional[str] = meta.get("topic_write")

        # Meta-driven interpretation of values
        self._state_on = meta.get("state_on")
        self._state_off = meta.get("state_off")

        self._payload_on = meta.get("payload_on") or self._state_on or "1"
        self._payload_off = meta.get("payload_off") or self._state_off or "0"

        self._mqtt: Optional[IoTOpenMqttClient] = None

    async def async_added_to_hass(self) -> None:
        """Resolve MQTT client once the entity is attached to HA."""
        await super().async_added_to_hass()
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        self._mqtt = entry_data.get("mqtt")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _get_state(self) -> IoTOpenFunctionState | None:
        return self.coordinator.data.get(self._function_id)

    def _value_is_on(self, raw: Any) -> bool:
        """Interpret a FunctionX value as on/off using meta first, then generic fallback."""
        if raw is None:
            return False

        text = str(raw)

        # 1) If user provided explicit on/off values, honour them.
        if self._state_on is not None or self._state_off is not None:
            if self._state_on is not None and text == str(self._state_on):
                return True
            if self._state_off is not None and text == str(self._state_off):
                return False

        # 2) Generic numeric fallback: non-zero → on.
        try:
            return float(text) != 0.0
        except (TypeError, ValueError):
            # 3) Last fallback: Python truthiness.
            return bool(raw)

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @property
    def is_on(self) -> bool:
        state = self._get_state()
        if state is None:
            return False
        return self._value_is_on(state.last_value)

    @property
    def available(self) -> bool:
        return self._get_state() is not None

    @property
    def device_info(self) -> DeviceInfo:
        state = self._get_state()
        if state is None:
            return DeviceInfo(
                identifiers={(DOMAIN, "installation_unknown")},
                name="IoT Open Installation",
                manufacturer="IoT Open",
                model="Lynx",
            )

        if state.device_id is not None:
            identifier = f"device_{state.device_id}"
            name = f"IoT Open Device {state.device_id}"
        else:
            identifier = f"installation_{state.installation_id}"
            name = f"IoT Open Installation {state.installation_id}"

        return DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=name,
            manufacturer="IoT Open",
            model="Lynx",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._get_state()
        if state is None:
            return {}

        return {
            "installation_id": state.installation_id,
            "function_id": state.function_id,
            "type": state.type,
            "topic_read": state.topic_read,
            "topic_write": self._topic_write,
            "last_timestamp": state.last_timestamp,
            "device_id": state.device_id,
            "state_on": self._state_on,
            "state_off": self._state_off,
            "payload_on": self._payload_on,
            "payload_off": self._payload_off,
        }

    # ------------------------------------------------------------------ #
    # Commands – publish via internal MQTT client
    # ------------------------------------------------------------------ #

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self._topic_write:
            _LOGGER.warning(
                "IoT Open switch %s has no meta.topic_write; cannot turn on",
                self.entity_id,
            )
            return

        if not self._mqtt:
            _LOGGER.warning(
                "IoT Open switch %s: internal MQTT client not configured",
                self.entity_id,
            )
            return

        payload = str(self._payload_on)
        await self._mqtt.async_publish(self._topic_write, payload, qos=0, retain=False)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if not self._topic_write:
            _LOGGER.warning(
                "IoT Open switch %s has no meta.topic_write; cannot turn off",
                self.entity_id,
            )
            return

        if not self._mqtt:
            _LOGGER.warning(
                "IoT Open switch %s: internal MQTT client not configured",
                self.entity_id,
            )
            return

        payload = str(self._payload_off)
        await self._mqtt.async_publish(self._topic_write, payload, qos=0, retain=False)
        await self.coordinator.async_request_refresh()
