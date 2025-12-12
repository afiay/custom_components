# SPDX-License-Identifier: Apache-2.0
# custom_components/iotopen/entity.py
#
# Base entity classes and helpers for the IoT Open integration.
#
# This keeps the sensor/binary_sensor/switch platforms DRY and ensures that
# all entities share the same unique_id/device_info conventions.

from __future__ import annotations

from typing import Any, Dict, Optional

import logging

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IoTOpenDataUpdateCoordinator, IoTOpenFunctionState

_LOGGER = logging.getLogger(__name__)


class IoTOpenEntity(CoordinatorEntity[IoTOpenDataUpdateCoordinator]):
    """Base class for all IoT Open entities."""

    _attr_has_entity_name = True
    _attr_attribution = "Data via IoT Open"

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
        if state is None:
            # This should not happen during normal setup, but be defensive.
            _LOGGER.debug(
                "IoT Open entity created without initial state: func=%s entry=%s",
                function_id,
                entry_id,
            )
            return

        # Consistent unique_id across all platforms
        self._attr_unique_id = (
            f"{DOMAIN}_{state.installation_id}_func_{state.function_id}"
        )

        # Default name (platforms can override if needed)
        self._attr_name = state.name

    # ------------------------------------------------------------------
    # Common helper for child classes
    # ------------------------------------------------------------------

    def _get_state(self) -> Optional[IoTOpenFunctionState]:
        """Return the cached state for this function, if any."""
        return self.coordinator.data.get(self._function_id)

    @property
    def available(self) -> bool:
        """Entity is available if coordinator has state for this function."""
        return self._get_state() is not None

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
