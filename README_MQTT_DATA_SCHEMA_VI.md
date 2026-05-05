# README MQTT Data Schema cho server ngoài

## 1) Mục tiêu

File này mô tả cấu trúc JSON dự kiến publish lên MQTT broker để một server khác có thể subscribe và xử lý dữ liệu GNSS realtime.

Schema được thiết kế cho 4 nhóm dữ liệu:

- Raw u-blox frame hiện tại.
- Detect result theo từng epoch đồng bộ giữa 2 receiver.
- Raw SDR frontend trong tương lai.
- Health/runtime metrics của pipeline.

Nguyên tắc thiết kế:

- Không trộn raw data nặng vào message detect nhẹ.
- Mỗi message có envelope chung để server ngoài có thể dedupe, theo dõi sequence gap, và route theo schema.
- Mỗi schema có version `v1`; thay đổi breaking thì tạo `v2`, không sửa ý nghĩa field cũ trong `v1`.
- Đơn vị đo nằm trong tên field, ví dụ `lat_deg`, `cno_dbhz`, `tow_s`, `sample_rate_hz`.
- Field JSON giữ nguyên tiếng Anh/ASCII để ổn định khi parse ở server.

---

## 2) Topic MQTT

Topic đề xuất:

```text
gnss/{site_id}/{device_id}/raw/ublox/v1
gnss/{site_id}/{device_id}/raw/sdr/v1
gnss/{site_id}/{device_id}/detect/epoch/v1
gnss/{site_id}/{device_id}/state/position/v1
gnss/{site_id}/{device_id}/health/v1
```

Ví dụ:

```text
gnss/lab_hanoi/ducanh_user/raw/ublox/v1
gnss/lab_hanoi/ducanh_user/detect/epoch/v1
gnss/lab_hanoi/ducanh_user/health/v1
```

Ý nghĩa:

- `site_id`: điểm đặt thiết bị, ví dụ `lab_hanoi`, `field_test_01`.
- `device_id`: định danh logical của node publish lên MQTT, ví dụ `ducanh_user`.
- `raw/ublox/v1`: từng frame UBX/NMEA từ receiver u-blox.
- `raw/sdr/v1`: raw snapshot hoặc metadata từ SDR frontend trong tương lai.
- `detect/epoch/v1`: kết quả detect cho một epoch đã đồng bộ.
- `state/position/v1`: vị trí mới nhất, có thể publish retain nếu cần server mới vào đọc trạng thái gần nhất.
- `health/v1`: backlog, dropped counter, process status.

Cấu hình QoS bắt buộc:

| Topic suffix | QoS | Retain | Ghi chú |
| --- | --- | --- | --- |
| `detect/epoch/v1` | 1 | false | Dữ liệu chính cho server ngoài đọc trạng thái spoofing. |
| `health/v1` | 1 | false | Dùng để cảnh báo backlog/drop. |
| `state/position/v1` | 1 | true hoặc false | Dùng `retain=true` nếu server cần vị trí mới nhất ngay khi subscribe. |
| `raw/ublox/v1` | 1 | false | Bắt buộc QoS 1 để giảm thất thoát raw frame trên đường MQTT; luôn theo dõi `seq`. |
| `raw/sdr/v1` | 1 | false | Bắt buộc QoS 1 dù payload có thể lớn; cần kiểm soát throughput/backpressure khi triển khai SDR. |

Ghi chú về QoS 1:

- QoS 1 là yêu cầu bắt buộc cho tất cả topic trong schema này.
- QoS 1 đảm bảo broker nhận message ít nhất một lần sau khi publisher publish thành công.
- QoS 1 có thể tạo duplicate khi retry, nên server vẫn phải dedupe bằng `(device_id, event_id)`.
- QoS 1 không tự bảo vệ dữ liệu đã mất trước bước publish, ví dụ queue nội bộ bị drop hoặc process chết trước khi publish xong. Vì vậy server vẫn phải theo dõi `seq`, `health.*_dropped`, và backlog.

---

