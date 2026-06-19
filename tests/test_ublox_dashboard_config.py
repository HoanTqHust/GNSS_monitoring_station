import unittest

from scripts.configure_ublox_dashboard_messages import configure_ports
from scripts.ublox_dashboard_config import (
    DASHBOARD_MESSAGES,
    UbloxMessage,
    build_dashboard_config_commands,
    cfg_cfg_save_current,
    cfg_msg_all_ports,
    cfg_prt_usb_ubx_only,
    ubx_frame,
)


class UbloxFrameTests(unittest.TestCase):
    def test_ubx_frame_wraps_payload_and_checksum(self):
        frame = ubx_frame(0x06, 0x01, bytes([0x01, 0x07, 1, 1, 1, 1, 1, 0]))

        self.assertEqual(frame[:2], b"\xb5\x62")
        self.assertEqual(frame[2], 0x06)
        self.assertEqual(frame[3], 0x01)
        self.assertEqual(int.from_bytes(frame[4:6], "little"), 8)
        self.assertEqual(frame[6:-2], bytes([0x01, 0x07, 1, 1, 1, 1, 1, 0]))
        self.assertEqual(frame[-2:], _independent_checksum(frame[2:-2]))

    def test_cfg_msg_all_ports_sets_every_output_rate(self):
        frame = cfg_msg_all_ports(UbloxMessage("NAV-PVT", 0x01, 0x07), rate=1)

        self.assertEqual(frame[6:-2], bytes([0x01, 0x07, 1, 1, 1, 1, 1, 0]))

    def test_cfg_prt_usb_ubx_only_uses_valid_cfg_prt_payload_length(self):
        frame = cfg_prt_usb_ubx_only()

        self.assertEqual(frame[2:4], bytes([0x06, 0x00]))
        self.assertEqual(int.from_bytes(frame[4:6], "little"), 20)
        self.assertEqual(frame[6], 0x03)
        self.assertEqual(int.from_bytes(frame[18:20], "little"), 0x01)
        self.assertEqual(int.from_bytes(frame[20:22], "little"), 0x01)

    def test_cfg_cfg_save_current_uses_save_mask_only(self):
        frame = cfg_cfg_save_current()

        self.assertEqual(frame[2:4], bytes([0x06, 0x09]))
        self.assertEqual(int.from_bytes(frame[4:6], "little"), 12)
        self.assertEqual(frame[6:10], b"\x00\x00\x00\x00")
        self.assertEqual(frame[10:14], b"\xff\xff\x00\x00")
        self.assertEqual(frame[14:18], b"\x00\x00\x00\x00")


class UbloxDashboardCommandPlanTests(unittest.TestCase):
    def test_command_plan_enables_dashboard_messages_after_disables(self):
        commands = build_dashboard_config_commands(save=True)
        descriptions = [command.description for command in commands]

        for message in DASHBOARD_MESSAGES:
            self.assertIn(f"Enable {message.identity}", descriptions)

        first_enable_index = min(index for index, description in enumerate(descriptions) if description.startswith("Enable "))
        last_disable_index = max(index for index, description in enumerate(descriptions) if description.startswith("Disable "))
        self.assertGreater(first_enable_index, last_disable_index)
        self.assertEqual(descriptions[-1], "Save current configuration to non-volatile memory")

    def test_command_plan_disables_known_noisy_messages(self):
        descriptions = [command.description for command in build_dashboard_config_commands(save=False)]

        self.assertIn("Disable RXM-SFRBX", descriptions)
        self.assertIn("Disable NAV-POSECEF", descriptions)
        self.assertIn("Disable NMEA-F0-00", descriptions)

    def test_no_save_omits_cfg_cfg_command(self):
        descriptions = [command.description for command in build_dashboard_config_commands(save=False)]

        self.assertNotIn("Save current configuration to non-volatile memory", descriptions)


class UbloxDashboardCliTests(unittest.TestCase):
    def test_dry_run_does_not_require_serial_or_hardware(self):
        configure_ports(
            ["/dev/test0", "/dev/test1"],
            baudrate=115200,
            dry_run=True,
            save=False,
            delay_s=0.0,
        )

    def test_rejects_empty_port_list(self):
        with self.assertRaises(ValueError):
            configure_ports([], baudrate=115200, dry_run=True, save=False, delay_s=0.0)


def _independent_checksum(data):
    ck_a = 0
    ck_b = 0
    for value in data:
        ck_a = (ck_a + value) % 256
        ck_b = (ck_b + ck_a) % 256
    return bytes([ck_a, ck_b])


if __name__ == "__main__":
    unittest.main()
