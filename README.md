# IoT Open – Home Assistant Integration

Custom Home Assistant integration for **IoT Open (Lynx)**.

This integration allows Home Assistant users (and customers with custom setups) to connect an IoT Open installation, discover data points, and manage devices and functions directly from HA.

---

## What this integration does

With this integration you can:

- Connect an **IoT Open installation** to Home Assistant via the REST API
- Discover **FunctionX** and expose them as HA entities
- Read live values via the **Status API**
- Manage IoT Open objects directly from Home Assistant:
  - Create / delete **DeviceX**
  - Create / delete **FunctionX**
  - Assign functions to devices using `meta.device_id`
  - Set arbitrary metadata on devices and functions (name, unit, icon, public, etc.)

The integration follows standard Home Assistant patterns:
- Config Flow
- `DataUpdateCoordinator`
- `services.yaml`
- Translations

---

## Data model

- **Installation**: One HA config entry equals one IoT Open installation
- **DeviceX**: Physical devices in IoT Open (gateways, controllers, hubs, etc.)
- **FunctionX**: Logical datapoints (temperature, humidity, switch, alarm, etc.)

Entities are grouped as follows:
- If `meta.device_id` is set → entity is grouped under a **DeviceX**
- Otherwise → entity is grouped under the **Installation** device

---

## How it works

- Uses **IoT Open API v2** over HTTPS with `X-API-Key`
- Periodically:
  - Lists all FunctionX for the installation
  - Reads `meta.topic_read`
  - Fetches latest samples from the Status API
  - Updates Home Assistant entities

---

## Requirements

- Home Assistant **2023.12+**
- An IoT Open / Lynx account with:
  - Access to an installation
  - A valid API key with read/write access to DeviceX, FunctionX and Status

---

## Installation

### File layout

Place the integration in your Home Assistant config directory:

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
```

Restart Home Assistant and add the integration via **Settings → Devices & Services**.

---

## Frontend & dashboard setup (optional)

### Home Assistant configuration

Add the following to your `configuration.yaml`:

```yaml
default_config:

frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

lovelace:
  mode: yaml
  resources:
    - url: /local/iotopen-unified-card.js?v=0.0.10
      type: module
  dashboards:
    iotopen-dashboard:
      mode: yaml
      title: IoT Open
      icon: mdi:cloud-braces
      show_in_sidebar: true
      filename: iotopen_dashboard.yaml

mqtt:
```

### File placement

```text
<config>/
  www/
    iotopen-unified-card.js
  iotopen_dashboard.yaml
```

---

## Example dashboard (`iotopen_dashboard.yaml`)

```yaml
title: IoT Open

views:
  - title: IoT Open Dashboard
    path: iotopen-unified
    icon: mdi:chip
    panel: true
    cards:
      - type: custom:iotopen-unified-card
        title: IoT Open
        show_device_form: true
        show_function_form: true
```

---

## Custom integrations for customers

Custom integration code is available here:

https://github.com/afiay/custom_components

This is intended as a **niche solution for customers** who run Home Assistant on their own infrastructure and want a tailored IoT Open integration.

These custom integrations:
- Are **not public**
- Do **not** appear in the official Home Assistant integration list
- Are delivered per customer need

---

## Notes

- The custom UI card and dashboard are local-only
- Not part of Home Assistant core
- Focused on correctness and HA best practices
