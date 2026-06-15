#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from telemetry.mqtt_identity import resolve_mqtt_device_id, validate_device_id, validate_topic_segment


DEFAULT_AUTHENTICATOR_ID = "password_based:built_in_database"


class ProvisioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmqxApiConfig:
    base_url: str
    api_key: str
    api_secret: str
    authenticator_id: str = DEFAULT_AUTHENTICATOR_ID

    def validate(self) -> None:
        if not self.base_url:
            raise ValueError("EMQX_API_BASE_URL must not be empty")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("EMQX_API_BASE_URL must start with http:// or https://")
        if not self.api_key:
            raise ValueError("EMQX_API_KEY must not be empty")
        if not self.api_secret:
            raise ValueError("EMQX_API_SECRET must not be empty")
        if not self.authenticator_id:
            raise ValueError("EMQX_AUTHENTICATOR_ID must not be empty")


class EmqxApiClient:
    def __init__(self, config: EmqxApiConfig, timeout_s: float = 10.0) -> None:
        self.config = config
        self.config.validate()
        self.timeout_s = timeout_s

    def request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        url = self.config.base_url.rstrip("/") + path
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("Content-Type", "application/json")
        token = f"{self.config.api_key}:{self.config.api_secret}".encode("utf-8")
        request.add_header("Authorization", "Basic " + base64.b64encode(token).decode("ascii"))

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return response.status, _decode_json_response(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, _decode_json_response(exc.read())
        except urllib.error.URLError as exc:
            raise ProvisioningError(f"EMQX API request failed: {exc}") from exc


def _decode_json_response(raw_body: bytes) -> Dict[str, Any]:
    if not raw_body:
        return {}
    try:
        decoded = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw_body": raw_body.decode("utf-8", errors="replace")}
    if isinstance(decoded, dict):
        return decoded
    return {"data": decoded}


def build_user_collection_path(authenticator_id: str) -> str:
    encoded_id = urllib.parse.quote(authenticator_id, safe="")
    return f"/api/v5/authentication/{encoded_id}/users"


def build_user_path(authenticator_id: str, user_id: str) -> str:
    encoded_user = urllib.parse.quote(user_id, safe="")
    return f"{build_user_collection_path(authenticator_id)}/{encoded_user}"


def generate_device_password() -> str:
    return secrets.token_urlsafe(32)


def provision_device_user(
    client: EmqxApiClient,
    *,
    device_id: str,
    password: str,
    update_existing: bool = False,
) -> str:
    username = validate_device_id(device_id)
    if not password:
        raise ValueError("device MQTT password must not be empty")

    get_path = build_user_path(client.config.authenticator_id, username)
    status, body = client.request_json("GET", get_path)
    if status == 200:
        if not update_existing:
            raise ProvisioningError(
                f"EMQX user already exists: {username}. Use --update-existing to rotate/update its password."
            )
        update_payload = {
            "user_id": username,
            "password": password,
            "is_superuser": False,
        }
        update_status, update_body = client.request_json("PUT", get_path, update_payload)
        if update_status not in {200, 204}:
            raise ProvisioningError(_format_api_error("update", update_status, update_body))
        return "updated"

    if status != 404:
        raise ProvisioningError(_format_api_error("lookup", status, body))

    create_payload = {
        "user_id": username,
        "password": password,
        "is_superuser": False,
    }
    create_status, create_body = client.request_json(
        "POST",
        build_user_collection_path(client.config.authenticator_id),
        create_payload,
    )
    if create_status in {200, 201}:
        return "created"
    if create_status == 409 and update_existing:
        update_status, update_body = client.request_json("PUT", get_path, create_payload)
        if update_status in {200, 204}:
            return "updated"
        raise ProvisioningError(_format_api_error("update_after_conflict", update_status, update_body))
    raise ProvisioningError(_format_api_error("create", create_status, create_body))


def _format_api_error(action: str, status: int, body: Dict[str, Any]) -> str:
    message = body.get("message") or body.get("code") or body.get("raw_body") or body
    return f"EMQX user {action} failed status={status} message={message}"


def upsert_env_file(path: str, values: Dict[str, str]) -> None:
    if not path:
        raise ValueError("env file path must not be empty")
    normalized_values = {str(key): str(value) for key, value in values.items()}
    for key in normalized_values:
        validate_topic_segment("env key", key)

    lines = []
    seen = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as env_file:
            lines = env_file.readlines()

    updated_lines = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue
        key, _separator, _value = line.partition("=")
        key = key.strip()
        if key in normalized_values:
            updated_lines.append(f"{key}={_quote_env_value(normalized_values[key])}\n")
            seen.add(key)
        else:
            updated_lines.append(line)

    for key, value in normalized_values.items():
        if key not in seen:
            updated_lines.append(f"{key}={_quote_env_value(value)}\n")

    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, temp_path = tempfile.mkstemp(prefix=".env.", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.writelines(updated_lines)
        if os.path.exists(path):
            file_mode = stat.S_IMODE(os.stat(path).st_mode)
        else:
            file_mode = 0o600
        os.chmod(temp_path, file_mode)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def _quote_env_value(value: str) -> str:
    if value == "":
        return ""
    if any(char.isspace() or char in {'"', "'", "#"} for char in value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def resolve_cli_device_id(args: argparse.Namespace) -> str:
    return resolve_mqtt_device_id(
        env_device_id=args.device_id,
        mac_address=args.mac,
        preferred_interface=args.interface,
        suffix_length=args.suffix_length,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provision an EMQX built-in-database MQTT user for one GNSS device.",
    )
    parser.add_argument("--device-id", help="Device ID, e.g. device_a1b2. Defaults to MAC-derived ID.")
    parser.add_argument("--mac", help="MAC address used to derive device ID when --device-id is not set.")
    parser.add_argument("--interface", default="", help="Network interface used for local MAC auto-detection.")
    parser.add_argument("--suffix-length", type=int, default=4, help="MAC hex suffix length, 4..12. Default: 4.")
    parser.add_argument("--password", help="MQTT password to set. Defaults to a generated random password.")
    parser.add_argument("--update-existing", action="store_true", help="Update password if the EMQX user exists.")
    parser.add_argument("--write-env", help="Update a device .env file with MQTT_DEVICE_ID/MQTT_USERNAME/MQTT_PASSWORD.")
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("EMQX_API_BASE_URL", "http://localhost:18083"),
        help="EMQX dashboard/API base URL. Env: EMQX_API_BASE_URL.",
    )
    parser.add_argument("--api-key", default=os.environ.get("EMQX_API_KEY", ""), help="EMQX REST API key.")
    parser.add_argument("--api-secret", default=os.environ.get("EMQX_API_SECRET", ""), help="EMQX REST API secret.")
    parser.add_argument(
        "--authenticator-id",
        default=os.environ.get("EMQX_AUTHENTICATOR_ID", DEFAULT_AUTHENTICATOR_ID),
        help="EMQX authenticator ID. Default: password_based:built_in_database.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="EMQX API timeout in seconds.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        device_id = resolve_cli_device_id(args)
        password = args.password or generate_device_password()
        api_config = EmqxApiConfig(
            base_url=args.api_base_url,
            api_key=args.api_key,
            api_secret=args.api_secret,
            authenticator_id=args.authenticator_id,
        )
        action = provision_device_user(
            EmqxApiClient(api_config, timeout_s=args.timeout),
            device_id=device_id,
            password=password,
            update_existing=args.update_existing,
        )
        if args.write_env:
            upsert_env_file(
                args.write_env,
                {
                    "MQTT_DEVICE_ID": device_id,
                    "MQTT_USERNAME": device_id,
                    "MQTT_PASSWORD": password,
                },
            )
            print(f"emqx_user_{action} device_id={device_id} env_updated={args.write_env}")
        else:
            print(f"emqx_user_{action} device_id={device_id}")
            print("MQTT_DEVICE_ID=" + device_id)
            print("MQTT_USERNAME=" + device_id)
            print("MQTT_PASSWORD=" + password)
        return 0
    except Exception as exc:
        print(f"provision_failed error={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
