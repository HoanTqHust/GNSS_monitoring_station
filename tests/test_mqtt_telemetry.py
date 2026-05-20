import json
import unittest

from telemetry.mqtt_publisher import MqttPublishSettings, MqttTelemetryPublisher
from telemetry.mqtt_subscriber import CommandContext, MqttCommandSubscriber, MqttSubscribeSettings
from telemetry.mqtt_schema import (
    build_detect_epoch_message,
    build_health_message,
    build_position_state_message,
    build_raw_ublox_message,
)


class FakeSat:
    def __init__(self, gnss_id, sv_id, sig_id, cno):
        self.gnssId = gnss_id
        self.svId = sv_id
        self.sigId = sig_id
        self.cno = cno


class FakeRawx:
    def __init__(self):
        self.rcvTow = 123456.0
        self.week = 2415
        self.satData = [
            FakeSat(0, 16, 0, 48.0),
            FakeSat(6, 8, 0, 32.0),
        ]


class FakeRawxSecond:
    def __init__(self):
        self.rcvTow = 123456.0
        self.week = 2415
        self.satData = [
            FakeSat(0, 16, 0, 50.0),
        ]


class FakeNav:
    lat = 210055000
    lon = 1058445000
    height = 12300
    fixType = 3
    pDOP = 163


class FakePublishInfo:
    rc = 0

    def __init__(self):
        self.wait_called = False

    def wait_for_publish(self, timeout=None):
        self.wait_called = True

    def is_published(self):
        return True


class FakeClient:
    def __init__(self):
        self.username = None
        self.password = None
        self.connected = None
        self.published = []
        self.loop_started = False
        self.last_publish_info = None

    def username_pw_set(self, username, password):
        self.username = username
        self.password = password

    def connect(self, host, port, keepalive):
        self.connected = (host, port, keepalive)
        return 0

    def loop_start(self):
        self.loop_started = True

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append(
            {
                "topic": topic,
                "payload": payload,
                "qos": qos,
                "retain": retain,
            }
        )
        info = FakePublishInfo()
        self.last_publish_info = info
        return info

    def subscribe(self, topic, qos=0):
        self.published.append({"topic": topic, "qos": qos, "subscribe": True})
        return (0, 1)


class FakeAckPublisher:
    def __init__(self):
        self.calls = []

    def publish(self, topic, message, **kwargs):
        self.calls.append({"topic": topic, "message": message, "kwargs": kwargs})
        return True


class FakeIncomingMessage:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


