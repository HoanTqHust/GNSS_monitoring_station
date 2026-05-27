# BladeRF Integration Guide — GNSS Jamming Classifier

Hướng dẫn cấu hình bladeRF và xử lý tín hiệu để đưa dữ liệu vào model `gnss_jamming_classifier_mps.pth`.

---

## 1. Tổng quan pipeline

```
bladeRF (IQ raw)
    │
    │  Thu 8192 samples @ 5 MHz
    ▼
STFT  (nperseg=256, noverlap=128, scipy.signal.stft)
    │
    │  Ma trận |Z| (magnitude)
    ▼
Render ảnh PNG  (3×3 inch, dpi=80, colormap mặc định matplotlib)
    │
    │  Resize về 224×224, normalize ImageNet
    ▼
ResNet18  →  6 class output
```

---

## 2. Cấu hình bladeRF

| Tham số | Giá trị | Ghi chú |
|---------|---------|---------|
| Center frequency | **1575.42 MHz** | GPS L1 |
| Sample rate | **5 MHz** | Bắt buộc khớp với `FS = 5e6` |
| Samples per frame | **8192** | Bắt buộc khớp với `N = 8192` |
| Format | **SC16_Q11** (int16 IQ) | Chuẩn bladeRF |
| Gain mode | Manual | Tránh AGC làm thay đổi biên độ |
| Gain | 20–30 dB | Điều chỉnh theo môi trường |
| Bandwidth | 2.5 MHz | `sample_rate / 2` |

---

## 3. Xử lý tín hiệu từng frame

### Bước 1 — Đọc và chuyển đổi IQ

```python
import numpy as np

buf = bytearray(8192 * 4)          # 8192 samples × 4 bytes (int16 I + int16 Q)
sdr.sync_rx(buf, 8192)

raw = np.frombuffer(buf, dtype=np.int16).copy()
iq = (raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)) / 2048.0
signal = iq.real                   # Dùng phần thực (model train trên tín hiệu thực)
```

### Bước 2 — Tính STFT

```python
from scipy.signal import stft

FS = 5e6
f, t, Z = stft(signal, fs=FS, nperseg=256, noverlap=128)
magnitude = np.abs(Z)              # Không dùng dB, dùng magnitude trực tiếp
```

### Bước 3 — Render ảnh

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
from PIL import Image

fig = plt.figure(figsize=(3, 3))
plt.axis("off")
plt.pcolormesh(t, f, magnitude, shading="gouraud")
plt.savefig("/tmp/frame.png", dpi=80, bbox_inches="tight", pad_inches=0)
plt.close(fig)
```

> **Quan trọng:** Dùng đúng `figsize=(3,3)`, `dpi=80`, `shading="gouraud"`, không thêm colorbar hay title.

### Bước 4 — Đưa vào model

```python
import torch
import torch.nn as nn
from torchvision import transforms, models
from PIL import Image

# Load model (chỉ làm 1 lần khi khởi động)
device = torch.device("cpu")
model = models.resnet18(weights=None)
model.fc = nn.Linear(512, 6)
model.load_state_dict(torch.load("gnss_jamming_classifier_mps.pth", map_location=device))
model.eval()

transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225])
])

# Inference mỗi frame
img = Image.open("/tmp/frame.png").convert("RGB")
tensor = transform(img).unsqueeze(0).to(device)

with torch.no_grad():
    output = model(tensor)
    pred_idx = torch.argmax(output, dim=1).item()
```

---

## 4. Nhãn đầu ra (class index)

| Index | Class | Mô tả |
|-------|-------|-------|
| 0 | `DME` | Distance Measuring Equipment — burst pulse |
| 1 | `NB` | Narrowband — tone liên tục |
| 2 | `NoJam` | Không có jamming |
| 3 | `SingleAM` | AM jamming đơn sóng mang |
| 4 | `SingleChirp` | Chirp sweep 100–300 kHz |
| 5 | `SingleFM` | FM jamming đơn sóng mang |

---

## 5. Lưu ý quan trọng

- **Sample rate phải là 5 MHz** — khác giá trị này sẽ làm sai hình dạng spectrogram, model cho kết quả sai.
- **Không dùng AGC** — biên độ tín hiệu ảnh hưởng đến màu sắc spectrogram, AGC sẽ làm mất đặc trưng.
- **Colormap mặc định matplotlib** (`viridis`) — không thay bằng colormap khác.
- **Dùng phần thực của IQ** — model được train trên tín hiệu thực (`iq.real`), không phải magnitude IQ phức.
- Mỗi frame độc lập — không cần buffer liên tiếp giữa các frame.

---

## 6. Ví dụ đầy đủ (pseudo-code realtime)

```python
while running:
    sdr.sync_rx(buf, 8192)
    signal = convert_iq_to_real(buf)          # Bước 1
    magnitude = compute_stft(signal)          # Bước 2
    img_path = render_to_png(magnitude)       # Bước 3
    class_idx = infer(model, img_path)        # Bước 4
    print(CLASS_NAMES[class_idx])
```

---

## 7. Dependencies

```
torch==2.2.2
torchvision==0.17.2
scipy>=1.11.0
matplotlib>=3.8.0
numpy>=1.26.0
Pillow>=10.0.0
bladerf (Python bindings)
```
