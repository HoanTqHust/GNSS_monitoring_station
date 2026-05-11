# README MQTT Data Schema cho server ngoài

## 1) Mục tiêu

File này mô tả cấu trúc JSON dự kiến publish lên MQTT broker để một server khác có thể subscribe và xử lý dữ liệu GNSS realtime.

Schema được thiết kế cho 5 nhóm dữ liệu:

- Raw u-blox frame hiện tại.
- Detect result theo từng epoch đồng bộ giữa 2 receiver.
- Raw SDR frontend trong tương lai.
- Health/runtime metrics của pipeline.
- Command branch để server gửi lệnh xuống local client (chiều ngược lại).

Nguyên tắc thiết kế:

- Không trộn raw data nặng vào message detect nhẹ.
- Mỗi message có envelope chung để server ngoài có thể dedupe, theo dõi sequence gap, và route theo schema.
- Mỗi schema có version `v1`; thay đổi breaking thì tạo `v2`, không sửa ý nghĩa field cũ trong `v1`.
- Đơn vị đo nằm trong tên field, ví dụ `lat_deg`, `cno_dbhz`, `tow_s`, `sample_rate_hz`.
- Field JSON giữ nguyên tiếng Anh/ASCII để ổn định khi parse ở server.

---

## 2) Topic MQTT

Topic đề xuất (client → server):

```text
gnss/{site_id}/{device_id}/raw/ublox/v1
gnss/{site_id}/{device_id}/raw/sdr/v1
gnss/{site_id}/{device_id}/detect/epoch/v1
gnss/{site_id}/{device_id}/state/position/v1
gnss/{site_id}/{device_id}/health/v1
```

Topic command (server → client):

```text
gnss/{site_id}/{device_id}/cmd/init/v1
gnss/{site_id}/{device_id}/cmd/ack/v1
gnss/{site_id}/{device_id}/cmd/{command_type}/v1
```

Ví dụ:

```text
gnss/lab_hanoi/ducanh_user/raw/ublox/v1
gnss/lab_hanoi/ducanh_user/detect/epoch/v1
gnss/lab_hanoi/ducanh_user/health/v1
gnss/lab_hanoi/ducanh_user/cmd/init/v1
gnss/lab_hanoi/ducanh_user/cmd/ack/v1
```

Ý nghĩa:

- `site_id`: điểm đặt thiết bị, ví dụ `lab_hanoi`, `field_test_01`.
- `device_id`: định danh logical của node publish lên MQTT, ví dụ `ducanh_user`.
- `raw/ublox/v1`: từng frame UBX/NMEA từ receiver u-blox.
- `raw/sdr/v1`: raw snapshot hoặc metadata từ SDR frontend trong tương lai.
- `detect/epoch/v1`: kết quả detect cho một epoch đã đồng bộ.
- `state/position/v1`: vị trí mới nhất, có thể publish retain nếu cần server mới vào đọc trạng thái gần nhất.
- `health/v1`: backlog, dropped counter, process status.
- `cmd/init/v1`: client publish khi khởi động để báo ready, retain=true để server mới vào biết client online.
- `cmd/ack/v1`: client publish ack khi nhận được command từ server.
- `cmd/{command_type}/v1`: lệnh server gửi xuống client, server publish QoS 1, retain=false.

Cấu hình QoS bắt buộc:

| Topic suffix | QoS | Retain | Ghi chú |
| --- | --- | --- | --- |
| `detect/epoch/v1` | 1 | false | Dữ liệu chính cho server ngoài đọc trạng thái spoofing. |
| `health/v1` | 1 | false | Dùng để cảnh báo backlog/drop. |
| `state/position/v1` | 1 | true hoặc false | Dùng `retain=true` nếu server cần vị trí mới nhất ngay khi subscribe. |
| `raw/ublox/v1` | 1 | false | Bắt buộc QoS 1 để giảm thất thoát raw frame trên đường MQTT; luôn theo dõi `seq`. |
| `raw/sdr/v1` | 1 | false | Bắt buộc QoS 1 dù payload có thể lớn; cần kiểm soát throughput/backpressure khi triển khai SDR. |
| `cmd/init/v1` | 1 | true | Client publish khi khởi động để server biết client online. |
| `cmd/ack/v1` | 1 | false | Client publish khi nhận và xử lý command. |
| `cmd/{command_type}/v1` | 1 | false | Server publish command xuống client. |

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
    "mqtt_raw_published": 123400,
    "mqtt_raw_failed": 0,
    "mqtt_detect_published": 50,
    "mqtt_detect_failed": 0,
    "mqtt_position_published": 50,
    "mqtt_position_failed": 0,
    "mqtt_health_published": 10,
    "mqtt_health_failed": 0,
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
| `mqtt_raw_published` | integer | yes | Số raw UBX message publish MQTT thành công. |
| `mqtt_raw_failed` | integer | yes | Số raw UBX message publish MQTT thất bại. |
| `mqtt_detect_published` | integer | yes | Số detect epoch message publish MQTT thành công. |
| `mqtt_detect_failed` | integer | yes | Số detect epoch message publish MQTT thất bại. |
| `mqtt_position_published` | integer | yes | Số position state message publish MQTT thành công. |
| `mqtt_position_failed` | integer | yes | Số position state message publish MQTT thất bại. |
| `mqtt_health_published` | integer | yes | Số health message publish MQTT thành công. |
| `mqtt_health_failed` | integer | yes | Số health message publish MQTT thất bại. |
| `cpu_percent` | number/null | yes | CPU percent nếu backend đo được. |

