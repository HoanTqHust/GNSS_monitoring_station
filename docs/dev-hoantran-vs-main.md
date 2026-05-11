# Thay đổi của branch `dev/hoantran` so với `main`

## Mục đích

Tài liệu này ghi lại các thay đổi đã có trên branch `dev/hoantran` so với `main`, theo từng commit.  
Khi `dev/hoantran` có commit mới, cập nhật file này bằng cách thêm một mục commit mới ở cuối và cập nhật trạng thái branch.

Phạm vi hiện tại:

- Base/merge-base với `main`: `3595525c4def`
- Head đã ghi nhận của `dev/hoantran`: `72de3b243177`
- Số commit trên `dev/hoantran` so với `main`: 8 commit
- Tổng diff tại thời điểm ghi nhận: 50 files changed, 8383 insertions, 163 deletions

Nguồn đối chiếu:

- `git log --reverse --date=short --pretty=format:'%h %ad %an %s' main..dev/hoantran`
- `git diff --stat main...dev/hoantran`
- `git show --stat --summary <commit>`
- `git show --name-status <commit>`
- Core memory: `docs/context.md`, `docs/codebase-map.md`

## Cập nhật vận hành gần nhất (local, chưa commit)

Ngày cập nhật: `2026-05-06`  
Trạng thái: chưa có commit mới trên `dev/hoantran` trong lần làm việc này, nhưng có thay đổi local để khôi phục runtime.

Nội dung chính:

