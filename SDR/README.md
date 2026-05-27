# SDR - Software-Defined Radio với BladeRF

Thư viện Python điều khiển thiết bị Software-Defined Radio **Nuand bladeRF**, cung cấp API đơn giản để nhận (RX) và phát (TX) mẫu tín hiệu IQ.

---

## Tổng quan

Dự án bao gồm ba thành phần chính:

| Thành phần | Mô tả |
|---|---|
| **BladeRFSdr** | Wrapper quản lý kết nối và cấu hình thiết bị bladeRF |
| **Receiver** | Nhận mẫu IQ từ antenna, chuyển đổi SC16_Q11 → complex64 |
| **Transmitter** | Phát mẫu complex64 ra antenna, chuyển đổi complex64 → SC16_Q11 |

---

## Cấu trúc thư mục

```
sdr/
├── src/                    # Thư viện core
│   ├── __init__.py         # Exports: BladeRFSdr, Receiver, Transmitter
│   ├── common.py           # Lớp BladeRFSdr - quản lý thiết bị
│   ├── receiver.py         # Lớp Receiver - nhận mẫu IQ
│   └── transmitter.py       # Lớp Transmitter - phát mẫu IQ
├── tests/
│   ├── test_bladerf.py     # Unit tests cho thiết bị thật
│   ├── read_and_log.py     # Đọc mẫu và ghi log thống kê
│   ├── sdr_server.py        # TCP server stream IQ qua socket
│   └── sdr_web.py          # Web viewer thời gian thực (Flask + Chart.js)
├── examples/
│   ├── receive_loop.py     # Nhận mẫu + vẽ PSD bằng matplotlib
│   └── transmit_tone.py    # Phát tone sin tại tần số chỉ định
├── bladeRF/               # Git submodule - firmware & HDL của bladeRF
└── requirements.txt       # Dependency: numpy >= 1.24.0
```

---

## Yêu cầu

- Python >= 3.8
- Thiết bị bladeRF (bladerf1 hoặc bladerf2)
- FPGA đã được nạp cho bladeRF
- `libbladeRF` đã build tại `bladeRF/host/build/output`
- `numpy >= 1.24.0`

---

## Cài đặt

```bash
# Clone repository cùng submodule
git clone --recursive https://github.com/your-repo/sdr.git
cd sdr

# Khởi tạo submodule bladeRF
git submodule update --init --recursive

# Build libbladeRF (nếu chưa có)
cd bladeRF/host
mkdir build && cd build
cmake .. && make

# Cài dependency Python
pip install -r requirements.txt
```

---

## Sử dụng cơ bản

### Nhận tín hiệu

```python
from src import BladeRFSdr, Receiver

with BladeRFSdr() as sdr:
    sdr.config_rx(freq=433e6, sr=2e6, gain=30, bw=1.5e6)
    rx = Receiver(sdr.sync_rx)

    samples = rx.receive(num_samples=1024)
    print(f"Nhận được {len(samples)} mẫu")
```

### Phát tín hiệu

```python
from src import BladeRFSdr, Transmitter

with BladeRFSdr() as sdr:
    sdr.config_tx(freq=433e6, sr=2e6, gain=0, bw=1.5e6)
    tx = Transmitter(sdr.sync_tx)

    # Tạo tone 1 MHz
    tone = tx.generate_tone(freq_hz=1e6, num_samples=1024, sample_rate=2e6)
    tx.send(tone)
```

### Ví dụ: Vẽ phổ tần số

```bash
python examples/receive_loop.py
```

---

## Các công cụ kèm theo

### Web Spectrum Viewer
Web server hiển thị phổ tín hiệu thời gian thực qua Chart.js.

```bash
python tests/sdr_web.py
# Truy cập http://localhost:5555
```

### TCP Stream Server
Stream mẫu IQ nhị phân qua TCP socket.

```bash
python tests/sdr_server.py
```

### Logging & Thống kê
Đọc và phân tích mẫu, ghi log thống kê amplitude.

```bash
python tests/read_and_log.py
```

---

## Chi tiết kỹ thuật

### Sample Format
- BladeRF sử dụng định dạng **SC16_Q11** (int16 I/Q interleaved)
- Thư viện chuyển đổi sang **complex64** (numpy complex) cho dễ xử lý
- Hệ số normalize: chia cho `2048.0`

### Cấu hình RX/TX mặc định
- **Buffers:** 16
- **Buffer size:** 8192 bytes
- **Transfers:** 8
- **Timeout:** 3500ms

---

## Testing

```bash
# Chạy unit tests (cần có bladeRF kết nối)
python -m pytest tests/test_bladerf.py

# Hoặc chạy trực tiếp
python tests/test_bladerf.py
```

> **Lưu ý:** Các test tương tác trực tiếp với phần cứng thật. Cần có bladeRF được kết nối và FPGA đã nạp.

---

## Giấy phép

MIT License