## 3) Envelope chung

Tất cả payload JSON publish lên MQTT dùng envelope sau:

```json
{
  "schema": "gnss.detect.epoch.v1",
  "event_id": "ducanh_user-000000123456",
  "seq": 123456,
  "device_id": "ducanh_user",
  "site_id": "lab_hanoi",
  "frontend": "ublox",
  "source": "rx_pair",
  "event_time": "2026-04-22T03:29:36.000Z",
  "ingest_time": "2026-04-22T03:29:36.125Z",
  "data": {}
}
```

Field bắt buộc:

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `schema` | string | yes | Tên schema và version, ví dụ `gnss.detect.epoch.v1`. |
| `event_id` | string | yes | ID duy nhất cho message. Server dùng để dedupe. |
| `seq` | integer | yes | Sequence tăng dần theo publisher. Server dùng để phát hiện duplicate hoặc gap. |
| `device_id` | string | yes | Node publish lên MQTT. Đây không phải receiver riêng lẻ. |
| `site_id` | string | yes | Vị trí/site logic của node. |
| `frontend` | string | yes | `ublox`, `sdr`, hoặc `mixed`. |
| `source` | string | yes | Nguồn bên trong node: `rx1`, `rx2`, `rx_pair`, `sdr0`, `pipeline`. |
| `event_time` | string/null | yes | Thời gian của measurement. Ưu tiên GNSS time đã convert UTC nếu có. |
| `ingest_time` | string | yes | Thời điểm app nhận hoặc tạo message theo UTC. |
| `data` | object | yes | Nội dung domain theo từng schema. |

Quy tắc timestamp:

- Format: ISO-8601 UTC, kết thúc bằng `Z`.
- `event_time` là thời điểm của dữ liệu GNSS/SDR.
- `ingest_time` là thời điểm backend tạo message.
- Nếu chưa convert được GNSS time sang UTC, vẫn gửi `event_time` theo clock của backend và đặt `data.time.tow_s`.

Quy tắc null:

- Field chưa có giá trị thì dùng `null`, không dùng chuỗi `"N/A"`.
- Field boolean chưa kết luận thì dùng `null`, ví dụ `spoofing: null`.
- Không đổi type của field giữa các message cùng schema.

---

## 4) Schema `gnss.detect.epoch.v1`

Topic:

```text
gnss/{site_id}/{device_id}/detect/epoch/v1
```

Mục đích:

- Message chính cho server ngoài đọc trạng thái spoofing.
- Mỗi message đại diện cho một epoch đã đồng bộ giữa `rx1` và `rx2`.
- Không chứa raw UBX bytes.

Ví dụ đầy đủ:

```json
{
  "schema": "gnss.detect.epoch.v1",
  "event_id": "ducanh_user-000000123456",
  "seq": 123456,
  "device_id": "ducanh_user",
  "site_id": "lab_hanoi",
  "frontend": "ublox",
  "source": "rx_pair",
  "event_time": "2026-04-22T03:29:36.000Z",
  "ingest_time": "2026-04-22T03:29:36.125Z",
  "data": {
    "time": {
      "tow_s": 123456.0,
      "gps_week": 2415
    },
    "position": {
      "lat_deg": 21.0055,
      "lon_deg": 105.8445,
      "height_m": 12.3,
      "fix_type": "3d",
      "pdop": 1.63
    },
    "summary": {
      "sat_count": 12,
      "avg_cno_dbhz": 42.5,
      "spoofing": false,
      "status": "normal"
    },
    "signals": [
      {
        "gnss": "GPS",
        "svid": 16,
        "signal": "L1C",
        "prn": "G16",
        "cno_dbhz": 48.5,
        "used_in_fix": true,
        "receiver_ids": ["rx1", "rx2"]
      },
      {
        "gnss": "GLONASS",
        "svid": 8,
        "signal": "L1",
        "prn": "R08",
        "cno_dbhz": 32.6,
        "used_in_fix": false,
        "receiver_ids": ["rx1"]
      }
    ],
    "detectors": {
      "sos_carrier": {
        "detector_name": "sos",
        "measurement_name": "carrier",
        "score": 0.0123,
        "threshold": 0.09,
        "spoofing": false,
        "status": "normal",
        "reference_svid": 3,
        "visible_svids": [3, 8, 14, 22],
        "suspect_svids": []
      },
      "sos_smoothed_pseudorange": {
        "detector_name": "sos",
        "measurement_name": "smoothed_pseudorange",
        "score": 0.42,
        "threshold": 1.1,
        "spoofing": false,
        "status": "normal",
        "reference_svid": 3,
        "visible_svids": [3, 8, 14, 22],
        "suspect_svids": []
      },
      "d3_carrier": {
        "detector_name": "d3",
        "measurement_name": "carrier",
        "score": 0.0,
        "threshold": 0.02,
        "spoofing": false,
        "status": "normal",
        "reference_svid": 3,
        "visible_svids": [3, 8, 14, 22],
        "suspect_svids": []
      },
      "d3_smoothed_pseudorange": {
        "detector_name": "d3",
        "measurement_name": "smoothed_pseudorange",
        "score": null,
        "threshold": 0.5,
        "spoofing": null,
        "status": "pending",
        "reference_svid": null,
        "visible_svids": [],
        "suspect_svids": []
      }
    }
  }
}
```

