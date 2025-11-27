# SPDX-License-Identifier: MIT
# custom_components/iotopen/api.py

"""Async API client for IoT Open Lynx."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

import asyncio
import logging

from aiohttp import ClientError, ClientSession
from yarl import URL

from .const import (
    PATH_FUNCTIONX_LIST,
    PATH_FUNCTIONX_ITEM,
    PATH_FUNCTIONX_META,
    PATH_DEVICEX_LIST,
    PATH_DEVICEX_ITEM,
    PATH_DEVICEX_META,
    PATH_STATUS,
)

_LOGGER = logging.getLogger(__name__)


class IoTOpenApiError(RuntimeError):
    """Raised when IoT Open API returns an error."""


class IoTOpenApiClient:
    """Thin async client for IoT Open API v2.

    It only implements the subset needed for this HA integration:

    - FunctionX:
        * list (installation)
        * create / get / update / delete
        * set meta key (for assigning device, naming, etc.)
    - DeviceX:
        * list (installation)
        * create / get / delete
        * set meta key
    - Status:
        * fetch latest values for topics
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        session: ClientSession,
        timeout: float = 10.0,
    ) -> None:
        self._base = URL(base_url.rstrip("/"))
        self._api_key = api_key
        self._session = session
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API – FunctionX
    # ------------------------------------------------------------------

    async def async_list_functionx(
        self,
        installation_id: int,
    ) -> List[Mapping[str, Any]]:
        """List FunctionX objects for an installation."""
        path = PATH_FUNCTIONX_LIST.format(installation_id=installation_id)
        data = await self._async_request_json("GET", path)
        if not isinstance(data, list):
            raise IoTOpenApiError("Unexpected FunctionX list response type")
        return data

    async def async_get_function(
        self,
        installation_id: int,
        function_id: int,
    ) -> Mapping[str, Any]:
        """Get a single FunctionX object."""
        path = PATH_FUNCTIONX_ITEM.format(
            installation_id=installation_id,
            functionx_id=function_id,
        )
        data = await self._async_request_json("GET", path)
        if not isinstance(data, Mapping):
            raise IoTOpenApiError("Unexpected FunctionX get response type")
        return data

    async def async_create_function(
        self,
        installation_id: int,
        *,
        type_: str,
        meta: Mapping[str, Any],
        silent: bool | None = None,
    ) -> Mapping[str, Any]:
        """Create a FunctionX object."""
        path = PATH_FUNCTIONX_LIST.format(installation_id=installation_id)
        body = {
            "installation_id": installation_id,
            "type": type_,
            "meta": dict(meta),
        }
        params: Dict[str, str] = {}
        if silent is not None:
            params["silent"] = "true" if silent else "false"
        data = await self._async_request_json("POST", path, params=params, json=body)
        if not isinstance(data, Mapping):
            raise IoTOpenApiError("Unexpected FunctionX create response type")
        return data

    async def async_update_function(
        self,
        installation_id: int,
        function_id: int,
        *,
        type_: str,
        meta: Mapping[str, Any],
        silent: bool | None = None,
    ) -> Mapping[str, Any]:
        """Update a FunctionX object (full update)."""
        path = PATH_FUNCTIONX_ITEM.format(
            installation_id=installation_id,
            functionx_id=function_id,
        )
        body = {
            "installation_id": installation_id,
            "type": type_,
            "meta": dict(meta),
        }
        params: Dict[str, str] = {}
        if silent is not None:
            params["silent"] = "true" if silent else "false"
        data = await self._async_request_json("PUT", path, params=params, json=body)
        if not isinstance(data, Mapping):
            raise IoTOpenApiError("Unexpected FunctionX update response type")
        return data

    async def async_delete_function(
        self,
        installation_id: int,
        function_id: int,
        *,
        silent: bool | None = None,
    ) -> None:
        """Delete a FunctionX object."""
        path = PATH_FUNCTIONX_ITEM.format(
            installation_id=installation_id,
            functionx_id=function_id,
        )
        params: Dict[str, str] = {}
        if silent is not None:
            params["silent"] = "true" if silent else "false"
        await self._async_request_json("DELETE", path, params=params)

    async def async_set_function_meta(
        self,
        installation_id: int,
        function_id: int,
        meta_key: str,
        value: Any,
        *,
        protected: bool = False,
        silent: bool | None = None,
    ) -> Mapping[str, Any]:
        """Upsert a meta key for a FunctionX using the meta API."""
        path = PATH_FUNCTIONX_META.format(
            installation_id=installation_id,
            functionx_id=function_id,
            meta_key=meta_key,
        )
        params: Dict[str, str] = {}
        if silent is not None:
            params["silent"] = "true" if silent else "false"
        body = {
            "value": str(value),
            "protected": bool(protected),
        }
        data = await self._async_request_json("PUT", path, params=params, json=body)
        if not isinstance(data, Mapping):
            raise IoTOpenApiError("Unexpected FunctionX meta response type")
        return data

    # ------------------------------------------------------------------
    # Public API – DeviceX
    # ------------------------------------------------------------------

    async def async_list_devices(
        self,
        installation_id: int,
    ) -> List[Mapping[str, Any]]:
        """List DeviceX objects for an installation."""
        path = PATH_DEVICEX_LIST.format(installation_id=installation_id)
        data = await self._async_request_json("GET", path)
        if not isinstance(data, list):
            raise IoTOpenApiError("Unexpected DeviceX list response type")
        return data

    async def async_get_device(
        self,
        installation_id: int,
        device_id: int,
    ) -> Mapping[str, Any]:
        """Get a single DeviceX object."""
        path = PATH_DEVICEX_ITEM.format(
            installation_id=installation_id,
            devicex_id=device_id,
        )
        data = await self._async_request_json("GET", path)
        if not isinstance(data, Mapping):
            raise IoTOpenApiError("Unexpected DeviceX get response type")
        return data

    async def async_create_device(
        self,
        installation_id: int,
        *,
        type_: str,
        meta: Mapping[str, Any],
        silent: bool | None = None,
    ) -> Mapping[str, Any]:
        """Create a DeviceX object."""
        path = PATH_DEVICEX_LIST.format(installation_id=installation_id)
        body = {
            "installation_id": installation_id,
            "type": type_,
            "meta": dict(meta),
        }
        params: Dict[str, str] = {}
        if silent is not None:
            params["silent"] = "true" if silent else "false"
        data = await self._async_request_json("POST", path, params=params, json=body)
        if not isinstance(data, Mapping):
            raise IoTOpenApiError("Unexpected DeviceX create response type")
        return data

    async def async_delete_device(
        self,
        installation_id: int,
        device_id: int,
        *,
        silent: bool | None = None,
    ) -> None:
        """Delete a DeviceX object."""
        path = PATH_DEVICEX_ITEM.format(
            installation_id=installation_id,
            devicex_id=device_id,
        )
        params: Dict[str, str] = {}
        if silent is not None:
            params["silent"] = "true" if silent else "false"
        await self._async_request_json("DELETE", path, params=params)

    async def async_set_device_meta(
        self,
        installation_id: int,
        device_id: int,
        meta_key: str,
        value: Any,
        *,
        protected: bool = False,
        silent: bool | None = None,
    ) -> Mapping[str, Any]:
        """Upsert a meta key for a DeviceX using the meta API."""
        path = PATH_DEVICEX_META.format(
            installation_id=installation_id,
            devicex_id=device_id,
            meta_key=meta_key,
        )
        params: Dict[str, str] = {}
        if silent is not None:
            params["silent"] = "true" if silent else "false"
        body = {
            "value": str(value),
            "protected": bool(protected),
        }
        data = await self._async_request_json("PUT", path, params=params, json=body)
        if not isinstance(data, Mapping):
            raise IoTOpenApiError("Unexpected DeviceX meta response type")
        return data

    # ------------------------------------------------------------------
    # Public API – Status
    # ------------------------------------------------------------------

    async def async_get_status_for_topics(
        self,
        installation_id: int,
        topics: List[str],
    ) -> List[Mapping[str, Any]]:
        """Return status samples for given MQTT topics."""
        if not topics:
            return []

        path = PATH_STATUS.format(installation_id=installation_id)
        params = {"topics": ",".join(topics)}
        data = await self._async_request_json("GET", path, params=params)
        if not isinstance(data, list):
            raise IoTOpenApiError("Unexpected status response type")
        return data

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    async def _async_request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, str]] = None,
        json: Any | None = None,
    ) -> Any:
        url = self._base.with_path(path)
        headers = {
            "Accept": "application/json",
            "X-API-Key": self._api_key,
        }

        _LOGGER.debug(
            "IoT Open request %s %s params=%s json=%s", method, url, params, json
        )

        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    params=params,
                    json=json,
                ) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        raise IoTOpenApiError(
                            f"HTTP {resp.status} from {url}: {text}"
                        )
                    if "application/json" in resp.headers.get("Content-Type", ""):
                        return await resp.json()
                    # Some DELETE endpoints just return a message or nothing.
                    if not text:
                        return None
                    return {"text": text}
        except (ClientError, asyncio.TimeoutError) as err:
            raise IoTOpenApiError(f"Error talking to IoT Open: {err}") from err