class MqttTelemetrySchemaTests(unittest.TestCase):
    def test_build_raw_ublox_message(self):
        event = {
            "seq": 7,
            "created_at_utc": "2026-04-22T03:29:36.125+00:00",
            "payload": {
                "receiver": "rx1",
                "identity": "RXM-RAWX",
                "tow_s": 123456.0,
                "raw_len": 3,
                "raw_base64": "AQID",
            },
        }

        topic, message = build_raw_ublox_message(
            event,
            topic_prefix="gnss",
            site_id="lab_hanoi",
            device_id="ducanh_user",
        )

        self.assertEqual(topic, "gnss/lab_hanoi/ducanh_user/raw/ublox/v1")
        self.assertEqual(message["schema"], "gnss.raw.ublox.v1")
        self.assertEqual(message["event_id"], "ducanh_user-000000000007")
        self.assertEqual(message["source"], "rx1")
        self.assertEqual(message["event_time"], "2026-04-22T03:29:36.125Z")
        self.assertEqual(message["data"]["raw_encoding"], "base64")
        self.assertEqual(message["data"]["raw_base64"], "AQID")

    def test_build_detect_epoch_message(self):
        event = {
            "seq": 8,
            "created_at_utc": "2026-04-22T03:29:36.125+00:00",
            "payload": {
                "received_at_utc": "2026-04-22T03:29:36.125+00:00",
                "tow_s": 123456.0,
                "rawx_1": FakeRawx(),
                "rawx_2": FakeRawxSecond(),
                "nav_1": FakeNav(),
                "nav_2": None,
            },
        }
        realtime_outputs = {
            "sos_carrier": {
                "detector_name": "sos",
                "measurement_name": "carrier",
                "score": 0.0123,
                "threshold": 0.09,
                "spoofing": True,
                "reference_svid": 3,
                "visible_svids": [3, 16],
                "suspect_svids": [16],
            }
        }

        topic, message = build_detect_epoch_message(
            event,
            realtime_outputs,
            topic_prefix="gnss",
            site_id="lab_hanoi",
            device_id="ducanh_user",
        )
        position_topic, position_message = build_position_state_message(message, topic_prefix="gnss")

        self.assertEqual(topic, "gnss/lab_hanoi/ducanh_user/detect/epoch/v1")
        self.assertEqual(message["schema"], "gnss.detect.epoch.v1")
        self.assertEqual(message["data"]["time"]["gps_week"], 2415)
        self.assertAlmostEqual(message["data"]["position"]["lat_deg"], 21.0055)
        self.assertAlmostEqual(message["data"]["position"]["lon_deg"], 105.8445)
        self.assertEqual(message["data"]["position"]["height_m"], 12.3)
        self.assertEqual(message["data"]["position"]["fix_type"], "3d")
        self.assertEqual(message["data"]["position"]["pdop"], 1.63)
        self.assertEqual(message["data"]["summary"]["status"], "spoofed")
        self.assertTrue(message["data"]["summary"]["spoofing"])
        self.assertEqual(message["data"]["summary"]["sat_count"], 2)
        self.assertAlmostEqual(message["data"]["summary"]["avg_cno_dbhz"], 40.5)
        self.assertEqual(message["data"]["signals"][0]["prn"], "R08")
        self.assertEqual(message["data"]["signals"][1]["prn"], "G16")
        self.assertEqual(message["data"]["signals"][1]["receiver_ids"], ["rx1", "rx2"])
        self.assertEqual(position_topic, "gnss/lab_hanoi/ducanh_user/state/position/v1")
        self.assertEqual(position_message["schema"], "gnss.state.position.v1")

    def test_build_health_message_includes_mqtt_metrics(self):
        topic, message = build_health_message(
            {
                "ingress_backlog": 0,
                "detect_backlog": 1,
                "raw_backlog": 2,
                "ingress_dropped": 0,
                "detect_dropped": 0,
                "raw_dropped": 1,
                "raw_emitted": 10,
                "unknown_events": 0,
                "last_seq": 12,
                "mqtt_raw_published": 8,
                "mqtt_raw_failed": 1,
                "mqtt_raw_queue_dropped": 3,
                "mqtt_detect_published": 2,
                "mqtt_detect_failed": 0,
                "mqtt_position_published": 2,
                "mqtt_position_failed": 0,
                "mqtt_health_published": 1,
                "mqtt_health_failed": 0,
            },
            topic_prefix="gnss",
            site_id="lab_hanoi",
            device_id="ducanh_user",
            seq=12,
            cpu_percent=35.4,
        )

        self.assertEqual(topic, "gnss/lab_hanoi/ducanh_user/health/v1")
        self.assertEqual(message["schema"], "gnss.health.v1")
        self.assertEqual(message["event_id"], "ducanh_user-000000000012-health")
        self.assertEqual(message["data"]["status"], "degraded")
        self.assertEqual(message["data"]["mqtt_raw_published"], 8)
        self.assertEqual(message["data"]["mqtt_raw_failed"], 1)
        self.assertEqual(message["data"]["mqtt_raw_queue_dropped"], 3)
        self.assertEqual(message["data"]["cpu_percent"], 35.4)


class MqttTelemetryPublisherTests(unittest.TestCase):
    def test_publish_uses_qos_1_and_credentials(self):
        fake_client = FakeClient()
        settings = MqttPublishSettings(
            enabled=True,
            host="localhost",
            port=1883,
            username="rw_user",
            password="secret",
            client_id="test-client",
            qos=1,
            keepalive_s=60,
            publish_timeout_s=1.0,
        )
        publisher = MqttTelemetryPublisher(settings, client_factory=lambda: fake_client)

        published = publisher.publish("test/topic", {"schema": "test.v1", "data": {"ok": True}})

        self.assertTrue(published)
        self.assertEqual(fake_client.username, "rw_user")
        self.assertEqual(fake_client.password, "secret")
        self.assertEqual(fake_client.connected, ("localhost", 1883, 60))
        self.assertTrue(fake_client.loop_started)
        self.assertEqual(fake_client.published[0]["topic"], "test/topic")
        self.assertEqual(fake_client.published[0]["qos"], 1)
        self.assertFalse(fake_client.published[0]["retain"])
        self.assertTrue(fake_client.last_publish_info.wait_called)
        self.assertTrue(json.loads(fake_client.published[0]["payload"])["data"]["ok"])

    def test_publish_can_skip_wait_for_ack(self):
        fake_client = FakeClient()
        settings = MqttPublishSettings(
            enabled=True,
            host="localhost",
            port=1883,
            username="rw_user",
            password="secret",
            client_id="test-client",
            qos=1,
            keepalive_s=60,
            publish_timeout_s=1.0,
        )
        publisher = MqttTelemetryPublisher(settings, client_factory=lambda: fake_client)

        published = publisher.publish(
            "test/topic",
            {"schema": "test.v1", "data": {"ok": True}},
            wait_for_ack=False,
        )

        self.assertTrue(published)
        self.assertFalse(fake_client.last_publish_info.wait_called)


