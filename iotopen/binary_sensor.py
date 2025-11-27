# SPDX-License-Identifier: MIT
# custom_components/iotopen/binary_sensor.py

"""Binary sensor platform for IoT Open."""

from __future__ import annotations

from typing import Any

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import (
    IoTOpenDataUpdateCoordinator,
    IoTOpenFunctionState,
    is_binary_function,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up IoT Open binary_sensors for a config entry."""
    coordinator: IoTOpenDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    entities: list[IoTOpenFunctionBinarySensor] = []

    for state in coordinator.data.values():
        if not is_binary_function(state):
            continue

        entities.append(
            IoTOpenFunctionBinarySensor(
                coordinator=coordinator,
                function_id=state.function_id,
                entry_id=entry.entry_id,
            )
        )

    async_add_entities(entities)


class IoTOpenFunctionBinarySensor(
    CoordinatorEntity[IoTOpenDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Binary sensor representing an alarm-style FunctionX."""

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
            f"iotopen_{state.installation_id}_func_{state.function_id}_binary"
        )
        self._attr_name = state.name

        # Treat alarm_* as problem/power alarms by default.
        self._attr_device_class = _guess_device_class(state)

    def _get_state(self) -> IoTOpenFunctionState | None:
        return self.coordinator.data.get(self._function_id)

    @property
    def is_on(self) -> bool:
        """Return true if the alarm condition is active."""
        state = self._get_state()
        if state is None:
            return False

        value = state.last_value
        meta = state.meta or {}

        # Attempt numeric comparison using state_alarm / state_no_alarm
        alarm_raw = meta.get("state_alarm")
        no_alarm_raw = meta.get("state_no_alarm")

        try:
            value_int = int(value)
        except (TypeError, ValueError):
            # Fall back to truthiness if value is non-numeric.
            return bool(value)

        try:
            alarm_int = int(alarm_raw) if alarm_raw is not None else None
        except (TypeError, ValueError):
            alarm_int = None

        try:
            no_alarm_int = int(
                no_alarm_raw) if no_alarm_raw is not None else None
        except (TypeError, ValueError):
            no_alarm_int = None

        if alarm_int is not None and value_int == alarm_int:
            return True
        if no_alarm_int is not None and value_int == no_alarm_int:
            return False

        # Fallback heuristic: non-zero means "on".
        return value_int != 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._get_state()
        if state is None:
            return {}

        meta = state.meta or {}
        return {
            "installation_id": state.installation_id,
            "function_id": state.function_id,
            "type": state.type,
            "topic_read": state.topic_read,
            "last_timestamp": state.last_timestamp,
            "device_id": state.device_id,
            "state_alarm": meta.get("state_alarm"),
            "state_no_alarm": meta.get("state_no_alarm"),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Group functions either under DeviceX or under the installation."""
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
    def available(self) -> bool:
        return self._get_state() is not None


def _guess_device_class(state: IoTOpenFunctionState) -> BinarySensorDeviceClass | None:
    """Try to map alarm_* to a reasonable binary_sensor device_class."""
    t = state.type.lower()
    meta = state.meta or {}
    zw_type = str(meta.get("zwave.type") or "").lower()

    # Your screenshot: type "alarm_power_management", zwave.type "power_management"
    if "power" in t or "power" in zw_type:
        return BinarySensorDeviceClass.POWER

    if "smoke" in t or "smoke" in zw_type:
        return BinarySensorDeviceClass.SMOKE

    if "water" in t or "flood" in t or "water" in zw_type:
        return BinarySensorDeviceClass.MOISTURE

    # Default to "problem" for generic alarms.
    if t.startswith("alarm_"):
        return BinarySensorDeviceClass.PROBLEM

    return None