1. Sửa regression startup do thiếu field MQTT trong `config.py`:
- Lỗi: `AttributeError: type object 'config' has no attribute 'MQTT_ENABLED'`.
- Đã khôi phục `_env_bool` và các biến:
  - `MQTT_ENABLED`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`,
    `MQTT_CLIENT_ID_PREFIX`, `MQTT_TOPIC_PREFIX`, `MQTT_SITE_ID`, `MQTT_DEVICE_ID`,
    `MQTT_QOS`, `MQTT_KEEPALIVE_S`, `MQTT_PUBLISH_TIMEOUT_S`, `MQTT_POSITION_RETAIN`.
- Log debug: `logs/debug/app_start_20260506_0333.log`, `logs/debug/app_start_20260506_0335_after_fix.log`.

2. Khôi phục luồng publish MQTT (Option A) trong `thread/SocketThread.py`:
- Trước khi sửa: runtime vẫn ingest serial nhưng không còn gọi MQTT publish path.
- Đã khôi phục:
  - raw: `raw/ublox/v1`
  - detect: `detect/epoch/v1`
  - position: `state/position/v1`
  - health: `health/v1`
- Đã khôi phục metric MQTT trong queue stats:
  - `mqtt_raw_published/failed`
  - `mqtt_detect_published/failed`
  - `mqtt_position_published/failed`
  - `mqtt_health_published/failed`
- Smoke log xác nhận publish trở lại:
  - `logs/debug/mqtt_restore_optionA_20260506.log` (có nhiều dòng `mqtt_publish_ok`).

3. Kết luận vận hành tại thời điểm cập nhật:
- Data GNSS vẫn ingest bình thường.
- MQTT publish đã hoạt động lại sau khi restore `SocketThread`.
- Luồng runtime hiện tại vẫn là RAM queue (không phải durable queue).

## Cách cập nhật khi có commit mới

1. Lấy danh sách commit mới:

```bash
git log --reverse --date=short --pretty=format:'%h %ad %an %s' 72de3b2..dev/hoantran
```

2. Với mỗi commit mới, đọc file thay đổi:

```bash
git show --stat --summary <commit>
git show --name-status <commit>
git show --unified=2 <commit> -- <file-can-doc-ky>
```

3. Thêm mục mới vào phần "Chi tiết theo commit".
4. Cập nhật lại: head, số commit chênh lệch, tổng diff, và phần feature lớn (nếu có).
5. Nếu commit mới đổi kiến trúc hoặc luồng dữ liệu, cập nhật thêm `docs/context.md` và `docs/codebase-map.md`.

Lưu ý bảo mật:

- Không copy nội dung nhạy cảm từ `.env`, `cookies.txt`, `login.txt`.
- Chỉ ghi nhận rủi ro và file cần review.

## Feature lớn đã thêm trên branch

1. Cấu hình và công cụ thu dữ liệu UBX:
- Đổi default port sang `/dev/ttyACM0`, `/dev/ttyACM1`, `/dev/ttyACM2`
- Đọc serial 115200 baud
- Thêm script record raw UBX và gửi lệnh cấu hình UBX

2. Nền tảng phân tích batch từ notebook/tài liệu nghiên cứu:
- AOA/DD pipeline
- SoS detector
- D3 detector
- Carrier-smoothed pseudorange/Hatch filter
- Pipeline tổng hợp carrier-smoothed double-difference

3. Package `realtime/`:
- Tách measurement builders và detector engines
- Hỗ trợ 4 output: `sos_carrier`, `sos_smoothed_pseudorange`, `d3_carrier`, `d3_smoothed_pseudorange`
- Ghi JSONL theo từng output trong `output_rt/`

4. Tích hợp realtime detector lên dashboard:
- Backend emit `realtime_outputs` trong `update_image`
- Frontend hiển thị 4 card detector
- Thêm script calibrate threshold từ dữ liệu UBX sạch

5. Raw UBX stream và hàng đợi:
- Commit `37727ce` từng dùng SQLite durable queue
- Commit `b2d7b42` thay bằng RAM queue: ingress/detect/raw queue
- Raw frame emit ra frontend qua `raw_data_batch`

6. Dashboard quan sát:
- Bảng raw stream theo `rx1`/`rx2`
- Metrics sequence, backlog, dropped
- Summary chart (Chart.js) cho detector và raw queue

## Chi tiết theo commit

## 1) `ee8653a` - 2026-04-09 - `Pre-code`

Nội dung chính:

- Đổi default serial ports trong `config.py`, thêm `PORT3`.
- Tăng `BUFFER_SAMPLES` từ 30 lên 150.
- `ReadSerialThread` chuyển sang baud 115200, đọc `UBX_PROTOCOL | NMEA_PROTOCOL`.
- Cập nhật text dashboard sang "BKGSD - GNSS Spoofing Detection".
- Chỉnh `draws/UbloxChart.py`:
- Skyplot chỉ vẽ GPS (`gnssId == 0`)
- Tập trung plot carrier phase differences
- Gom cụm hệ số dốc `a` (`delta_a = 0.0001`)
- Cảnh báo spoofing khi cụm có từ 4 vệ tinh
- Thêm công cụ logging/capture: `log.py`, `log_fake.py`, `logs/RawDataLogger.py`, `record_ubx.sh`.
- Thêm `send_command.py` để gửi lệnh UBX config.

File nên đọc:

- `config.py`
- `thread/ReadSerialThread.py`
- `draws/UbloxChart.py`
- `templates/index.html`
- `logs/RawDataLogger.py`
- `record_ubx.sh`
- `send_command.py`

Lưu ý:

- Commit có thêm `.env`, `cookies.txt`, `login.txt` (cần review bảo mật).

## 2) `9f2fbb6` - 2026-04-09 - `[DOCS]: Init docs`

Nội dung chính:

- Khởi tạo tài liệu nền:
- `README.md`
- `docs/context.md`
- `docs/codebase-map.md`
- `docs/structure.md`

File nên đọc:

- `README.md`
- `docs/context.md`
- `docs/codebase-map.md`
- `docs/structure.md`

## 3) `86d349c` - 2026-04-13 - `clone batch`

Nội dung chính:

- Thêm bộ script batch trong `clone/`:
- `aoa_pipeline.py`
- `smoothing_pseudorange.py`
- `sos.py`
- `d3.py`
- `carrier_smoothed_dd_pipeline.py`
- Mục tiêu: phân tích/research offline từ dữ liệu UBX (`Non-SP`, `SP`), chưa phải runtime Flask realtime.

File nên đọc:

- `clone/aoa_pipeline.py` (`sync_by_tow`, `compute_dps`, `run_analysis_block`)
- `clone/carrier_smoothed_dd_pipeline.py` (`match_rawx_epochs`, `update_hatch_state`, `compute_sos`, `detect_d3_spoofed_svids`)
- `clone/sos.py`
- `clone/d3.py`
- `clone/smoothing_pseudorange.py`

## 4) `94800f7` - 2026-04-15 - `skeleton realtime`

Nội dung chính:

- Thêm package `realtime/` và skeleton pipeline realtime:
- `types.py`: `RealtimeEpochPair`, `MeasurementFrame`, `DetectorResult`
- Measurement builders: `carrier`, `smoothed_pseudorange`
- Detector engines: `sos`, `d3`
- `output_writer.py`: ghi `events.jsonl`
- `pipeline.py`: ghép builders + engines + writer
- Thêm `live_runner.py` (standalone serial live), `test_runner.py` (synthetic smoke test).
- `models/SatelliteData.py` thêm `locktime` để phục vụ Hatch filter.

File nên đọc:

- `realtime/types.py`
- `realtime/measurement_builders/common.py`
- `realtime/measurement_builders/carrier.py`
- `realtime/measurement_builders/smoothed_pseudorange.py`
- `realtime/detector_engines/sos.py`
- `realtime/detector_engines/d3.py`
- `realtime/pipeline.py`
- `realtime/output_writer.py`
- `realtime/live_runner.py`
- `realtime/test_runner.py`

## 5) `0b17c98` - 2026-04-23 - `push result to app`

Nội dung chính:

- Thêm `realtime/calibrate_thresholds.py`:
- Đọc cặp UBX sạch
- Match epoch theo TOW
- Ước lượng 4 threshold (SoS + D3 cho carrier/smoothed)
- Xuất JSON và gợi ý env vars
- Đổi rule SoS thành `score < threshold` là spoofing.
- Bắt đầu đẩy `realtime_outputs` lên `update_image`.
- Frontend thêm 4 card detector với trạng thái `Detected/Normal/Pending`.

File nên đọc:

- `realtime/calibrate_thresholds.py`
- `realtime/detector_engines/sos.py`
- `thread/ReadSerialThread.py` (snapshot commit này)
- `thread/SocketThread.py` (snapshot commit này)
- `templates/index.html`

## 6) `37727ce` - 2026-05-04 - `RTKLIB + sqlite`

Nội dung chính:

- Thêm Option B: SQLite durable queue (`thread/DurableRawQueue.py`):
- `raw_events` append-only
- `consumer_offsets` ACK theo consumer
- Replay record chưa ACK
- `ReadSerialThread` ghi `ubx_frame` và `epoch_pair` vào SQLite.
- `SocketThread` đọc batch, emit `raw_data_batch` + `update_image`, rồi ACK.
- `app.py` chuyển từ `multiprocessing.Queue` sang đường DB queue.
- Thêm test: `tests/test_durable_raw_queue.py`.

File nên đọc (vì đã bị xóa ở HEAD):

```bash
git show 37727ce:thread/DurableRawQueue.py
git show 37727ce:tests/test_durable_raw_queue.py
git show 37727ce:thread/ReadSerialThread.py
git show 37727ce:thread/SocketThread.py
```

Lưu ý:

- Đây là luồng lịch sử, không còn là runtime hiện tại.

## 7) `b2d7b42` - 2026-05-04 - `RTKLIB + Ram; Set test value threshold`

Nội dung chính:

- Bỏ SQLite durable queue, chuyển sang RAM queue:
- Ingress queue (`multiprocessing.Queue`)
- Detect queue (`ThreadQueue`)
- Raw queue (`ThreadQueue`)
- Thêm `thread/RTKLIBStage.py` chuẩn hóa payload:
- `normalize_frame`
- `normalize_receiver_state`
- `normalize_epoch_pair`
- `ReadSerialThread` tạo event có `seq/event_type/created_at_utc/payload`.
- `SocketThread` tách router + detect consumer + raw consumer.
- Thêm metrics backlog/drop và backpressure policy.
- `config.py` thêm cấu hình RAM queue và threshold mặc định cho SoS/D3.
- `realtime/pipeline.py` inject threshold từ config.
- Thêm test: `tests/test_ram_queue_flow.py`.
- Thêm tài liệu tiếng Việt: `README_RAW_UBX_STREAM_VI.md`.

File nên đọc:

- `app.py`
- `thread/RTKLIBStage.py`
- `thread/ReadSerialThread.py`
- `thread/SocketThread.py`
- `realtime/pipeline.py`
- `tests/test_ram_queue_flow.py`
- `README_RAW_UBX_STREAM_VI.md`

Lưu ý:

- Runtime hiện tại là RAM-only.
- UI vẫn còn label `Raw UBX Stream (Durable Queue)` mang tính lịch sử.

## 8) `72de3b2` - 2026-05-04 - `update(docs) + add diagram`

Nội dung chính:

- Mở rộng `README_RAW_UBX_STREAM_VI.md`:
- Mô tả đầy đủ `Realtime Detector Outputs`
- Giải thích field/status: `Detected/Normal/Pending/Waiting.../N/A`
- Thêm summary chart trong `templates/index.html` (Chart.js):
- `Detected Count`
- `Normal Count`
- `Pending Count`
- `Raw Queue Pending`
- `Raw Total Dropped`
- Update throttle 1 giây.
- Cập nhật `docs/context.md` và `docs/codebase-map.md`.

File nên đọc:

- `templates/index.html`
- `README_RAW_UBX_STREAM_VI.md`
- `docs/context.md`
- `docs/codebase-map.md`

## Các đoạn code nên đọc trước khi sửa tiếp

Luồng ingest/queue hiện tại:

- `app.py`
- `thread/ReadSerialThread.py`
- `thread/RTKLIBStage.py`
- `thread/SocketThread.py`

Luồng realtime detector:

- `realtime/types.py`
- `realtime/measurement_builders/common.py`
- `realtime/measurement_builders/carrier.py`
- `realtime/measurement_builders/smoothed_pseudorange.py`
- `realtime/detector_engines/sos.py`
- `realtime/detector_engines/d3.py`
- `realtime/pipeline.py`

Frontend dashboard:

- `templates/index.html`
- `README_RAW_UBX_STREAM_VI.md`

Code lịch sử cần xem bằng `git show`:

- `git show 37727ce:thread/DurableRawQueue.py`
- `git show 37727ce:tests/test_durable_raw_queue.py`
- `git show 0b17c98:thread/ReadSerialThread.py`
- `git show 0b17c98:thread/SocketThread.py`

## Validation đã biết

- Test RAM queue hiện tại: `tests/test_ram_queue_flow.py`
- Test durable queue lịch sử (ở commit `37727ce`): `tests/test_durable_raw_queue.py`
- Smoke runner synthetic: `realtime/test_runner.py`

## Rủi ro/điểm cần review tiếp

- Có file nhạy cảm từng được add: `.env`, `cookies.txt`, `login.txt`
- Frontend Socket.IO đang hard-code `http://192.168.5.2:5000`
- D3 default similarity threshold `0.0` có thể làm `score` luôn 0 nếu không override env
- Pipeline hiện tại RAM-only, restart process sẽ mất queue state
- Chưa có end-to-end test đầy đủ cho live spoofing pipeline
