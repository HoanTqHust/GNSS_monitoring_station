from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict

from config import config


LOGGER = logging.getLogger("telemetry.mqtt_subscriber")


@dataclass(frozen=True)
class MqttSubscribeSettings:
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    client_id: str
    qos: int
    keepalive_s: int
    subscribe_timeout_s: float

    @classmethod
    def from_config(cls, app_config: Any, component: str) -> "MqttSubscribeSettings":
        client_prefix = str(getattr(app_config, "MQTT_CLIENT_ID_PREFIX", "gnss-subscriber"))
        return cls(
            enabled=bool(getattr(app_config, "MQTT_ENABLED", False)),
            host=str(getattr(app_config, "MQTT_HOST", "localhost")),
            port=int(getattr(app_config, "MQTT_PORT", 1883)),
            username=str(getattr(app_config, "MQTT_USERNAME", "")),
            password=str(getattr(app_config, "MQTT_PASSWORD", "")),
            client_id=f"{client_prefix}-{component}-cmd",
            qos=int(getattr(app_config, "MQTT_QOS", 1)),
            keepalive_s=int(getattr(app_config, "MQTT_KEEPALIVE_S", 60)),
            subscribe_timeout_s=float(getattr(app_config, "MQTT_SUBSCRIBE_TIMEOUT_S", 2.0)),
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
        if self.subscribe_timeout_s <= 0:
            raise ValueError("MQTT_SUBSCRIBE_TIMEOUT_S must be positive")


CommandHandler = Callable[[Dict[str, Any], Any], Any]


@dataclass
class CommandContext:
    site_id: str
    device_id: str
    topic_prefix: str
    mqtt_publisher: Any
    realtime_pipeline: Any
    pipeline_status: dict[str, Any] = field(default_factory=dict)
    pipeline_lock: threading.Lock = field(default_factory=threading.Lock)


class UbloxCommandHandler:
    def __init__(
        self,
        context: CommandContext,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ctx = context
        self._logger = logger or LOGGER

    def handle_configure(self, command: dict[str, Any]) -> dict[str, Any]:
        params = command.get("data", {}).get("params", {})
        errors: list[str] = []

        with self._ctx.pipeline_lock:
            if "detectors" in params:
                detectors = params["detectors"]
                if "sos_carrier" in detectors:
                    value = detectors["sos_carrier"].get("threshold")
                    if value is not None:
                        self._ctx.realtime_pipeline.set_threshold("sos_carrier", float(value))
                if "sos_smoothed_pseudorange" in detectors:
                    value = detectors["sos_smoothed_pseudorange"].get("threshold")
                    if value is not None:
                        self._ctx.realtime_pipeline.set_threshold("sos_smoothed_pseudorange", float(value))
                if "d3_carrier" in detectors:
                    value = detectors["d3_carrier"].get("threshold")
                    if value is not None:
                        self._ctx.realtime_pipeline.set_threshold("d3_carrier", float(value))
                if "d3_smoothed_pseudorange" in detectors:
                    value = detectors["d3_smoothed_pseudorange"].get("threshold")
                    if value is not None:
                        self._ctx.realtime_pipeline.set_threshold("d3_smoothed_pseudorange", float(value))

            if "reference_svid" in params:
                value = params["reference_svid"]
                if value is not None:
                    self._ctx.realtime_pipeline.set_reference_svid(int(value))

            if "min_sat_count" in params:
                value = params["min_sat_count"]
                if value is not None:
                    self._ctx.realtime_pipeline.set_min_sat_count(int(value))

        if errors:
            return {"status": "error", "errors": errors}

        self._logger.info("ublox_configure_applied params=%s", params)
        return {
            "status": "applied",
            "applied": list(params.keys()),
        }

    def handle_restart(self, command: dict[str, Any]) -> dict[str, Any]:
        scope = command.get("data", {}).get("params", {}).get("scope", "pipeline")
        self._logger.info("ublox_restart_requested scope=%s", scope)

        with self._ctx.pipeline_lock:
            self._ctx.realtime_pipeline.reset()
            self._ctx.pipeline_status["status"] = "running"

        self._logger.info("ublox_restart_completed scope=%s", scope)
        return {"status": "completed", "scope": scope}

    def handle_start(self, command: dict[str, Any]) -> dict[str, Any]:
        mode = command.get("data", {}).get("params", {}).get("mode", "realtime")
        self._logger.info("ublox_start_requested mode=%s", mode)

        with self._ctx.pipeline_lock:
            if self._ctx.pipeline_status.get("status") == "running":
                return {"status": "no_change", "reason": "already_running"}
            self._ctx.pipeline_status["status"] = "running"

        return {"status": "started", "mode": mode}

    def handle_stop(self, command: dict[str, Any]) -> dict[str, Any]:
        reason = command.get("data", {}).get("params", {}).get("reason", "user_requested")
        self._logger.info("ublox_stop_requested reason=%s", reason)

        with self._ctx.pipeline_lock:
            if self._ctx.pipeline_status.get("status") == "stopped":
                return {"status": "no_change", "reason": "already_stopped"}
            self._ctx.pipeline_status["status"] = "stopped"

        return {"status": "stopped", "reason": reason}

    def handle_status(self, command: dict[str, Any]) -> dict[str, Any]:
        del command
        with self._ctx.pipeline_lock:
            status = dict(self._ctx.pipeline_status)
            if self._ctx.realtime_pipeline is not None:
                status["config"] = self._ctx.realtime_pipeline.get_current_config()
            else:
                status["config"] = {}
        return {"status": status}


class MqttCommandSubscriber:
    _HANDLERS: dict[str, str] = {
        # Legacy one-level command types.
        "reboot": "handle_restart",
        "set_rate": "handle_configure",
        "start": "handle_start",
        "stop": "handle_stop",
        "status": "handle_status",
        # Nested ublox command types.
        "ublox/configure": "handle_configure",
        "ublox/restart": "handle_restart",
        "ublox/start": "handle_start",
        "ublox/stop": "handle_stop",
        "ublox/status": "handle_status",
    }

    def __init__(
        self,
        settings: MqttSubscribeSettings,
        context: CommandContext,
        client_factory: Callable[[], Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings
        self._context = context
        self._client_factory = client_factory or self._create_paho_client
        self._client: Any = None
        self._lock = threading.Lock()
        self._logger = logger or LOGGER
        self._running = False
        self._command_handler = UbloxCommandHandler(context, self._logger)
        self._processed_ids: set[str] = set()
        self._processed_ids_lock = threading.Lock()

        try:
            self.settings.validate()
        except ValueError as exc:
            self._logger.error("mqtt_subscriber_config_invalid error=%s", exc)
            self._settings_valid = False
        else:
            self._settings_valid = True

    def start(self) -> None:
        if not self.settings.enabled:
            self._logger.debug("mqtt_subscriber_disabled")
            return
        if not self._settings_valid:
            self._logger.warning("mqtt_subscriber_config_invalid_skipping")
            return

        with self._lock:
            if self._running:
                return
            try:
                client = self._ensure_client()
                topics = self._build_command_topics()
                for topic in topics:
                    client.subscribe(topic, qos=self.settings.qos)
                self._logger.info(
                    "mqtt_subscriber_started topics=%s qos=%s",
                    topics,
                    self.settings.qos,
                )
                self._running = True
            except Exception:
                self._logger.exception("mqtt_subscriber_start_error")

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            try:
                if self._client is not None:
                    self._client.loop_stop()
                    self._client.disconnect()
                    self._client = None
                self._running = False
                self._logger.info("mqtt_subscriber_stopped")
            except Exception:
                self._logger.exception("mqtt_subscriber_stop_error")

    def _build_command_topics(self) -> list[str]:
        base_parts = [
            self._context.topic_prefix.strip("/"),
            self._context.site_id.strip("/"),
            self._context.device_id.strip("/"),
            "cmd",
        ]
        base = "/".join(base_parts)
        # Support both one-level command_type (`cmd/reboot/v1`) and nested
        # command_type (`cmd/ublox/configure/v1`) shapes.
        return [f"{base}/+/v1", f"{base}/+/+/v1"]

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        del client, userdata
        topic_parts = msg.topic.strip("/").split("/")
        if len(topic_parts) >= 6 and topic_parts[3] == "cmd" and topic_parts[-1] == "v1":
            command_type = "/".join(topic_parts[4:-1])
            if command_type in {"init", "ack"}:
                self._logger.debug("mqtt_subscriber_skip_internal_command topic=%s", msg.topic)
                return

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._logger.warning("mqtt_subscriber_invalid_json topic=%s", msg.topic)
            return

        try:
            command_data = payload.get("data", {})
            command_id = command_data.get("command_id") or payload.get("event_id")
            if not command_id:
                self._logger.warning("mqtt_subscriber_missing_command_id topic=%s", msg.topic)
                return

            with self._processed_ids_lock:
                if command_id in self._processed_ids:
                    self._logger.debug("mqtt_subscriber_duplicate command_id=%s", command_id)
                    return
                self._processed_ids.add(command_id)
                if len(self._processed_ids) > 10000:
                    self._processed_ids.clear()

            result = self._dispatch_command(msg.topic, payload)
            self._publish_ack(command_id, result)

        except Exception:
            self._logger.exception("mqtt_subscriber_handler_error topic=%s", msg.topic)

    def _dispatch_command(self, topic: str, command: dict[str, Any]) -> dict[str, Any]:
        topic_parts = topic.strip("/").split("/")
        if len(topic_parts) < 6 or topic_parts[3] != "cmd" or topic_parts[-1] != "v1":
            self._logger.warning("mqtt_subscriber_invalid_command_topic topic=%s", topic)
            return {"status": "error", "reason": f"invalid_command_topic:{topic}"}

        command_type = "/".join(topic_parts[4:-1])
        if not command_type:
            self._logger.warning("mqtt_subscriber_invalid_command_type topic=%s", topic)
            return {"status": "error", "reason": f"invalid_command_type:{topic}"}

        handler_name = self._HANDLERS.get(command_type)
        if not handler_name:
            self._logger.warning("mqtt_subscriber_unknown_command_type type=%s", command_type)
            return {"status": "error", "reason": f"unknown_command_type:{command_type}"}

        handler = getattr(self._command_handler, handler_name, None)
        if not handler:
            self._logger.error("mqtt_subscriber_handler_missing handler=%s", handler_name)
            return {"status": "error", "reason": f"handler_not_found:{handler_name}"}

        return handler(command)

    def _publish_ack(self, command_id: str, result: dict[str, Any]) -> None:
        try:
            from telemetry.mqtt_schema import build_ack_message

            topic, message = build_ack_message(
                topic_prefix=self._context.topic_prefix,
                site_id=self._context.site_id,
                device_id=self._context.device_id,
                acknowledged=[command_id],
                extra_data=result,
            )
            self._context.mqtt_publisher.publish(topic, message)
            self._logger.info(
                "cmd_ack_published topic=%s command_id=%s event_id=%s",
                topic,
                command_id,
                message.get("event_id"),
            )
        except Exception:
            self._logger.exception("mqtt_ack_publish_error command_id=%s", command_id)

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        client = self._client_factory()
        client.on_message = self._on_message
        client.username_pw_set(self.settings.username, self.settings.password)
        rc = int(client.connect(self.settings.host, self.settings.port, self.settings.keepalive_s))
        if rc != 0:
            raise ConnectionError(f"MQTT connect failed rc={rc}")
        client.loop_start()
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


class SharedPipelineState:
    _instance: "SharedPipelineState | None" = None

    def __init__(self) -> None:
        self.pipeline_status: dict[str, Any] = {"status": "running"}
        self.realtime_pipeline: Any = None
        self.lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "SharedPipelineState":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_context(self, mqtt_publisher: Any) -> CommandContext:
        return CommandContext(
            site_id=config.MQTT_SITE_ID,
            device_id=config.MQTT_DEVICE_ID,
            topic_prefix=config.MQTT_TOPIC_PREFIX,
            mqtt_publisher=mqtt_publisher,
            realtime_pipeline=self.realtime_pipeline,
            pipeline_status=self.pipeline_status,
            pipeline_lock=self.lock,
        )
