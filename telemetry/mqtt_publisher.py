from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable


LOGGER = logging.getLogger("telemetry.mqtt_publisher")


@dataclass(frozen=True)
class MqttPublishSettings:
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    client_id: str
    qos: int
    keepalive_s: int
    publish_timeout_s: float

    @classmethod
    def from_config(cls, app_config: Any, component: str) -> "MqttPublishSettings":
        client_prefix = str(getattr(app_config, "MQTT_CLIENT_ID_PREFIX", "gnss-publisher"))
        return cls(
            enabled=bool(getattr(app_config, "MQTT_ENABLED", False)),
            host=str(getattr(app_config, "MQTT_HOST", "localhost")),
            port=int(getattr(app_config, "MQTT_PORT", 1883)),
            username=str(getattr(app_config, "MQTT_USERNAME", "")),
            password=str(getattr(app_config, "MQTT_PASSWORD", "")),
            client_id=f"{client_prefix}-{component}",
            qos=int(getattr(app_config, "MQTT_QOS", 1)),
            keepalive_s=int(getattr(app_config, "MQTT_KEEPALIVE_S", 60)),
            publish_timeout_s=float(getattr(app_config, "MQTT_PUBLISH_TIMEOUT_S", 2.0)),
        )

    def validate(self) -> None:
        if not self.enabled:
            return
        if not self.host:
            raise ValueError("MQTT_HOST must not be empty when MQTT is enabled")
        if not (1 <= self.port <= 65535):
            raise ValueError("MQTT_PORT must be in range 1..65535")
        if not self.username:
            raise ValueError("MQTT_USERNAME must not be empty when MQTT is enabled")
        if not self.password:
            raise ValueError("MQTT_PASSWORD must not be empty when MQTT is enabled")
        if self.qos != 1:
            raise ValueError("MQTT_QOS must be 1 for this telemetry contract")
        if self.publish_timeout_s <= 0:
            raise ValueError("MQTT_PUBLISH_TIMEOUT_S must be positive")


class MqttTelemetryPublisher:
    def __init__(
        self,
        settings: MqttPublishSettings,
        client_factory: Callable[[], Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory or self._create_paho_client
        self._client = None
        self._lock = threading.Lock()
        self._logger = logger or LOGGER
        try:
            self.settings.validate()
        except ValueError as exc:
            self._logger.error("mqtt_config_invalid error=%s", exc)
            self._settings_valid = False
        else:
            self._settings_valid = True

    def publish(self, topic: str, message: dict[str, Any], *, retain: bool = False) -> bool:
        if not self.settings.enabled:
            return False
        if not self._settings_valid:
            return False
        if not topic:
            raise ValueError("topic must not be empty")
        if message is None:
            raise ValueError("message must not be None")

        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self._lock:
            try:
                client = self._ensure_client()
                info = client.publish(topic, payload, qos=self.settings.qos, retain=retain)
                rc = int(getattr(info, "rc", 0))
                if rc != 0:
                    self._logger.error(
                        "mqtt_publish_rejected topic=%s qos=%s rc=%s",
                        topic,
                        self.settings.qos,
                        rc,
                    )
                    return False
                self._wait_for_publish(info, topic)
                self._logger.debug(
                    "mqtt_publish_ok topic=%s qos=%s bytes=%s",
                    topic,
                    self.settings.qos,
                    len(payload.encode("utf-8")),
                )
                return True
            except Exception:
                self._client = None
                self._logger.exception("mqtt_publish_error topic=%s qos=%s", topic, self.settings.qos)
                return False

    def close(self) -> None:
        with self._lock:
            if self._client is None:
                return
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                self._logger.exception("mqtt_disconnect_error")
            finally:
                self._client = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        client = self._client_factory()
        client.username_pw_set(self.settings.username, self.settings.password)
        rc = int(client.connect(self.settings.host, self.settings.port, self.settings.keepalive_s))
        if rc != 0:
            raise ConnectionError(f"MQTT connect failed rc={rc}")
        client.loop_start()
        self._logger.info(
            "mqtt_connected host=%s port=%s client_id=%s qos=%s",
            self.settings.host,
            self.settings.port,
            self.settings.client_id,
            self.settings.qos,
        )
        self._client = client
        return client

    def _create_paho_client(self) -> Any:
        try:
            import paho.mqtt.client as mqtt_client
        except ImportError as exc:
            raise RuntimeError("paho-mqtt is required when MQTT_ENABLED=1") from exc

        try:
            return mqtt_client.Client(
                mqtt_client.CallbackAPIVersion.VERSION2,
                client_id=self.settings.client_id,
            )
        except (AttributeError, TypeError):
            return mqtt_client.Client(client_id=self.settings.client_id)

    def _wait_for_publish(self, info: Any, topic: str) -> None:
        wait = getattr(info, "wait_for_publish", None)
        if wait is None:
            return
        try:
            wait(timeout=self.settings.publish_timeout_s)
        except TypeError:
            wait()

        is_published = getattr(info, "is_published", None)
        if is_published is not None and not bool(is_published()):
            raise TimeoutError(f"MQTT publish timeout topic={topic}")