### 4.1 `data.time`

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `tow_s` | number/null | yes | GPS Time Of Week theo giây. Lấy từ `RXM-RAWX.rcvTow` khi có. |
| `gps_week` | integer/null | yes | GPS week. Nếu chưa có thì `null`. |

### 4.2 `data.position`

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `lat_deg` | number/null | yes | Latitude theo degree. |
| `lon_deg` | number/null | yes | Longitude theo degree. |
| `height_m` | number/null | yes | Độ cao theo meter. |
| `fix_type` | string/null | yes | Loại fix, ví dụ `no_fix`, `2d`, `3d`, `rtk_float`, `rtk_fixed`. |
| `pdop` | number/null | yes | Position dilution of precision. |

### 4.3 `data.summary`

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `sat_count` | integer | yes | Số vệ tinh quan sát hoặc được tổng hợp trong epoch. |
| `avg_cno_dbhz` | number/null | yes | C/N0 trung bình, đơn vị dB-Hz. |
| `spoofing` | boolean/null | yes | Kết luận tổng hợp: `true`, `false`, hoặc `null` nếu chưa đủ kết luận. |
| `status` | string | yes | `spoofed`, `normal`, `pending`, hoặc `error`. |

Quy tắc tổng hợp `summary.spoofing` đề xuất:

- Nếu bất kỳ detector có `spoofing=true` thì `summary.spoofing=true`, `status=spoofed`.
- Nếu ít nhất một detector có `spoofing=false` và không có detector nào `true` thì `summary.spoofing=false`, `status=normal`.
- Nếu tất cả detector là `null` hoặc không có output thì `summary.spoofing=null`, `status=pending`.
- Nếu pipeline lỗi khi tính epoch thì `summary.spoofing=null`, `status=error`.

### 4.4 `data.signals[]`

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `gnss` | string | yes | Hệ vệ tinh: `GPS`, `GLONASS`, `GALILEO`, `BEIDOU`, `SBAS`, `UNKNOWN`. |
| `svid` | integer | yes | Satellite vehicle ID dạng số. |
| `signal` | string/null | yes | Tín hiệu/band, ví dụ `L1C`, `L2`, `E1`. |
| `prn` | string | yes | Mã hiển thị, ví dụ `G16`, `R08`, `E01`. |
| `cno_dbhz` | number/null | yes | Carrier-to-noise density, đơn vị dB-Hz. |
| `used_in_fix` | boolean/null | yes | Vệ tinh có được dùng trong navigation fix không, nếu biết. |
| `receiver_ids` | array[string] | yes | Receiver thấy signal này, ví dụ `["rx1", "rx2"]`. |

### 4.5 `data.detectors`

