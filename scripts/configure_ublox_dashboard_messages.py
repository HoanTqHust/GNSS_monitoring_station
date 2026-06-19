#!/usr/bin/env python3

# python3 scripts/configure_ublox_dashboard_messages.py
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Optional, Sequence

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from config import config as app_config
from scripts.ublox_dashboard_config import build_dashboard_config_commands, dashboard_identity_names


LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


class UbloxConfigurationError(RuntimeError):
    pass


def configure_ports(
    ports: Sequence[str],
    *,
    baudrate: int,
    dry_run: bool,
    save: bool,
    delay_s: float,
) -> None:
    clean_ports = _normalize_ports(ports)
    _validate_baudrate(baudrate)
    _validate_delay(delay_s)

    commands = build_dashboard_config_commands(save=save)
    logging.info(
        "ublox_dashboard_config_start ports=%s baudrate=%s dry_run=%s save=%s target_identities=%s commands=%s",
        ",".join(clean_ports),
        baudrate,
        dry_run,
        save,
        ",".join(dashboard_identity_names()),
        len(commands),
    )

    if dry_run:
        for command_index, command in enumerate(commands, start=1):
            logging.info(
                "ublox_dashboard_config_command index=%s description=%r bytes=%s",
                command_index,
                command.description,
                command.frame.hex(" "),
            )
        logging.info("ublox_dashboard_config_dry_run_complete")
        return

    try:
        import serial
    except ImportError as exc:
        raise UbloxConfigurationError("pyserial is required to configure u-blox receivers") from exc

    for port in clean_ports:
        logging.info("ublox_dashboard_config_port_start port=%s", port)
        try:
            with serial.Serial(port, baudrate=baudrate, timeout=1) as serial_port:
                for command_index, command in enumerate(commands, start=1):
                    logging.info(
                        "ublox_dashboard_config_write port=%s index=%s description=%r bytes=%s",
                        port,
                        command_index,
                        command.description,
                        len(command.frame),
                    )
                    written = serial_port.write(command.frame)
                    serial_port.flush()
                    if written != len(command.frame):
                        raise UbloxConfigurationError(
                            f"short serial write on {port}: wrote {written}/{len(command.frame)} bytes"
                        )
                    time.sleep(delay_s)
        except OSError as exc:
            raise UbloxConfigurationError(f"failed to configure {port}: {exc}") from exc
        logging.info("ublox_dashboard_config_port_complete port=%s", port)

    logging.info("ublox_dashboard_config_complete")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Configure u-blox receivers to output only the dashboard-required UBX messages: "
            + ", ".join(dashboard_identity_names())
        )
    )
    parser.add_argument(
        "--ports",
        nargs="+",
        default=[app_config.PORT1, app_config.PORT2],
        help="Serial ports to configure. Default: config.PORT1 and config.PORT2.",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Serial baudrate used while sending configuration commands.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the UBX command plan without opening serial ports.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not persist the configuration to non-volatile memory.",
    )
    parser.add_argument(
        "--delay-s",
        type=float,
        default=0.05,
        help="Delay after each UBX command write.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Console log level.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format=LOG_FORMAT)

    try:
        configure_ports(
            args.ports,
            baudrate=args.baudrate,
            dry_run=args.dry_run,
            save=not args.no_save,
            delay_s=args.delay_s,
        )
    except (ValueError, UbloxConfigurationError) as exc:
        logging.error("ublox_dashboard_config_failed error=%s", exc)
        return 1
    return 0


def _normalize_ports(ports: Sequence[str]) -> Sequence[str]:
    if not ports:
        raise ValueError("at least one serial port is required")
    clean_ports = []
    for port in ports:
        if not isinstance(port, str) or not port.strip():
            raise ValueError("serial ports must be non-empty strings")
        clean_ports.append(port.strip())
    return tuple(clean_ports)


def _validate_baudrate(baudrate: int) -> None:
    if not isinstance(baudrate, int) or baudrate <= 0:
        raise ValueError("baudrate must be a positive integer")


def _validate_delay(delay_s: float) -> None:
    if delay_s < 0:
        raise ValueError("delay_s must not be negative")


if __name__ == "__main__":
    raise SystemExit(main())