---

## 9) Schema Command (server → client)

### 9.1 Mục đích

Chiều dữ liệu ngược lại: server gửi lệnh xuống local client. Client subscribe topic `cmd/{command_type}/v1` để nhận lệnh và publish `cmd/ack/v1` để xác nhận.

Client tự động publish `cmd/init/v1` (retain=true) khi khởi động để:
- Server biết client đang online.
- Server mới subscribe có thể đọc được trạng thái gần nhất của client.

### 9.2 Schema `gnss.cmd.init.v1`

Topic:

```text
gnss/{site_id}/{device_id}/cmd/init/v1
```

Client publish retain=true khi khởi động để báo ready.

```json
{
  "schema": "gnss.cmd.init.v1",
  "event_id": "test_device-cmd_init-000000000001",
  "seq": 1,
  "device_id": "test_device",
  "site_id": "lab_hanoi",
  "frontend": "ublox",
  "source": "pipeline",
  "event_time": "2026-05-10T14:30:00.000Z",
  "ingest_time": "2026-05-10T14:30:00.000Z",
  "data": {
    "status": "online",
    "ready": true
  }
}
```

Field trong `data`:

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `status` | string | yes | `online` khi client khởi động thành công. |
| `ready` | boolean | yes | `true` khi pipeline sẵn sàng nhận lệnh. |

### 9.3 Schema `gnss.cmd.ack.v1`

Topic:

```text
gnss/{site_id}/{device_id}/cmd/ack/v1
```

Client publish khi nhận và xử lý xong một command.

```json
{
  "schema": "gnss.cmd.ack.v1",
  "event_id": "test_device-cmd_ack-000000000001",
  "seq": 1,
  "device_id": "test_device",
  "site_id": "lab_hanoi",
  "frontend": "ublox",
  "source": "pipeline",
  "event_time": "2026-05-10T14:30:05.000Z",
  "ingest_time": "2026-05-10T14:30:05.000Z",
  "data": {
    "acknowledged": ["cmd_e1", "cmd_e2"]
  }
}
```

Field trong `data`:

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `acknowledged` | array[string] | yes | Danh sách `event_id` của các command đã xử lý thành công. |

### 9.4 Command format (server → client)

Server publish command lên topic:

```text
gnss/{site_id}/{device_id}/cmd/{command_type}/v1
```

```json
{
  "schema": "gnss.cmd.{command_type}.v1",
  "event_id": "server-cmd_e1",
  "seq": 1,
  "device_id": "test_device",
  "site_id": "lab_hanoi",
  "frontend": "ublox",
  "source": "server",
  "event_time": "2026-05-10T14:30:05.000Z",
  "ingest_time": "2026-05-10T14:30:05.000Z",
  "data": {
    "command_id": "cmd_e1",
    "command_type": "{command_type}",
    "params": {}
  }
}
```

Field trong `data`:

| Field | Type | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `command_id` | string | yes | ID unique của command, dùng để client ack. |
| `command_type` | string | yes | Loại command, ví dụ `restart`, `calibrate`, `configure`. |
| `params` | object | yes | Tham số cho command, structure tùy loại command. |

---

## 10) Hướng dẫn cho server subscriber

Server chỉ cần kết quả spoofing:

```text
subscribe gnss/+/+/detect/epoch/v1
```

Server cần raw UBX để replay:

```text
subscribe gnss/+/+/raw/ublox/v1
```

Server cần health:

```text
subscribe gnss/+/+/health/v1
```

Xử lý dedupe:

1. Dùng cặp `(device_id, event_id)` làm key duy nhất.
2. Nếu nhận lại cùng `event_id`, coi là duplicate và bỏ qua hoặc update idempotent.
3. Theo dõi `seq` theo từng `(site_id, device_id, source, schema)`.
4. Nếu `seq` nhảy cách, ghi nhận gap. Gap có thể do queue drop trước publish, process restart, hoặc lỗi producer trước khi message được broker xác nhận.

Xử lý restart:

- Nếu publisher restart và `seq` reset về `1`, server nên bắt đầu một session mới khi `event_id` prefix/session thay đổi.
- Nếu cần truy vết tuyệt đối, thêm `boot_id` vào envelope trong bản `v2` hoặc extension field riêng.

Xử lý status:

