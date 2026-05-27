#!/usr/bin/env python3
"""
SDR Server: Đọc data từ bladeRF và stream qua TCP port.
Usage: python tests/sdr_server.py [freq] [sr] [port] [chunk_size]
"""
import sys
import socket
import struct
import numpy as np
from datetime import datetime

sys.path.insert(0, "/home/ubuntu/sdr")
from src import BladeRFSdr, Receiver


def send_samples(conn, samples):
    """Gửi samples dạng binary: [int32 count][float32 I][float32 Q] ..."""
    count = len(samples)
    interleaved = np.empty(count * 2, dtype=np.float32)
    interleaved[0::2] = samples.real
    interleaved[1::2] = samples.imag
    data = interleaved.tobytes()
    conn.sendall(struct.pack("<i", count) + data)


def main():
    freq = float(sys.argv[1]) if len(sys.argv) > 1 else 2.4e9
    sr = float(sys.argv[2]) if len(sys.argv) > 2 else 10e6
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 5555
    chunk = int(sys.argv[4]) if len(sys.argv) > 4 else 1024

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Server starting on port {port}...")
    print(f"Frequency: {freq/1e6:.1f} MHz, SR: {sr/1e6:.1f} Msps, Chunk: {chunk}")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", port))
    server.listen(1)
    print(f"Waiting for client...")

    conn, addr = server.accept()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Connected: {addr}")

    with BladeRFSdr() as sdr:
        sdr.config_rx(freq=freq, sr=sr, gain=50)
        rx = Receiver(sdr)
        total = 0

        try:
            while True:
                samples = rx.receive(chunk)
                # Remove DC offset
                samples = samples - samples.mean()
                send_samples(conn, samples)
                total += len(samples)
                amp = np.abs(samples).max()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent {total} samples, peak amp: {amp:.4f}", end="\r")
        except (BrokenPipeError, ConnectionResetError):
            print(f"\nClient disconnected. Total: {total} samples")
        finally:
            conn.close()
            server.close()


if __name__ == "__main__":
    main()
