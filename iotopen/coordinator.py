# SPDX-License-Identifier: MIT
# custom_components/iotopen/coordinator.py

"""DataUpdateCoordinator for IoT Open."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Mapping, Optional

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import IoTOpenApiClient, IoTOpenApiError
from .const import DEFAULT_UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class IoTOpenFunctionState:
    """Flattened function + last value + metadata.

    We also keep an optional device_id (from meta.device_id) so that
    entities can be grouped under their physical DeviceX in HA.
    """

    function_id: int
    installation_id: int
    type: str
    name: str
    topic_read: str
    last_value: Any | None
    last_timestamp: int | None
    device_id: Optional[int] = None
    meta: Mapping[str, Any] = None  # original meta from FunctionX


def is_binary_function(state: IoTOpenFunctionState) -> bool:
    """Decide if a FunctionX should be represented as a binary_sensor.

    Heuristics:
      - type starts with 'alarm_'
      - OR meta contains both 'state_alarm' and 'state_no_alarm'
    """
    t = state.type.lower()
    meta = state.meta or {}

    # Switch-like types are handled by the switch platform instead.
    if "switch" in t:
        return False

    if t.startswith("alarm_"):
        return True

    if "state_alarm" in meta and "state_no_alarm" in meta:
        return True

    return False


def is_switch_function(state: IoTOpenFunctionState) -> bool:
    """Decide if a FunctionX should be represented as a switch.

    Heuristics are deliberately generic and meta-driven:

      - type exactly 'switch' or endswith '_switch'
      - OR meta contains 'topic_write' (we can send commands)
    """
    t = state.type.lower()
    meta = state.meta or {}

    if t == "switch" or t.endswith("_switch"):
        return True

    if "topic_write" in meta:
        return True

    return False


class IoTOpenDataUpdateCoordinator(
    DataUpdateCoordinator[Dict[int, IoTOpenFunctionState]]
):
    """Coordinator that polls IoT Open for function values."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        api: IoTOpenApiClient,
        installation_id: int,
        update_interval: int = DEFAULT_UPDATE_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"IoT Open ({installation_id})",
            update_interval=timedelta(seconds=update_interval),
        )
        self._api = api
        self._installation_id = installation_id

    @property
    def installation_id(self) -> int:
        return self._installation_id

    async def _async_update_data(self) -> Dict[int, IoTOpenFunctionState]:
        """Fetch data from IoT Open.

        Strategy:
          1. Get FunctionX list for the installation.
          2. Collect all `topic_read` from function.meta.
          3. Query Status for those topics.
          4. Map latest value per topic.
        """
        try:
            functionx_raw = await self._api.async_list_functionx(
                installation_id=self._installation_id
            )
        except IoTOpenApiError as err:
            raise UpdateFailed(f"Failed to fetch FunctionX: {err}") from err

        topics: List[str] = []
        function_by_topic: Dict[str, Mapping[str, Any]] = {}

        for item in functionx_raw:
            meta = item.get("meta") or {}
            topic = meta.get("topic_read")
            if not topic:
                continue
            topics.append(topic)
            function_by_topic[topic] = item

        status_by_topic: Dict[str, Mapping[str, Any]] = {}

        if topics:
            try:
                status_raw = await self._api.async_get_status_for_topics(
                    installation_id=self._installation_id,
                    topics=topics,
                )
            except IoTOpenApiError as err:
                raise UpdateFailed(f"Failed to fetch status: {err}") from err

            for sample in status_raw:
                topic = sample.get("topic")
                if not topic:
                    continue
                ts = sample.get("timestamp") or 0
                current = status_by_topic.get(topic)
                if current is None or ts >= current.get("timestamp", 0):
                    status_by_topic[topic] = sample

        result: Dict[int, IoTOpenFunctionState] = {}

        for topic, func in function_by_topic.items():
            func_id = int(func.get("id"))
            meta = func.get("meta") or {}
            status = status_by_topic.get(topic)

            raw_dev_id = meta.get("device_id")
            if raw_dev_id is None:
                device_id: Optional[int] = None
            else:
                try:
                    device_id = int(raw_dev_id)
                except (TypeError, ValueError):
                    device_id = None

            result[func_id] = IoTOpenFunctionState(
                function_id=func_id,
                installation_id=int(
                    func.get("installation_id", self._installation_id)
                ),
                type=str(func.get("type", "")),
                name=str(meta.get("name") or f"Function {func_id}"),
                topic_read=topic,
                last_value=None if status is None else status.get("value"),
                last_timestamp=None if status is None else status.get(
                    "timestamp"),
                device_id=device_id,
                meta=meta,
            )

        _LOGGER.debug(
            "IoT Open coordinator: %d functions with status for installation %s",
            len(result),
            self._installation_id,
        )
        return result
