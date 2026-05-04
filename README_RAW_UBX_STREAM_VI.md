# README Raw UBX Stream (Tiếng Việt)

## 1) Mục tiêu file này

File này giải thích chi tiết:

- Từng trường dữ liệu đang đi qua pipeline realtime.
- Ý nghĩa từng chỉ số đang hiển thị trên màn hình `Raw UBX Stream`.
- Từng loại `identity` (theo nhóm bản tin UBX) và bản tin nào hệ thống đang dùng trực tiếp.

Phạm vi mô tả bám theo code hiện tại:

- [thread/ReadSerialThread.py](/home/firefly/double_difference_cp/thread/ReadSerialThread.py)
- [thread/RTKLIBStage.py](/home/firefly/double_difference_cp/thread/RTKLIBStage.py)
- [thread/SocketThread.py](/home/firefly/double_difference_cp/thread/SocketThread.py)
- [templates/index.html](/home/firefly/double_difference_cp/templates/index.html)
- [models/RAWXData.py](/home/firefly/double_difference_cp/models/RAWXData.py)
- [models/SatelliteData.py](/home/firefly/double_difference_cp/models/SatelliteData.py)

---

## 2) Luồng dữ liệu tổng quát

```text
u-blox serial
  -> RTKLIBStage.normalize_frame()/normalize_epoch_pair()
  -> ingress queue (RAM)
  -> router (fan-out)
     -> raw queue    -> emit raw_data_batch -> UI Raw UBX Stream
     -> detect queue -> detector + chart    -> emit update_image
```

Trong code:

1. `ReadSerial` đọc từng bản tin UBX từ `rx1`, `rx2`.
2. Mỗi bản tin tạo event `ubx_frame`.
3. Khi đồng bộ epoch (`RXM-RAWX` + `NAV-PVT` hai máy), tạo thêm event `epoch_pair`.
4. Router tách event theo `event_type`.

---

## 3) Cấu trúc dữ liệu chi tiết

## 3.1 Event chung trong ingress queue

Mỗi event trong ingress queue có dạng:

```json
{
  "seq": 123,
  "event_type": "ubx_frame | epoch_pair",
  "created_at_utc": "2026-05-04T12:34:56.789+00:00",
  "payload": { ... }
}
```

- `seq`: số thứ tự tăng dần toàn cục trong process ingest.
- `event_type`: loại event để router tách nhánh.
- `created_at_utc`: timestamp tạo event ở ingest.
- `payload`: nội dung thực tế theo từng loại event.

## 3.2 Payload của `ubx_frame` (raw stream)

`payload` của `ubx_frame` được tạo ở `RTKLIBStage.normalize_frame()`:

```json
{
  "stage": "rtklib",
  "received_at_utc": "...",
  "receiver": "rx1 | rx2",
  "identity": "NAV-PVT | RXM-RAWX | ...",
  "tow_s": 123456.0,
  "raw_len": 248,
  "raw_base64": "...."
}
```

- `stage`: marker logic stage, hiện là `"rtklib"`.
- `received_at_utc`: thời điểm ingest đọc được frame.
- `receiver`: nguồn thiết bị (`rx1` hoặc `rx2`).
- `identity`: tên bản tin UBX/NMEA do `pyubx2` parse.
- `tow_s`: GPS Time Of Week (giây), nếu bản tin có trường `rcvTow`; nếu không có thì `null`.
- `raw_len`: độ dài frame nhị phân gốc (byte).
- `raw_base64`: raw bytes encode base64 để có thể truyền qua socket/json.

## 3.3 Payload của `epoch_pair` (detect path)

`payload` của `epoch_pair` được tạo ở `RTKLIBStage.normalize_epoch_pair()`:

```json
{
  "stage": "rtklib",
  "received_at_utc": "...",
  "tow_s": 123456.0,
  "rawx_1": RAWXData,
  "nav_1": NAV-PVT object,
  "rawx_2": RAWXData,
  "nav_2": NAV-PVT object,
  "skyplot_data_1": NAV-SAT object,
  "skyplot_data_2": NAV-SAT object,
  "spectrum_data_1": MON-SPAN object,
  "spectrum_data_2": MON-SPAN object
}
```

- `tow_s`: min(`rcvTow` của hai máy).
- `rawx_*`: dữ liệu quan sát GNSS để detect.
- `nav_*`: trạng thái định vị tương ứng epoch.
- `skyplot_data_*`, `spectrum_data_*`: dữ liệu phục vụ render.

## 3.4 Dữ liệu model trong `RAWXData` / `SatelliteData`

### `RAWXData`

- `rcvTow`: Time Of Week của epoch đo.
- `week`: GPS week.
- `satData`: danh sách vệ tinh trong epoch.

### `SatelliteData` (mỗi vệ tinh)

