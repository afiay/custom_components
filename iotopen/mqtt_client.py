# SPDX-License-Identifier: Apache-2.0
# custom_components/iotopen/mqtt_client.py
#
# Thin, Home Assistant–friendly MQTT publisher for IoT Open.
#
# We intentionally *do not* use asyncio-mqtt here because it is tightly
# coupled to specific paho-mqtt versions and can break with the 2.x series
# that Home Assistant ships.
#
# Instead we wrap paho-mqtt directly and run the blocking parts in an
# executor / background thread so we never block HA's event loop.

from __future__ import annotations

from typing import Optional

import asyncio
import logging

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)


class IoTOpenMqttClient:
    """Small helper around paho-mqtt Client for one-way publish.

    Usage:
        mqtt_client = IoTOpenMqttClient(
            host="mqtt.example.org",
            port=8883,
            username="user",
            password="secret",
            use_tls=True,
        )
        await mqtt_client.async_publish("set/obj/zwave/usb0/node/32/switch", "1")
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = False,
        client_id: str | None = None,
        keepalive: int = 60,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._keepalive = keepalive
        self._client_id = client_id or "iotopen-ha-client"

        self._client: Optional[mqtt.Client] = None
        self._connected = asyncio.Event()
        self._connect_lock = asyncio.Lock()
        self._loop = asyncio.get_running_loop()

    # ------------------------------------------------------------------
    # Internal setup
    # ------------------------------------------------------------------

    def _ensure_client(self) -> mqtt.Client:
        """Create paho client instance (no blocking work here)."""
        if self._client is not None:
            return self._client

        # Explicit protocol to avoid surprises if HA changes default.
        client = mqtt.Client(
            client_id=self._client_id,
            protocol=mqtt.MQTTv311,
        )

        if self._username:
            client.username_pw_set(self._username, self._password)

        # IMPORTANT: we *do not* call client.tls_set() here anymore,
        # because that may load CA bundles from disk and HA will treat it
        # as a blocking call in the event loop. We do it in the executor
        # inside async_connect instead.
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect

        self._client = client
        return client

    # Callbacks run in paho’s network thread
    # type: ignore[override]
    def _on_connect(self, client: mqtt.Client, userdata, flags, rc, *_args) -> None:
        if rc == 0:
            _LOGGER.info("IoT Open MQTT: connected to %s:%s",
                         self._host, self._port)
            self._loop.call_soon_threadsafe(self._connected.set)
        else:
            _LOGGER.warning(
                "IoT Open MQTT: connect failed with rc=%s to %s:%s",
                rc,
                self._host,
                self._port,
            )

    # type: ignore[override]
    def _on_disconnect(self, client: mqtt.Client, userdata, rc, *_args) -> None:
        _LOGGER.info("IoT Open MQTT: disconnected (rc=%s)", rc)
        self._loop.call_soon_threadsafe(self._connected.clear)

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def async_connect(self) -> None:
        """Ensure the client is connected before publishing."""

        async with self._connect_lock:
            if self._client is not None and self._connected.is_set():
                return

            client = self._ensure_client()

            def _blocking_connect() -> None:
                # All potentially blocking operations (TLS + connect + loop)
                # run inside this executor thread – not on HA's event loop.
                if self._use_tls:
                    client.tls_set()  # may load CA bundles from disk
                client.connect(self._host, self._port, self._keepalive)
                client.loop_start()

            await self._loop.run_in_executor(None, _blocking_connect)

            try:
                await asyncio.wait_for(self._connected.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"Timeout connecting to MQTT broker {self._host}:{self._port}"
                )

    async def async_publish(
        self,
        topic: str,
        payload: str,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Publish a single message.

        This will connect on first use and re-use the connection.
        """
        await self.async_connect()

        assert self._client is not None

        def _blocking_publish() -> None:
            info = self._client.publish(
                topic, payload=payload, qos=qos, retain=retain)
            info.wait_for_publish()
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish failed with rc={info.rc}")

        await self._loop.run_in_executor(None, _blocking_publish)

    async def async_disconnect(self) -> None:
        """Cleanly disconnect and stop the background loop."""
        if self._client is None:
            return

        client = self._client

        def _blocking_disconnect() -> None:
            try:
                client.loop_stop()
            finally:
                try:
                    client.disconnect()
                except Exception:
                    _LOGGER.debug(
                        "IoT Open MQTT: disconnect error", exc_info=True)

        await self._loop.run_in_executor(None, _blocking_disconnect)
        self._connected.clear()