Key detector hiện tại:

- `sos_carrier`
- `sos_smoothed_pseudorange`
- `d3_carrier`
- `d3_smoothed_pseudorange`

Mỗi detector object:

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `detector_name` | string | yes | `sos` hoặc `d3`. |
| `measurement_name` | string | yes | `carrier` hoặc `smoothed_pseudorange`. |
| `score` | number/null | yes | Điểm detector tính được. |
| `threshold` | number/null | yes | Ngưỡng đang dùng. |
| `spoofing` | boolean/null | yes | Kết luận detector. |
| `status` | string | yes | `spoofed`, `normal`, `pending`, hoặc `error`. |
| `reference_svid` | integer/null | yes | SVID tham chiếu khi tính double difference. |
| `visible_svids` | array[integer] | yes | Các SVID được đưa vào measurement frame. |
| `suspect_svids` | array[integer] | yes | Các SVID bị detector đánh dấu nghi vấn. |

---

## 5) Schema `gnss.raw.ublox.v1`

Topic:

```text
gnss/{site_id}/{device_id}/raw/ublox/v1
```

Mục đích:

- Gửi từng raw frame UBX/NMEA từ u-blox lên broker.
- Server có thể decode lại `raw_base64` nếu cần replay hoặc lưu raw.
- Message này không chứa kết quả detect.

Ví dụ:

```json
{
  "schema": "gnss.raw.ublox.v1",
  "event_id": "ducanh_user-000000123450",
  "seq": 123450,
  "device_id": "ducanh_user",
  "site_id": "lab_hanoi",
  "frontend": "ublox",
  "source": "rx1",
  "event_time": "2026-04-22T03:29:36.000Z",
  "ingest_time": "2026-04-22T03:29:36.125Z",
  "data": {
    "receiver": "rx1",
    "identity": "RXM-RAWX",
    "tow_s": 123456.0,
    "raw_len": 248,
    "raw_encoding": "base64",
    "raw_base64": "u7YBA..."
  }
}
```

Field trong `data`:

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `receiver` | string | yes | `rx1` hoặc `rx2`. |
| `identity` | string | yes | Tên message parser đọc được, ví dụ `RXM-RAWX`, `NAV-PVT`, `NAV-SAT`, `MON-SPAN`. |
| `tow_s` | number/null | yes | GPS Time Of Week nếu frame có `rcvTow`; nếu không thì `null`. |
| `raw_len` | integer | yes | Độ dài raw frame theo byte trước khi encode base64. |
| `raw_encoding` | string | yes | Luôn là `base64` trong `v1`. |
| `raw_base64` | string | yes | Raw bytes encode base64. |

Mapping với code hiện tại:

- `receiver`, `identity`, `tow_s`, `raw_len`, `raw_base64` lấy từ `RTKLIBStage.normalize_frame()`.
- `seq` lấy từ event wrapper của `ReadSerial`.
- `source` nên bằng `receiver`.

---

## 6) Schema `gnss.raw.sdr.v1`

Topic:

```text
gnss/{site_id}/{device_id}/raw/sdr/v1
```

Mục đích:

- Dành cho SDR frontend sau này.
- Không ép SDR phải giống UBX.
- Có thể gửi metadata-only hoặc gửi samples base64 tùy cấu hình.

Ví dụ:

```json
{
  "schema": "gnss.raw.sdr.v1",
  "event_id": "ducanh_user-000000223450",
  "seq": 223450,
  "device_id": "ducanh_user",
  "site_id": "lab_hanoi",
  "frontend": "sdr",
  "source": "sdr0",
  "event_time": "2026-04-22T03:29:36.000Z",
  "ingest_time": "2026-04-22T03:29:36.125Z",
  "data": {
    "receiver": "sdr0",
    "sample_format": "cf32",
    "center_freq_hz": 1575420000,
    "sample_rate_hz": 4000000,
    "band": "L1",
    "duration_ms": 100,
    "sample_count": 400000,
    "payload_encoding": "base64",
    "samples_base64": "AAAA..."
  }
}
```