- Đọc `data.summary.status` để hiển thị nhanh.
- Đọc `data.summary.spoofing` cho logic machine-readable.
- Đọc từng `data.detectors.*` nếu cần giải thích detector nào kích hoạt.

---

## 11) Mapping từ mẫu ban đầu sang schema mới

Mẫu ban đầu:

```json
{
  "device_id": "ducanh_user",
  "timestamp": "2026-04-22T03:29:36Z",
  "lat": 21.0055,
  "lon": 105.8445,
  "sat_count": 12,
  "avg_cno": 42.5,
  "pdop": 1.63,
  "is_spoofed": false,
  "signals_data": [
    {"prn": "G16", "cno": 48.5}
  ]
}
```

Mapping:

| Field cũ | Field mới |
| --- | --- |
| `device_id` | envelope `device_id` |
| `timestamp` | envelope `event_time` |
| `lat` | `data.position.lat_deg` |
| `lon` | `data.position.lon_deg` |
| `sat_count` | `data.summary.sat_count` |
| `avg_cno` | `data.summary.avg_cno_dbhz` |
| `pdop` | `data.position.pdop` |
| `is_spoofed` | `data.summary.spoofing` |
| `signals_data[].prn` | `data.signals[].prn` |
| `signals_data[].cno` | `data.signals[].cno_dbhz` |

Lý do không giữ schema phẳng:

- Không phân biệt được raw UBX, detect, health, và SDR.
- Không có `seq` để detect mất message.
- Không có `schema` để versioning.
- Không có `source` để phân biệt `rx1`, `rx2`, `rx_pair`, `sdr0`.
- Không có trạng thái `pending` khi detector chưa đủ điều kiện kết luận.

---

## 12) Quy tắc tương thích

Trong `v1`:

- Không đổi tên field đã công bố.
- Không đổi type field đã công bố.
- Không đổi ý nghĩa enum đã công bố.
- Có thể thêm field mới nếu server cũ có thể bỏ qua field không biết.
- Breaking change phải tạo topic/schema `v2`.

Enum khuyến nghị:

```text
frontend: ublox | sdr | mixed
summary.status: spoofed | normal | pending | error
detector.status: spoofed | normal | pending | error
health.status: running | degraded | stopped | error
```

---

## 13) Checklist cho server ngoài

- Subscribe đúng topic theo nhu cầu, không subscribe `raw/#` nếu chỉ cần spoofing status.
- Validate `schema` trước khi parse `data`.
- Dedupe bằng `(device_id, event_id)`.
- Track gap bằng `seq` theo từng `(site_id, device_id, source, schema)`.
- Chấp nhận `null` cho field chưa có giá trị.
- Dùng field có đơn vị rõ ràng: `_deg`, `_m`, `_s`, `_hz`, `_dbhz`.
- Không suy luận spoofing từ mỗi detector riêng lẻ nếu đã có `data.summary`.
- Để nhận command từ server: subscribe `gnss/{site_id}/{device_id}/cmd/{command_type}/v1`.
- Để gửi command: publish lên topic `gnss/{site_id}/{device_id}/cmd/{command_type}/v1` với QoS 1.
- Server nên theo dõi `cmd/ack/v1` để biết command đã được client xử lý.

---

## 14) Cấu hình publisher trong app

App đọc cấu hình MQTT từ environment hoặc `.env`:

```text
MQTT_ENABLED=1
MQTT_HOST=192.168.1.50
MQTT_PORT=1883
MQTT_USERNAME=rw_user
MQTT_PASSWORD=<password cua rw_user>
MQTT_TOPIC_PREFIX=gnss
MQTT_SITE_ID=lab_hanoi
MQTT_DEVICE_ID=ducanh_user
MQTT_QOS=1
MQTT_KEEPALIVE_S=60
MQTT_PUBLISH_TIMEOUT_S=2.0
MQTT_POSITION_RETAIN=0
```

Quy tắc bảo mật:

- Không commit password thật vào git.
- `MQTT_USERNAME` mặc định là `rw_user`.
- `MQTT_PASSWORD` bắt buộc phải được set khi `MQTT_ENABLED=1`.
- Nếu thiếu password hoặc cấu hình sai, app vẫn chạy nhưng MQTT publisher sẽ log lỗi `mqtt_config_invalid` và không publish.

Mapping runtime hiện tại:

| Runtime event | MQTT topic |
| --- | --- |
| `ubx_frame` từ raw queue | `gnss/{site_id}/{device_id}/raw/ublox/v1` |
| `epoch_pair` sau realtime detector | `gnss/{site_id}/{device_id}/detect/epoch/v1` |
| Position rút gọn từ detect message | `gnss/{site_id}/{device_id}/state/position/v1` |
| Queue/MQTT metrics sau raw batch | `gnss/{site_id}/{device_id}/health/v1` |
| Client khởi động (retain) | `gnss/{site_id}/{device_id}/cmd/init/v1` |
| Client ack command | `gnss/{site_id}/{device_id}/cmd/ack/v1` |
