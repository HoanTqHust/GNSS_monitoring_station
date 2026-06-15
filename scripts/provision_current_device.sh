#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env}"
EMQX_API_BASE_URL="${EMQX_API_BASE_URL:-http://gnss.soict.io:18083}"
DEVICE_INTERFACE="${DEVICE_INTERFACE:-}"
UPDATE_EXISTING="${UPDATE_EXISTING:-0}"

if [[ -z "${EMQX_API_KEY:-}" ]]; then
    read -r -p "EMQX API key: " EMQX_API_KEY
fi

if [[ -z "${EMQX_API_SECRET:-}" ]]; then
    read -r -s -p "EMQX API secret: " EMQX_API_SECRET
    printf '\n'
fi

if [[ -z "$EMQX_API_KEY" ]]; then
    printf 'provision_failed error=EMQX_API_KEY is empty\n' >&2
    exit 1
fi

if [[ -z "$EMQX_API_SECRET" ]]; then
    printf 'provision_failed error=EMQX_API_SECRET is empty\n' >&2
    exit 1
fi

args=(
    "scripts/provision_emqx_device.py"
    "--api-base-url" "$EMQX_API_BASE_URL"
    "--api-key" "$EMQX_API_KEY"
    "--api-secret" "$EMQX_API_SECRET"
    "--write-env" "$ENV_FILE"
)

if [[ -n "$DEVICE_INTERFACE" ]]; then
    args+=("--interface" "$DEVICE_INTERFACE")
fi

if [[ "$UPDATE_EXISTING" == "1" || "$UPDATE_EXISTING" == "true" ]]; then
    args+=("--update-existing")
fi

python3 "${args[@]}"

printf 'provision_done env_file=%s\n' "$ENV_FILE"
printf 'Next: unset EMQX_API_KEY EMQX_API_SECRET, then run python app.py\n'