Field trong `data`:

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `receiver` | string | yes | SDR source, ví dụ `sdr0`. |
| `sample_format` | string | yes | Format sample, ví dụ `cf32`, `ci16`, `ci8`. |
| `center_freq_hz` | integer | yes | Tần số center theo Hz. |
| `sample_rate_hz` | integer | yes | Sample rate theo Hz. |
| `band` | string/null | yes | Band GNSS, ví dụ `L1`, `L2`, `E1`. |
| `duration_ms` | number | yes | Độ dài snapshot theo ms. |
| `sample_count` | integer | yes | Số sample trong payload. |
| `payload_encoding` | string | yes | `base64` hoặc `none`. |
| `samples_base64` | string/null | yes | Sample bytes encode base64; `null` nếu chỉ gửi metadata. |

---

## 7) Schema `gnss.state.position.v1`

Topic:

```text
gnss/{site_id}/{device_id}/state/position/v1
```

Mục đích:

- Gửi vị trí mới nhất dạng nhẹ hơn `detect/epoch`.
- Phù hợp để server mới subscribe lấy trạng thái gần nhất.
- Có thể publish với `retain=true`.

Ví dụ:

```json
{
  "schema": "gnss.state.position.v1",
  "event_id": "ducanh_user-000000123460",
  "seq": 123460,
  "device_id": "ducanh_user",
  "site_id": "lab_hanoi",
  "frontend": "ublox",
  "source": "rx_pair",
  "event_time": "2026-04-22T03:29:36.000Z",
  "ingest_time": "2026-04-22T03:29:36.125Z",
  "data": {
    "lat_deg": 21.0055,
    "lon_deg": 105.8445,
    "height_m": 12.3,
    "fix_type": "3d",
    "pdop": 1.63,
    "sat_count": 12,
    "avg_cno_dbhz": 42.5
  }
}
```

---

## 8) Schema `gnss.health.v1`

Topic:

```text
gnss/{site_id}/{device_id}/health/v1
```

Mục đích:

- Gửi tình trạng runtime độc lập với measurement.
- Server dùng để cảnh báo mất dữ liệu, backlog cao, hoặc pipeline lỗi.

Ví dụ:

```json
{
  "schema": "gnss.health.v1",
  "event_id": "ducanh_user-health-000000001",
  "seq": 1,
  "device_id": "ducanh_user",
  "site_id": "lab_hanoi",
  "frontend": "mixed",
  "source": "pipeline",
  "event_time": "2026-04-22T03:29:36.000Z",
  "ingest_time": "2026-04-22T03:29:36.000Z",
  "data": {
    "status": "running",
    "ingress_backlog": 0,
    "detect_backlog": 0,
    "raw_backlog": 5,
    "ingress_dropped": 0,
    "detect_dropped": 0,
    "raw_dropped": 0,
    "raw_emitted": 123450,
    "unknown_events": 0,
    "last_seq": 123456,
    "cpu_percent": 35.4
  }
}
```

Field trong `data`:

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `status` | string | yes | `running`, `degraded`, `stopped`, hoặc `error`. |
| `ingress_backlog` | integer | yes | Số event đang chờ ở ingress queue; `-1` nếu không đọc được. |
| `detect_backlog` | integer | yes | Số event đang chờ ở detect queue; `-1` nếu không đọc được. |
| `raw_backlog` | integer | yes | Số event đang chờ ở raw queue; `-1` nếu không đọc được. |
| `ingress_dropped` | integer | yes | Số event bị drop ở ingress. |
| `detect_dropped` | integer | yes | Số event detect bị drop. |
| `raw_dropped` | integer | yes | Số raw event bị drop. |
| `raw_emitted` | integer | yes | Số raw frame đã emit/publish. |
| `unknown_events` | integer | yes | Số event type không nhận diện được. |
| `last_seq` | integer | yes | Sequence lớn nhất node đã thấy. |
| `cpu_percent` | number/null | yes | CPU percent nếu backend đo được. |

---
