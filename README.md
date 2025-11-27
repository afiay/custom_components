# IoT Open – Home Assistant Integration

Custom Home Assistant integration for **IoT Open (Lynx)** that lets you:

- Connect a Lynx **installation** to Home Assistant over the REST API.
- Discover **FunctionX** as sensors (with live values via the Status API).
- Manage **DeviceX** and **FunctionX** from Home Assistant:
  - Create / delete devices.
  - Create / delete functions.
  - Assign functions to devices via `meta.device_id`.
  - Set arbitrary metadata on devices and functions (name, unit, icon, public, etc.).

The integration is designed as a conventional HA custom component and follows the official integration patterns (config flow, `DataUpdateCoordinator`, `services.yaml`, translations, etc.).   

---

## Features

### Data model

- **Installation**: One HA config entry = one IoT Open installation.
- **DeviceX**: Physical devices in IoT Open (KNX gateways, sensor hubs, controllers…).   
- **FunctionX**: Logical datapoints / functions (temperature, humidity, boolean, etc.).   
- **Status API**: Used to pull the latest values per `topic_read` and expose them as HA entities.   

### What the integration does

- Uses **IoT Open API v2** over HTTPS with `X-API-Key` authentication.
- Periodically:
  - Lists `FunctionX` for the installation.
  - Collects `meta.topic_read` for each function.
  - Fetches latest **status samples** for these topics.
  - Exposes each function as a **sensor entity** in Home Assistant.
- Groups entities:
  - If `meta.device_id` is set → entities are grouped under an IoT Open **DeviceX**.
  - Otherwise → grouped under the **Installation** device.

### Management from Home Assistant

Via HA **services** you can:

- Create / delete **DeviceX**.
- Create / delete **FunctionX**.
- Assign `FunctionX` → `DeviceX` (set `meta.device_id`).
- Set arbitrary metadata keys for **DeviceX** and **FunctionX** via the **meta API**.   

This allows you to do a lot of “platform maintenance” from HA automations or scripts.

---

## Requirements

- Home Assistant **2023.12+** (tested against dev patterns from the current docs).   
- Python environment provided by Home Assistant (no extra manual deps required).
- An IoT Open / Lynx account with:
  - Access to an **installation**.
  - A valid **API key** (`X-API-Key`) with rights to read/write DeviceX/FunctionX and Status.   

---

## Installation

### 1. File layout

Place the integration in your HA config directory as:

```text
<config>/
  custom_components/
    iotopen/
      __init__.py
      manifest.json
      const.py
      api.py
      coordinator.py
      sensor.py
      config_flow.py
      services.yaml
      translations/
        en.json
        sv.json
        de.json
        fr.json
        ar.json
