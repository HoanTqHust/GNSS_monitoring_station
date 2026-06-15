import os
import tempfile
import unittest

os.environ["MQTT_DEVICE_ID"] = "device_abcd"
os.environ["MQTT_USERNAME"] = "device_abcd"
os.environ.setdefault("MQTT_PASSWORD", "secret")

from config import (
    _find_primary_mac_address,
    _mac_to_device_id,
    _resolve_mqtt_device_id,
    _resolve_mqtt_username,
    _validate_device_id,
    _validate_topic_segment,
)
from telemetry.mqtt_publisher import MqttPublishSettings
from telemetry.mqtt_subscriber import MqttSubscribeSettings


class MqttDeviceIdentityTests(unittest.TestCase):
    def _write_interface_mac(self, root, interface_name, mac_address):
        interface_dir = os.path.join(root, interface_name)
        os.makedirs(interface_dir)
        with open(os.path.join(interface_dir, "address"), "w", encoding="utf-8") as address_file:
            address_file.write(mac_address)

    def test_mac_to_device_id_uses_last_hex_characters(self):
        self.assertEqual(_mac_to_device_id("AA:BB:CC:DD:EE:FF", 4), "device_eeff")
        self.assertEqual(_mac_to_device_id("aa-bb-cc-dd-ee-ff", 8), "device_ccddeeff")

    def test_resolve_device_id_accepts_valid_env_override(self):
        self.assertEqual(
            _resolve_mqtt_device_id(env_device_id="device_a1b2", mac_address="aa:bb:cc:dd:ee:ff"),
            "device_a1b2",
        )

    def test_resolve_device_id_rejects_invalid_env_override(self):
        with self.assertRaises(ValueError):
            _resolve_mqtt_device_id(env_device_id="test_device", mac_address="aa:bb:cc:dd:ee:ff")

    def test_find_primary_mac_prefers_configured_interface(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_interface_mac(root, "eth0", "aa:bb:cc:dd:ee:01")
            self._write_interface_mac(root, "wlan0", "aa:bb:cc:dd:ee:02")

            self.assertEqual(
                _find_primary_mac_address(preferred_interface="wlan0", sys_class_net=root),
                "aabbccddee02",
            )

    def test_resolve_device_id_from_fake_sysfs(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_interface_mac(root, "lo", "00:00:00:00:00:00")
            self._write_interface_mac(root, "eth0", "12:34:56:78:9A:BC")

            self.assertEqual(
                _resolve_mqtt_device_id(
                    env_device_id=None,
                    preferred_interface="",
                    suffix_length=4,
                    sys_class_net=root,
                ),
                "device_9abc",
            )

    def test_username_must_equal_device_id(self):
        self.assertEqual(_resolve_mqtt_username(None, "device_abcd"), "device_abcd")
        self.assertEqual(_resolve_mqtt_username("device_abcd", "device_abcd"), "device_abcd")
        with self.assertRaises(ValueError):
            _resolve_mqtt_username("rw_user", "device_abcd")

    def test_topic_segments_reject_wildcards_and_slashes(self):
        self.assertEqual(_validate_topic_segment("MQTT_SITE_ID", "lab_hanoi"), "lab_hanoi")
        for value in ("lab/one", "lab+", "lab#", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _validate_topic_segment("MQTT_SITE_ID", value)

    def test_device_id_pattern_matches_acl(self):
        self.assertEqual(_validate_device_id("device_A1b2"), "device_A1b2")
        for value in ("device_abc", "device_abcdefghijkl", "device_xyz1", "test_device"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _validate_device_id(value)


class MqttClientIdTests(unittest.TestCase):
    class DummyConfig:
        MQTT_ENABLED = True
        MQTT_HOST = "localhost"
        MQTT_PORT = 1883
        MQTT_USERNAME = "device_a1b2"
        MQTT_PASSWORD = "secret"
        MQTT_DEVICE_ID = "device_a1b2"
        MQTT_CLIENT_ID_PREFIX = "double-difference-cp"
        MQTT_QOS = 1
        MQTT_KEEPALIVE_S = 60
        MQTT_PUBLISH_TIMEOUT_S = 1.0
        MQTT_SUBSCRIBE_TIMEOUT_S = 1.0

    def test_publisher_client_id_includes_device_id(self):
        settings = MqttPublishSettings.from_config(self.DummyConfig, "detect")
        self.assertEqual(settings.client_id, "double-difference-cp-device_a1b2-detect")

    def test_subscriber_client_id_includes_device_id(self):
        settings = MqttSubscribeSettings.from_config(self.DummyConfig, "detect")
        self.assertEqual(settings.client_id, "double-difference-cp-device_a1b2-detect-cmd")


if __name__ == "__main__":
    unittest.main()