class MqttSubscribeSettingsTests(unittest.TestCase):
    def test_validate_accepts_valid_settings(self):
        settings = MqttSubscribeSettings(
            enabled=True,
            host="localhost",
            port=1883,
            username="rw_user",
            password="secret",
            client_id="sub-client",
            qos=1,
            keepalive_s=60,
            subscribe_timeout_s=2.0,
        )
        settings.validate()


class MqttCommandSubscriberTopicTests(unittest.TestCase):
    def _build_subscriber(self) -> MqttCommandSubscriber:
        settings = MqttSubscribeSettings(
            enabled=False,
            host="localhost",
            port=1883,
            username="rw_user",
            password="secret",
            client_id="sub-client",
            qos=1,
            keepalive_s=60,
            subscribe_timeout_s=2.0,
        )
        ack_publisher = FakeAckPublisher()
        context = CommandContext(
            site_id="lab_hanoi",
            device_id="test_device",
            topic_prefix="gnss",
            mqtt_publisher=ack_publisher,
            realtime_pipeline=None,
        )
        subscriber = MqttCommandSubscriber(settings=settings, context=context)
        subscriber._ack_publisher = ack_publisher
        return subscriber

    def test_build_command_topics_matches_readme_shape(self):
        subscriber = self._build_subscriber()
        topics = subscriber._build_command_topics()
        self.assertEqual(
            topics,
            [
                "gnss/lab_hanoi/test_device/cmd/+/v1",
                "gnss/lab_hanoi/test_device/cmd/+/+/v1",
            ],
        )

    def test_dispatch_parses_nested_command_type(self):
        subscriber = self._build_subscriber()

        class DummyHandler:
            def handle_configure(self, command):
                self.last_command = command
                return {"status": "applied"}

        subscriber._command_handler = DummyHandler()
        result = subscriber._dispatch_command(
            "gnss/lab_hanoi/test_device/cmd/ublox/configure/v1",
            {"data": {"command_id": "cmd1"}},
        )
        self.assertEqual(result["status"], "applied")

    def test_dispatch_parses_one_level_command_type(self):
        subscriber = self._build_subscriber()

        class DummyHandler:
            def handle_restart(self, command):
                self.last_command = command
                return {"status": "completed"}

        subscriber._command_handler = DummyHandler()
        result = subscriber._dispatch_command(
            "gnss/lab_hanoi/test_device/cmd/reboot/v1",
            {"data": {"command_id": "cmd1"}},
        )
        self.assertEqual(result["status"], "completed")

    def test_dispatch_rejects_invalid_topic_shape(self):
        subscriber = self._build_subscriber()
        result = subscriber._dispatch_command(
            "gnss/lab_hanoi/test_device/command/reboot/v1",
            {"data": {"command_id": "cmd1"}},
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("invalid_command_topic", result["reason"])

    def test_on_message_fallbacks_command_id_from_event_id(self):
        subscriber = self._build_subscriber()

        class DummyHandler:
            def handle_restart(self, command):
                self.last_command = command
                return {"status": "completed"}

        subscriber._command_handler = DummyHandler()
        payload = {
            "event_id": "server-evt-1",
            "data": {
                "command_type": "reboot",
                "params": {"scope": "pipeline"},
            },
        }
        msg = FakeIncomingMessage(
            "gnss/lab_hanoi/test_device/cmd/reboot/v1",
            json.dumps(payload).encode("utf-8"),
        )
        subscriber._on_message(None, None, msg)

        self.assertEqual(len(subscriber._ack_publisher.calls), 1)
        ack = subscriber._ack_publisher.calls[0]["message"]
        self.assertEqual(ack["data"]["acknowledged"], ["server-evt-1"])

    def test_on_message_skips_cmd_ack_topic(self):
        subscriber = self._build_subscriber()
        payload = {
            "event_id": "test-device-cmd-ack-1",
            "data": {
                "acknowledged": ["server-cmd-1"],
            },
        }
        msg = FakeIncomingMessage(
            "gnss/lab_hanoi/test_device/cmd/ack/v1",
            json.dumps(payload).encode("utf-8"),
        )
        subscriber._on_message(None, None, msg)
        self.assertEqual(len(subscriber._ack_publisher.calls), 0)

    def test_on_message_skips_cmd_init_topic(self):
        subscriber = self._build_subscriber()
        payload = {
            "event_id": "test-device-cmd-init-1",
            "data": {
                "ready": True,
            },
        }
        msg = FakeIncomingMessage(
            "gnss/lab_hanoi/test_device/cmd/init/v1",
            json.dumps(payload).encode("utf-8"),
        )
        subscriber._on_message(None, None, msg)
        self.assertEqual(len(subscriber._ack_publisher.calls), 0)


if __name__ == "__main__":
    unittest.main()
