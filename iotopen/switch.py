# SPDX-License-Identifier: Apache-2.0
# custom_components/iotopen/switch.py
#
# Switch platform for IoT Open (writes via internal MQTT client).

from __future__ import annotations

from typing import Any, Optional, Tuple

import json
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import (
    IoTOpenDataUpdateCoordinator,
    IoTOpenFunctionState,
    is_switch_function,
)
from .entity import IoTOpenEntity
from .mqtt_client import IoTOpenMqttClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up IoT Open switches for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IoTOpenDataUpdateCoordinator = data["coordinator"]
    mqtt_client: Optional[IoTOpenMqttClient] = data.get("mqtt")
    mqtt_prefix: Optional[str] = data.get("mqtt_prefix")

    entities: list[IoTOpenSwitch] = []

    for state in coordinator.data.values():
        # Use the shared heuristic so we catch type=='switch', *_switch and
        # any function that has meta.topic_write.
        if not is_switch_function(state):
            continue

        entities.append(
            IoTOpenSwitch(
                coordinator=coordinator,
                function_id=state.function_id,
                entry_id=entry.entry_id,
                mqtt_client=mqtt_client,
                mqtt_prefix=mqtt_prefix,
            )
        )

    if entities:
        _LOGGER.debug("Adding %d IoT Open switches", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug(
            "No IoT Open switch-type functions discovered for entry %s",
            entry.entry_id,
        )


class IoTOpenSwitch(IoTOpenEntity, SwitchEntity):
    """Switch entity that writes to IoT Open MQTT broker."""

    def __init__(
        self,
        *,
        coordinator: IoTOpenDataUpdateCoordinator,
        function_id: int,
        entry_id: str,
        mqtt_client: IoTOpenMqttClient | None,
        mqtt_prefix: str | None = None,
    ) -> None:
        super().__init__(
            coordinator=coordinator,
            function_id=function_id,
            entry_id=entry_id,
        )
        self._mqtt = mqtt_client
        self._mqtt_prefix = mqtt_prefix

        state = self._get_state()
        assert state is not None

        # Slightly more specific unique_id than the base default
        self._attr_unique_id = (
            f"{DOMAIN}_{state.installation_id}_func_{state.function_id}_switch"
        )

        self._topic_read = state.topic_read

        # ------------------------------------------------------------------
        # Build the write topic:
        #   - Prefer meta.topic_write if present
        #   - Prefix with MQTT client id (derived in __init__) if needed
        #   - Fallback to "<install_or_prefix>/set/<topic_read>"
        # ------------------------------------------------------------------
        meta = state.meta or {}
        topic_write_meta = str(meta.get("topic_write") or "").strip()

        default_prefix = mqtt_prefix or str(state.installation_id)

        if topic_write_meta:
            # If topic_write already looks fully qualified ("2086/set/..."),
            # use it as-is. Otherwise prefix it.
            if topic_write_meta[0].isdigit() and "/" in topic_write_meta:
                self._topic_set = topic_write_meta
            else:
                self._topic_set = f"{default_prefix}/{topic_write_meta.lstrip('/')}"
        else:
            self._topic_set = f"{default_prefix}/set/{self._topic_read.lstrip('/')}"

        self._state_on, self._state_off = self._compute_on_off_values(state)

        _LOGGER.debug(
            "IoT Open switch %s using set-topic %s (on=%s off=%s prefix=%s)",
            self._attr_unique_id,
            self._topic_set,
            self._state_on,
            self._state_off,
            self._mqtt_prefix,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_state(self) -> IoTOpenFunctionState | None:
        return self.coordinator.data.get(self._function_id)

    @staticmethod
    def _parse_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _compute_on_off_values(self, state: IoTOpenFunctionState) -> Tuple[int, int]:
        """Derive on/off payloads from meta, with sensible defaults."""
        meta = state.meta or {}

        # For Z-Wave switches typical: on=255, off=0
        default_on = 255
        default_off = 0

        raw_on = meta.get("state_on")
        raw_off = meta.get("state_off")

        on_val = self._parse_int(raw_on, default_on)
        off_val = self._parse_int(raw_off, default_off)

        return on_val, off_val

    def _value_to_bool(self, value: Any) -> bool:
        """Best-effort mapping from last_value -> on/off."""
        if value is None:
            return False

        try:
            v = int(value)
        except (TypeError, ValueError):
            return bool(value)

        # Prefer explicit mapping if it matches
        if v == self._state_on:
            return True
        if v == self._state_off:
            return False

        # Fallback: non-zero means "on".
        return v != 0

    async def _publish(self, value: int) -> None:
        """Publish a command to the IoT Open MQTT broker.

        IoT Open expects JSON payloads of the form:
            {"value": <number>}
        """
        if self._mqtt is None:
            _LOGGER.warning(
                "IoT Open switch %s: internal MQTT client not configured",
                self.entity_id,
            )
            return

        payload_obj = {"value": int(value)}
        payload = json.dumps(payload_obj)

        try:
            await self._mqtt.async_publish(
                self._topic_set,
                payload,
                qos=1,
                retain=False,
            )
            _LOGGER.debug(
                "IoT Open switch %s: published %s to %s",
                self.entity_id,
                payload,
                self._topic_set,
            )
        except Exception as err:  # pragma: no cover
            _LOGGER.warning(
                "IoT Open switch %s: failed to publish to %s: %s",
                self.entity_id,
                self._topic_set,
                err,
            )

    # ------------------------------------------------------------------
    # HA entity API
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool:
        state = self._get_state()
        if state is None:
            return False
        return self._value_to_bool(state.last_value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._publish(self._state_on)

        # Optimistic local update so HA reflects the change immediately.
        state = self._get_state()
        if state is not None:
            state.last_value = self._state_on
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._publish(self._state_off)

        # Optimistic local update so HA reflects the change immediately.
        state = self._get_state()
        if state is not None:
            state.last_value = self._state_off
        self.async_write_ha_state()

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
            "topic_set": self._topic_set,
            "last_timestamp": state.last_timestamp,
            "device_id": state.device_id,
            "state_on": self._state_on,
            "state_off": self._state_off,
        }