- `prMes`: pseudorange measurement.
- `cpMes`: carrier phase measurement.
- `doMes`: Doppler measurement.
- `gnssId`: hệ GNSS (GPS/GLO/GAL/BDS...).
- `svId`: mã vệ tinh.
- `sigId`: mã tín hiệu.
- `locktime`: thời gian lock tín hiệu.
- `freqId`: id tần số (quan trọng với GLONASS).
- `cno`: C/N0.

---

## 4) Các chỉ số hiển thị trên màn hình Raw UBX Stream

## 4.1 Khối tổng quan (global)

Các field hiển thị ở panel trên cùng:

- `Frames received in browser`: tổng frame raw browser đã nhận từ `raw_data_batch`.
- `Last batch size`: số frame của batch gần nhất.
- `Last sequence`: `seq` lớn nhất browser đã thấy.
- `Duplicate seq frames`: số frame có `seq` lùi/trùng so với `lastSeq`.
- `Sequence gaps observed in browser`: tổng số khoảng trống `seq` bị nhảy.
- `Queue total events`: tổng event ingress router đã nhận (`ingress_received`).
- `Detect processed count`: số event detect đã xử lý (`detect_processed`).
- `Queue pending events`: tổng backlog 3 queue (ingress + detect + raw) nếu đọc được `qsize`.
- `Ingress backlog`: số phần tử tồn trong ingress queue.
- `Detect backlog`: số phần tử tồn trong detect queue.
- `Raw backlog`: số phần tử tồn trong raw queue.
- `Detect dropped`: số event bị drop ở detect queue do đầy.
- `Raw dropped`: số event bị drop ở raw queue do đầy.

Lưu ý:

- Trường `last_acked_seq` trong payload `queue_stats` hiện đang map vào `detect_processed` để giữ tương thích UI cũ, không còn nghĩa ACK SQLite.

## 4.2 Khối theo từng receiver (`rx1`, `rx2`)

- `Total frames`: tổng frame của receiver đó browser đã nhận.
- `Last seq`: `seq` mới nhất của receiver đó.
- `Duplicates`: số bản tin trùng/lùi `seq` theo receiver.
- `Gaps`: số khoảng trống `seq` theo receiver.
- `Identity counts`: đếm số lần xuất hiện từng `identity`.

## 4.3 Bảng chi tiết từng dòng

Mỗi dòng một frame:

- `Idx`: thứ tự hiển thị cục bộ theo receiver (tăng dần theo số frame đã nhận).
- `Seq`: sequence toàn cục từ ingest.
- `Timestamp`: ưu tiên `received_at_utc`, fallback `created_at_utc`.
- `Identity`: tên bản tin UBX/NMEA.
- `TOW(s)`: `tow_s` (nếu có).
- `Len(B)`: `raw_len`.

---

## 5) Identity là gì?

`identity` là tên message sau khi parse từ frame u-blox (qua `pyubx2`), ví dụ:

- `RXM-RAWX`
- `NAV-PVT`
- `NAV-SAT`
- `MON-SPAN`
- và nhiều bản tin khác cùng prefix `NAV-*`, `MON-*`, `RXM-*`, `SEC-*`, `TIM-*`...

## 5.1 Nhóm identity hệ thống dùng trực tiếp

Các identity có logic xử lý rõ trong code:

1. `RXM-RAWX`
- Dùng tạo `RAWXData` cho detect.
- Là dữ liệu đo thô GNSS theo epoch.

2. `NAV-PVT`
- Dùng làm điều kiện ghép cặp epoch giữa 2 receiver.
- Cung cấp trạng thái định vị/thời gian.

3. `NAV-SAT`
- Lưu vào state `skyplot` để vẽ skyplot.

4. `MON-SPAN`
- Lưu vào state `spectrum` để vẽ spectrum.

## 5.2 Nhóm identity chỉ pass-through raw stream

Các identity khác (ví dụ nhiều bản tin `NAV-*`, `MON-*`, `SEC-*`, `TIM-*`) hiện:

- vẫn được ingest,
- vẫn đi vào `raw_data_batch`,
- vẫn được thống kê trong `Identity counts`,
- nhưng không tham gia trực tiếp vào nhánh detect hiện tại (trừ khi bạn thêm logic).

---

## 6) Gợi ý đọc nhanh khi debug

1. Xem `Identity counts` để biết luồng bản tin đang phát.
2. Nếu `Gaps` tăng nhanh:
- kiểm tra `Ingress/Detect/Raw backlog`,
- kiểm tra `Detect dropped` hoặc `Raw dropped`.
3. Nếu detect không ra:
- kiểm tra có đủ `RXM-RAWX` + `NAV-PVT` từ cả `rx1`/`rx2` không,
- kiểm tra điều kiện đồng bộ `round(rcvTow)` giữa 2 máy.

---

## 7) Giới hạn hiện tại

- Pipeline là RAM-only: mất process là mất queue state.
- `raw_base64` tăng tải mạng/UI; nếu cần tối ưu, có thể phát raw ở chế độ sampling hoặc nhị phân riêng.
- `identity` có thể khác theo cấu hình message rate trên thiết bị u-blox.
