# SPDX-License-Identifier: MIT
# custom_components/iotopen/const.py

"""Constants for the IoT Open integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "iotopen"

CONF_BASE_URL: Final = "base_url"
CONF_API_KEY: Final = "api_key"
CONF_INSTALLATION_ID: Final = "installation_id"

DEFAULT_BASE_URL: Final = "https://lynx.iotopen.se"

PLATFORMS: Final = ["sensor"]

# ---------------------------------------------------------------------------
# API endpoints (REST v2) – paths only, base URL is configurable.
# ---------------------------------------------------------------------------

# FunctionX (logical functions / signals) :contentReference[oaicite:1]{index=1}
PATH_FUNCTIONX_LIST: Final = "/api/v2/functionx/{installation_id}"
PATH_FUNCTIONX_ITEM: Final = "/api/v2/functionx/{installation_id}/{functionx_id}"
PATH_FUNCTIONX_META: Final = (
    "/api/v2/functionx/{installation_id}/{functionx_id}/meta/{meta_key}"
)

# DeviceX (physical devices) :contentReference[oaicite:2]{index=2}
PATH_DEVICEX_LIST: Final = "/api/v2/devicex/{installation_id}"
PATH_DEVICEX_ITEM: Final = "/api/v2/devicex/{installation_id}/{devicex_id}"
PATH_DEVICEX_META: Final = (
    "/api/v2/devicex/{installation_id}/{devicex_id}/meta/{meta_key}"
)

# Status (last values per topic) :contentReference[oaicite:3]{index=3}
PATH_STATUS: Final = "/api/v2/status/{installation_id}"

# Update interval in seconds
DEFAULT_UPDATE_INTERVAL: Final = 60

# ---------------------------------------------------------------------------
# Services – exposed in HA for device/function management
# ---------------------------------------------------------------------------

SERVICE_CREATE_DEVICE: Final = "create_device"
SERVICE_DELETE_DEVICE: Final = "delete_device"
SERVICE_CREATE_FUNCTION: Final = "create_function"
SERVICE_DELETE_FUNCTION: Final = "delete_function"
SERVICE_ASSIGN_FUNCTION_DEVICE: Final = "assign_function_device"

# NEW: generic metadata management services
SERVICE_SET_DEVICE_META: Final = "set_device_meta"
SERVICE_SET_FUNCTION_META: Final = "set_function_meta"
