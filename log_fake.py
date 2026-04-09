#!/usr/bin/env python3

import os
import serial
import threading
from datetime import datetime

# Danh sách các Serial port và file output tương ứng
port_list = [
    ("/dev/ttyACM0", "raw_data_1.ubx"),
    ("/dev/ttyACM1", "raw_data_2.ubx"),
    ("/dev/ttyACM2", "raw_data_3.ubx"),
]

# Tạo thư mục theo format YYYY-MM-DD
folder_name = datetime.now().strftime("%Y-%m-%d")
os.makedirs(folder_name, exist_ok=True)

def record_data(port, filename):
    file_path = os.path.join(folder_name, filename)
    try:
        ser = serial.Serial(port, baudrate=115200, timeout=1)
        print(f"✅ Đang ghi từ {port} → {file_path}")
    except Exception as e:
        print(f"❌ Không mở được {port}: {e}")
        return

    with open(file_path, "wb") as f:
        while True:
            try:
                data = ser.read(1024)
                if data:
                    f.write(data)
            except KeyboardInterrupt:
                print(f"\n⛔ Dừng ghi từ {port}")
                break
            except Exception as e:
                print(f"⚠️ Lỗi đọc {port}: {e}")
                break

    ser.close()
    print(f"✅ Đã đóng {port}")

threads = []
for port, filename in port_list:
    t = threading.Thread(target=record_data, args=(port, filename))
    t.daemon = True
    threads.append(t)
    t.start()

print("🎯 Đang thu dữ liệu... nhấn Ctrl + C để dừng toàn bộ.\n")

try:
    while True:
        pass
except KeyboardInterrupt:
    print("\n🛑 Dừng toàn bộ script.")
