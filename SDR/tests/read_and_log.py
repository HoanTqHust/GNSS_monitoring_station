#!/usr/bin/env python3
"""
Đọc data từ bladeRF và ghi log.
Usage: python tests/read_and_log.py [freq] [sr] [n_samples] [output_file]
"""
import sys
import numpy as np
from datetime import datetime

sys.path.insert(0, "/home/ubuntu/sdr")
from src import BladeRFSdr, Receiver


def main():
    freq = float(sys.argv[1]) if len(sys.argv) > 1 else 2.4e9
    sr = float(sys.argv[2]) if len(sys.argv) > 2 else 10e6
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 10240
    out_file = sys.argv[4] if len(sys.argv) > 4 else "sdr_capture.log"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_lines = [
        f"=== bladeRF Capture Log ===",
        f"Time:       {timestamp}",
        f"Frequency:  {freq/1e6:.1f} MHz",
        f"Sample Rate: {sr/1e6:.1f} Msps",
        f"Samples:   {n}",
        "",
    ]

    with BladeRFSdr() as sdr:
        log_lines.append(f"Board: {sdr.sdr.board_name}")
        log_lines.append(f"Firmware: {sdr.sdr.fw_version}")
        log_lines.append(f"FPGA: {sdr.sdr.fpga_version}")
        log_lines.append("")

        sdr.config_rx(freq=freq, sr=sr, gain=50)
        rx = Receiver(sdr)

        log_lines.append("Receiving...")
        samples = rx.receive(n)
        log_lines.append(f"Done. Received {len(samples)} samples.")

        amp = np.abs(samples)
        log_lines.extend([
            "",
            "=== Statistics ===",
            f"Amplitude  min: {amp.min():.6f}",
            f"Amplitude  max: {amp.max():.6f}",
            f"Amplitude  mean: {amp.mean():.6f}",
            f"Amplitude  std:  {amp.std():.6f}",
            "",
            "=== First 20 samples ===",
            "    i       q",
        ])
        for s in samples[:20]:
            log_lines.append(f"{s.real:>8.4f}  {s.imag:>8.4f}")

    with open(out_file, "w") as f:
        f.write("\n".join(log_lines))

    print(f"Log saved to: {out_file}")


if __name__ == "__main__":
    main()
