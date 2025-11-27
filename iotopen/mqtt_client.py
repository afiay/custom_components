# SPDX-License-Identifier: MIT
# custom_components/iotopen/mqtt_client.py

"""Small async MQTT client for the IoT Open integration."""

from __future__ import annotations

from typing import Optional
import ssl
import logging

from asyncio_mqtt import Client as MqttClient, MqttError

_LOGGER = logging.getLogger(__name__)


class IoTOpenMqttClient:
    """Very small helper that connects, publishes, disconnects.

    We intentionally do not maintain a permanent connection here to keep the
    integration simple and stateless. For typical home usage the overhead is
    negligible.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tls: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._tls = tls

    async def async_publish(
        self,
        topic: str,
        payload: str,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        """Connect, publish, disconnect."""

        if not topic:
            _LOGGER.warning("IoT Open MQTT: empty topic, skipping publish")
            return

        kwargs = {}
        if self._tls:
            # Simple default TLS context – can be extended if needed.
            kwargs["tls_context"] = ssl.create_default_context()

        try:
            async with MqttClient(
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                **kwargs,
            ) as client:
                _LOGGER.debug(
                    "IoT Open MQTT: publishing to %s: %s (qos=%s retain=%s)",
                    topic,
                    payload,
                    qos,
                    retain,
                )
                await client.publish(topic, payload, qos=qos, retain=retain)
        except MqttError as err:
            _LOGGER.error(
                "IoT Open MQTT: failed to publish to %s: %s", topic, err
            )
