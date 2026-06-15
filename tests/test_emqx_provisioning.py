import os
import tempfile
import unittest

from scripts.provision_emqx_device import (
    EmqxApiConfig,
    EmqxApiClient,
    ProvisioningError,
    build_user_collection_path,
    build_user_path,
    provision_device_user,
    upsert_env_file,
)


class FakeEmqxClient:
    def __init__(self, responses):
        self.config = EmqxApiConfig(
            base_url="http://emqx.local:18083",
            api_key="api-key",
            api_secret="api-secret",
        )
        self._responses = list(responses)
        self.calls = []

    def request_json(self, method, path, payload=None):
        self.calls.append({"method": method, "path": path, "payload": payload})
        if not self._responses:
            raise AssertionError("unexpected request")
        return self._responses.pop(0)


class EmqxProvisioningPathTests(unittest.TestCase):
    def test_user_paths_encode_authenticator_id_and_user_id(self):
        self.assertEqual(
            build_user_collection_path("password_based:built_in_database"),
            "/api/v5/authentication/password_based%3Abuilt_in_database/users",
        )
        self.assertEqual(
            build_user_path("password_based:built_in_database", "device_abcd"),
            "/api/v5/authentication/password_based%3Abuilt_in_database/users/device_abcd",
        )


class EmqxProvisioningFlowTests(unittest.TestCase):
    def test_create_user_when_missing(self):
        client = FakeEmqxClient([(404, {"code": "NOT_FOUND"}), (201, {"user_id": "device_abcd"})])

        action = provision_device_user(
            client,
            device_id="device_abcd",
            password="secret",
        )

        self.assertEqual(action, "created")
        self.assertEqual(client.calls[0]["method"], "GET")
        self.assertEqual(client.calls[1]["method"], "POST")
        self.assertEqual(
            client.calls[1]["payload"],
            {"user_id": "device_abcd", "password": "secret", "is_superuser": False},
        )

    def test_existing_user_requires_update_flag(self):
        client = FakeEmqxClient([(200, {"user_id": "device_abcd"})])

        with self.assertRaises(ProvisioningError):
            provision_device_user(client, device_id="device_abcd", password="secret")

        self.assertEqual(len(client.calls), 1)

    def test_update_existing_user(self):
        client = FakeEmqxClient([(200, {"user_id": "device_abcd"}), (204, {})])

        action = provision_device_user(
            client,
            device_id="device_abcd",
            password="new-secret",
            update_existing=True,
        )

        self.assertEqual(action, "updated")
        self.assertEqual(client.calls[1]["method"], "PUT")
        self.assertEqual(client.calls[1]["payload"]["password"], "new-secret")


class EnvFileUpdateTests(unittest.TestCase):
    def test_upsert_env_file_updates_known_keys_and_preserves_other_lines(self):
        with tempfile.TemporaryDirectory() as root:
            env_path = os.path.join(root, ".env")
            with open(env_path, "w", encoding="utf-8") as env_file:
                env_file.write("# existing\n")
                env_file.write("MQTT_HOST=gnss.soict.io\n")
                env_file.write("MQTT_DEVICE_ID=device_old\n")
                env_file.write("MQTT_USERNAME=device_old\n")

            upsert_env_file(
                env_path,
                {
                    "MQTT_DEVICE_ID": "device_abcd",
                    "MQTT_USERNAME": "device_abcd",
                    "MQTT_PASSWORD": "secret value",
                },
            )

            with open(env_path, "r", encoding="utf-8") as env_file:
                content = env_file.read()

            self.assertIn("# existing\n", content)
            self.assertIn("MQTT_HOST=gnss.soict.io\n", content)
            self.assertIn("MQTT_DEVICE_ID=device_abcd\n", content)
            self.assertIn("MQTT_USERNAME=device_abcd\n", content)
            self.assertIn('MQTT_PASSWORD="secret value"\n', content)


class EmqxApiConfigTests(unittest.TestCase):
    def test_config_validation_rejects_missing_credentials(self):
        with self.assertRaises(ValueError):
            EmqxApiConfig(
                base_url="http://emqx.local:18083",
                api_key="",
                api_secret="secret",
            ).validate()

    def test_client_can_be_constructed_with_valid_config(self):
        client = EmqxApiClient(
            EmqxApiConfig(
                base_url="http://emqx.local:18083",
                api_key="api-key",
                api_secret="api-secret",
            )
        )
        self.assertEqual(client.config.authenticator_id, "password_based:built_in_database")


if __name__ == "__main__":
    unittest.main()
