# SPDX-License-Identifier: Apache-2.0
# custom_components/iotopen/coordinator.py
#
# DataUpdateCoordinator for IoT Open.

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, Mapping, Optional

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
    meta: Mapping[str, Any] | None = None  # original meta from FunctionX


# ---------------------------------------------------------------------------
# Heuristics: what becomes a binary_sensor vs a switch vs a "normal" sensor
# ---------------------------------------------------------------------------


def is_binary_function(state: IoTOpenFunctionState) -> bool:
    """Decide if a FunctionX should be represented as a binary_sensor.

    Heuristics:
      - type starts with 'alarm_'
      - OR meta contains both 'state_alarm' and 'state_no_alarm'
      - BUT any '...switch' types are excluded (handled by switch platform)
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


def _parse_device_id(raw: Any) -> Optional[int]:
    """Best-effort conversion of meta.device_id to an int."""
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_exposed_to_ha(meta: Mapping[str, Any] | None) -> bool:
    """Return True if this FunctionX should be exposed to Home Assistant.

    We use simple, meta-driven flags so integrators can control visibility
    from Lynx/IoT Open without touching HA:

      - If meta['ha.disabled'] is truthy -> NOT exposed
      - If meta['ha.hidden'] is truthy   -> NOT exposed

    Any of: "1", "true", "yes", "on" (case-insensitive) are treated as True.
    """
    if not meta:
        return True

    def _truthy(v: Any) -> bool:
        s = str(v).strip().lower()
        return s in ("1", "true", "yes", "on")

    if _truthy(meta.get("ha.disabled", "")):
        return False

    if _truthy(meta.get("ha.hidden", "")):
        return False

    return True


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


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
        """Return the installation id this coordinator is bound to."""
        return self._installation_id

    async def _async_update_data(self) -> Dict[int, IoTOpenFunctionState]:
        """Fetch data from IoT Open.

        Strategy:
          1. Get FunctionX list for the installation.
          2. Filter out functions that are explicitly hidden/disabled for HA.
          3. Collect all `topic_read` from function.meta.
          4. Query Status for those topics.
          5. Map latest value per topic into IoTOpenFunctionState.
        """
        # ------------------------------------------------------------------
        # 1. List FunctionX
        # ------------------------------------------------------------------
        try:
            functionx_raw = await self._api.async_list_functionx(
                installation_id=self._installation_id
            )
        except IoTOpenApiError as err:
            raise UpdateFailed(f"Failed to fetch FunctionX: {err}") from err

        total_functions = len(functionx_raw)
        topics: list[str] = []
        function_by_topic: Dict[str, Mapping[str, Any]] = {}
        skipped_hidden = 0
        skipped_no_topic = 0

        for item in functionx_raw:
            meta = item.get("meta") or {}

            if not is_exposed_to_ha(meta):
                skipped_hidden += 1
                continue

            topic = meta.get("topic_read")
            if not topic:
                skipped_no_topic += 1
                continue

            topics.append(topic)
            function_by_topic[topic] = item

        _LOGGER.debug(
            (
                "IoT Open coordinator(%s): %d FunctionX total, %d exposed, "
                "%d hidden/disabled, %d without topic_read"
            ),
            self._installation_id,
            total_functions,
            len(function_by_topic),
            skipped_hidden,
            skipped_no_topic,
        )

        # ------------------------------------------------------------------
        # 2. Fetch latest status per topic (if any topics exist)
        # ------------------------------------------------------------------
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

            _LOGGER.debug(
                "IoT Open coordinator(%s): received status for %d topics",
                self._installation_id,
                len(status_by_topic),
            )
        else:
            _LOGGER.debug(
                "IoT Open coordinator(%s): no topics to query (no exposed FunctionX with topic_read)",
                self._installation_id,
            )

        # ------------------------------------------------------------------
        # 3. Build IoTOpenFunctionState objects
        # ------------------------------------------------------------------
        result: Dict[int, IoTOpenFunctionState] = {}

        for topic, func in function_by_topic.items():
            func_id = int(func.get("id"))
            meta = func.get("meta") or {}
            status = status_by_topic.get(topic)

            device_id = _parse_device_id(meta.get("device_id"))

            result[func_id] = IoTOpenFunctionState(
                function_id=func_id,
                installation_id=int(
                    func.get("installation_id", self._installation_id)
                ),
                type=str(func.get("type", "")),
                name=str(meta.get("name") or f"Function {func_id}"),
                topic_read=topic,
                last_value=None if status is None else status.get("value"),
                last_timestamp=None if status is None else status.get("timestamp"),
                device_id=device_id,
                meta=meta,
            )

        _LOGGER.debug(
            "IoT Open coordinator(%s): %d functions with status after filtering",
            self._installation_id,
            len(result),
        )

        return result
