# Context

## Overview

This repository implements a real-time GNSS monitoring system focused on comparing carrier phase behavior across two u-blox receivers to identify anomalies that may indicate spoofing.

## Domain Problem

- Read UBX data from multiple GNSS receivers
- Synchronize data pairs between two devices by observation time
- Compute carrier phase differences over a sliding window
- Display visual analysis results through a web dashboard
- Mark spoofing status based on per-satellite trend behavior

## Current Data Flow

1. `thread/ReadSerialThread.py` reads serial data from two receivers.
2. `RXM-RAWX`, `NAV-PVT`, `NAV-SAT`, and `MON-SPAN` messages are parsed and stored temporarily.
3. `thread/RTKLIBStage.py` normalizes parsed u-blox messages into RTKLIB-stage payloads.
4. `thread/ReadSerialThread.py` publishes normalized events into one RAM ingress queue (`multiprocessing.Queue`).
5. `thread/SocketThread.py` routes events from ingress queue into two RAM consumer queues:
   - detect queue (`epoch_pair`)
   - raw queue (`ubx_frame`)
6. Detect consumer runs realtime detectors and plotting logic from `epoch_pair`.
7. Raw consumer emits batched raw frame telemetry to the frontend.
8. The backend emits:
   - `update_image` (plots + detector outputs)
   - `raw_data_batch` (raw UBX stream batches)

## Main Functional Components

- `app.py`: web application entry point
- `thread/ReadSerialThread.py`: serial ingestion and RAM ingress queue producer
- `thread/RTKLIBStage.py`: RTKLIB-stage normalization adapter
- `draws/UbloxChart.py`: numeric processing and plot generation
- `thread/SocketThread.py`: RAM router + detect/raw consumer workers
- `logs/RawDataLogger.py`: raw UBX file logging helper

## Operating Assumptions

- The runtime environment is Linux with available serial devices under `/dev/ttyACM*`.
- The main data ingestion flow expects u-blox receivers to produce UBX data at `115200` baud.
- The dashboard is expected to run on the same host or within the same local network as the server.

## Important Findings From Source Review

- The runtime code requires `pyubx2`, but that package is not listed in `requirements.txt`.
- The frontend connects to Socket.IO through a fixed endpoint, `192.168.5.2:5000`, instead of using the current host dynamically.
- `requirements.txt` contains many packages that do not appear to be directly used by the source code currently present in the repo.
- The repository now includes deterministic unit tests for RAM queue routing helpers, but still lacks broad end-to-end automated tests for the full spoofing pipeline.
- The repo contains potentially sensitive files such as `.env`, `cookies.txt`, and `login.txt`.

## Recent Architectural Addition

- A new `realtime/` package now provides a skeleton realtime spoofing pipeline split into two layers:
  - `measurement_builders`: builds `carrier` and `smoothed_pseudorange` DD frames from normalized epoch pairs
  - `detector_engines`: runs `SoS` and `D3` detector skeletons against those measurement frames
- The realtime skeleton writes separated JSONL outputs under `output_rt/` for:
  - `sos_carrier`
  - `sos_smoothed_pseudorange`
  - `d3_carrier`
  - `d3_smoothed_pseudorange`
- This layer is intentionally not wired into `app.py` or the serial reader yet; it is a standalone foundation for later integration with live UBX ingestion and MQTT/REST publishing.
- `realtime/test_runner.py` now provides a small synthetic test runner that exercises the pipeline and verifies the four output branches are created.
- `realtime/live_runner.py` now provides a standalone live serial runner for Option A:
  - opens `PORT1` and `PORT2`
  - pairs realtime epochs by `rcvTow`
  - feeds normalized epoch pairs into the realtime pipeline
  - writes live detector output into `output_rt/`
- The realtime runners now prepend the repo root to `sys.path` so they work both as:
  - `python3 -m realtime.live_runner`
  - `python3 realtime/live_runner.py`
- The web runtime now computes realtime detector outputs inside `thread/SocketThread.py` from RAM-routed `epoch_pair` records and emits them to `templates/index.html` as `realtime_outputs`.
- `realtime/calibrate_thresholds.py` now calibrates initial thresholds from clean recorded UBX pairs and emits four threshold values for the current realtime stack:
  - `sos_carrier`
  - `sos_smoothed_pseudorange`
  - `d3_carrier`
  - `d3_smoothed_pseudorange`

## Architecture Decision Note (2026-04-23, Pre-Implementation)

- Before Option B implementation, the web runtime could drop data under load because:
  - `thread/ReadSerialThread.py` explicitly evicts old queue items when `data_queue` is full.
  - `thread/ReadSerialThread.py` also truncates `combined_samples` to `BUFFER_SAMPLES`.
  - `thread/SocketThread.py` consumes one queue item at a time and performs plotting/encoding before emitting, which can lag ingestion.
- Proposed direction for "no raw data loss" requirements:
  - split ingestion from detection/visualization with a durable raw-ingest stage
  - treat `RTKLIB` as one downstream consumer, not as the only buffer guarantee
  - add sequence-numbered raw frame envelopes with enqueue/dequeue lag metrics
- Practical guarantee model:
  - in-memory queue alone gives best-effort delivery
  - for process-crash-safe delivery, persist raw frames first (WAL/disk spool/Kafka/Redis Streams), then fan out to detect/app pipelines

## Option B Implementation (2026-04-23, Historical Superseded)

- Implemented durable ingest with SQLite WAL queue in `thread/DurableRawQueue.py`:
  - append-only `raw_events` table (sequence ordered)
  - per-consumer `consumer_offsets` ACK table
  - replay behavior when records are not ACKed
- Serial ingestion now writes to durable queue in `thread/ReadSerialThread.py`:
  - `ubx_frame` records for every parsed UBX frame with full raw payload in base64
  - `epoch_pair` records for synchronized RAWX/NAV pairs used by detectors
- Socket consumer now reads from durable queue in `thread/SocketThread.py`:
  - processes `epoch_pair` records to run realtime detectors and emit `update_image`
  - emits raw frame batches to frontend with `raw_data_batch`
  - ACKs queue offsets only after successful processing/emission path
- App bootstrap changed in `app.py`:
  - removed in-memory `multiprocessing.Queue(maxsize=1000)` path
  - producer and consumer now share durable queue DB path from config
- New config keys in `config.py`:
  - `RAW_QUEUE_DB_PATH`
  - `RAW_QUEUE_CONSUMER_ID`
  - `RAW_QUEUE_BATCH_SIZE`
  - `RAW_QUEUE_POLL_INTERVAL`
  - `RAW_EMIT_BATCH_SIZE`
- Frontend additions in `templates/index.html`:
  - realtime raw stream panel for `raw_data_batch`
  - sequence/duplicate/gap metrics to observe at-least-once behavior
  - receiver-split presentation (`rx1`, `rx2`) with per-row indexed tables (`idx`, `seq`, `timestamp`, `identity`, `tow_s`, `raw_len`)

## Validation Evidence (2026-04-23)

- Deterministic unit tests added:
  - `tests/test_durable_raw_queue.py`
- Executed:
  - `python3 -m unittest discover -s tests -p 'test_durable_raw_queue.py' -v`
- Result:
  - 3 tests passed (`ack` persistence, unacked replay, independent consumer offsets)

## Option C RAM Queue Implementation (2026-05-04)

- Removed SQLite runtime dependency from the live ingestion path.
- Added RTKLIB-stage normalization adapter in `thread/RTKLIBStage.py`.
- Implemented RAM pipeline:
  - ingress queue (`multiprocessing.Queue`) for producer process output
  - router thread fan-out to detect queue and raw queue
  - detect consumer thread for `epoch_pair` -> realtime detectors -> `update_image`
  - raw consumer thread for `ubx_frame` -> `raw_data_batch`
- Added bounded queue backpressure strategy in RAM mode:
  - detect/raw queues use `drop-oldest` on overflow
  - ingress queue uses `drop-new` with warning logs on overflow
- Updated tests:
  - added `tests/test_ram_queue_flow.py`
  - removed `tests/test_durable_raw_queue.py` from active runtime validation scope
- Added Vietnamese raw stream data dictionary:
  - `README_RAW_UBX_STREAM_VI.md`
  - covers event schema, UI metrics fields, and identity group meanings

## Operational Debug Finding (2026-05-04)

- Realtime detector cards in the dashboard can stay in `Pending` even when data is flowing.
- Root cause in current runtime:
  - `realtime/pipeline.py` initializes SoS/D3 engines without thresholds.
  - SoS engine sets `spoofing=None` when threshold is `None`.
  - D3 engine sets `spoofing=None` when similarity threshold is `None`.
  - Frontend maps `spoofing===true/false` to `Detected/Normal`; all other values render `Pending`.
- Evidence captured in:
  - `logs/debug/realtime_pending_20260504.log`
  - `output_rt/*/events.jsonl` (`"threshold": null`, `"spoofing": null`)

## Threshold Test Wiring (2026-05-04)

- Added runtime threshold wiring so realtime detector cards can leave `Pending` state during test runs.
- `config.py` now defines test defaults (overridable via env):
  - `SOS_CARRIER_THRESHOLD=0.09`
  - `SOS_SMOOTHED_PSEUDORANGE_THRESHOLD=1.10`
  - `D3_CARRIER_SIMILARITY_THRESHOLD=0.0`
  - `D3_SMOOTHED_PSEUDORANGE_SIMILARITY_THRESHOLD=0.0`
  - `D3_MIN_CLUSTER_SIZE=3`
- `realtime/pipeline.py` now injects these values into SoS/D3 detector engines at construction time.

## Frontend Summary Chart (2026-05-04)

- Added one combined chart block in `templates/index.html` to summarize two existing text sections:
  - `Realtime Detector Outputs`
  - `Raw UBX Stream`
- Existing text metrics/cards remain unchanged for detailed inspection.
- Chart implementation details:
  - uses Chart.js line chart with dual Y-axes
  - realtime series: `Detected Count`, `Normal Count`, `Pending Count`
  - raw stream series: `Raw Queue Pending`, `Raw Total Dropped`
  - update throttle at `1s` to avoid UI overload under high-rate stream

## Vietnamese Realtime/Raw Stream README (2026-05-04)

- `README_RAW_UBX_STREAM_VI.md` now documents both dashboard data surfaces:
  - `Realtime Detector Outputs`
  - `Raw UBX Stream`
- The realtime detector section describes:
  - `realtime_outputs` map keys (`sos_carrier`, `sos_smoothed_pseudorange`, `d3_carrier`, `d3_smoothed_pseudorange`)
  - each detector output field (`tow_s`, `score`, `threshold`, `spoofing`, `reference_svid`, `visible_svids`, `suspect_svids`, `measurement_name`, `detector_name`)
  - frontend status mapping (`Detected`, `Normal`, `Pending`, `Waiting...`, `N/A`)
  - current SoS/D3 score and threshold rules
- This is a documentation-only update; no runtime schema or frontend behavior changed.

## D3 Score Zero Finding (2026-05-04)

- Current D3 runtime defaults are `D3_CARRIER_SIMILARITY_THRESHOLD=0.0` and `D3_SMOOTHED_PSEUDORANGE_SIMILARITY_THRESHOLD=0.0` unless env overrides are set.
- D3 computes `score` as `len(suspect_svids)`.
- `suspect_svids` is populated only when a pair of DD values satisfies `abs(dd_a - dd_b) <= similarity_threshold`.
- With a threshold of `0.0`, D3 only counts exactly equal floating-point DD values, so `suspect_svids` can remain empty and `score` stays `0.0` even when many SVIDs are visible.
- Observed output evidence in `output_rt/d3_*/events.jsonl`: `threshold: 0.0`, `suspect_svids: []`, `score: 0.0`.

## Branch Delta Documentation (2026-05-05)

- Added `docs/dev-hoantran-vs-main.md` as the Vietnamese branch-change ledger for `dev/hoantran` compared with `main`.
- Current recorded comparison scope:
  - merge-base/main: `3595525c4def`
  - `dev/hoantran` head: `72de3b243177`
  - 8 commits from `main..dev/hoantran`
- The file is intended to be updated whenever `dev/hoantran` receives a new commit.
- It records each commit's feature-level changes, important files/functions to read, historical superseded code, validation references, and current risks such as sensitive files and RAM-only queue behavior.

## MQTT Telemetry Architecture Note (2026-05-05)

- Planned MQTT output should preserve the current internal split between raw transport data and derived detector data:
  - `raw.ubx_frame.v1` for each parsed u-blox frame, with raw bytes carried as base64 and receiver/message identity metadata.
  - `raw.sdr_frame.v1` later for SDR frontend snapshots or sample metadata, using the same event envelope.
  - `detect.epoch_result.v1` for one synchronized epoch result, carrying position quality, signal summaries, and detector outputs.
  - `device.health.v1` for queue/backpressure/runtime health independent of GNSS measurement content.

- All MQTT messages should use one stable event envelope with explicit schema version, event id, source, event time, device id, frontend type, sequence number, and payload type.
- Heavy raw payloads must not be mixed into lightweight detect messages. Subscribers that only need spoofing status should subscribe to detect topics without receiving raw UBX/SDR bytes.
- The existing single flat sample shape with `lat`, `lon`, `sat_count`, `avg_cno`, `pdop`, `is_spoofed`, and `signals_data` is suitable only as a dashboard summary, not as the canonical broker schema.
- Added `README_MQTT_DATA_SCHEMA_VI.md` as the Vietnamese MQTT contract document with diacritics for external server subscribers.
- MQTT schema now requires QoS 1 for every topic family; subscribers must still deduplicate by `event_id` and track `seq` gaps because QoS 1 is at-least-once delivery and does not protect data lost before publish.
- Implemented initial MQTT publishing path:
  - `telemetry/mqtt_schema.py` builds `raw/ublox`, `detect/ublox`, `state/position`, and `health` JSON envelopes.
  - `telemetry/mqtt_publisher.py` publishes JSON through paho-mqtt with QoS 1 and waits for publish acknowledgement.
  - `thread/SocketThread.py` publishes raw UBX messages from the raw consumer, detect/position messages from the detect consumer, and health messages after raw batch emission.
  - MQTT config is environment-driven in `config.py`; `MQTT_USERNAME` defaults to `rw_user`, but `MQTT_PASSWORD` has no default and must be supplied outside git.
  - `paho-mqtt==2.1.0` is now listed in `requirements.txt`.

## Logging Expansion (2026-05-06)

- `app.py` now adds a dedicated `all.log` file handler at startup that records all runtime logs (`DEBUG` and above) without MQTT-only filtering.
- Existing `mqtt.log` behavior is kept, so MQTT-focused logs still remain isolated for transport debugging while `all.log` is used for full pipeline debugging.

## Raw Queue Drop Finding (2026-05-06)

- Evidence from `all.log` shows sustained raw-queue overflow with `queue_drop_oldest drop_key=raw_dropped`.
- During one run window:
  - first drop at `2026-05-06 02:55:42,582`
  - last drop at `2026-05-06 02:56:55,577`
  - total `raw_dropped` warnings: `6642`
  - `detect_dropped`: `0`
  - `ingress_queue_full_drop`: `0`
- This confirms drops are happening at the raw fan-out queue stage, not ingress saturation.
- Current RAM queue limits are bounded by item count (`ingress=5000`, `detect=2000`, `raw=5000`), so queue-full drop can occur even when host RAM is still available.

## Startup Regression Fix (2026-05-06)

- Captured startup failure log in `logs/debug/app_start_20260506_0333.log`:
  - `AttributeError: type object 'config' has no attribute 'MQTT_ENABLED'` from `app.py`.
- Root cause:
  - `config.py` no longer defined MQTT config attributes while `app.py` and `thread/SocketThread.py` still referenced them.
- Fix:
  - restored `_env_bool` helper and MQTT fields in `config.py`:
    - `MQTT_ENABLED`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`,
      `MQTT_CLIENT_ID_PREFIX`, `MQTT_TOPIC_PREFIX`, `MQTT_SITE_ID`, `MQTT_DEVICE_ID`,
      `MQTT_QOS`, `MQTT_KEEPALIVE_S`, `MQTT_PUBLISH_TIMEOUT_S`, `MQTT_POSITION_RETAIN`.
- Verification:
  - `python3 -m py_compile config.py app.py thread/SocketThread.py` passed.
  - startup smoke log `logs/debug/app_start_20260506_0335_after_fix.log` shows app booting and serial enqueue activity without the AttributeError.

## MQTT Publish Missing (2026-05-06)

- Runtime is active and serial ingestion is running (`epoch_pair_enqueued` continues in `all.log` around `03:44` to `03:48` UTC).
- However, current `thread/SocketThread.py` no longer imports or calls MQTT publisher/schema functions.
- Result:
  - app still emits data to frontend (`raw_data_batch`, `update_image`) via Socket.IO
  - no new MQTT publish events are generated in current runtime
  - latest historical `mqtt_publish_ok` entries remain at approximately `2026-05-06 03:23:16` in `mqtt.log`.

## MQTT Publish Path Restored (2026-05-06)

- Re-enabled MQTT publishing in `thread/SocketThread.py` for:
  - raw stream (`raw/ublox/v1`) in `raw_consumer_thread`
  - detect stream (`detect/ublox/v1`) and position (`state/position/v1`) in `detect_consumer_thread`
  - health stream (`health/v1`) after raw batch emit
- Restored MQTT metric counters in runtime queue stats:
  - `mqtt_raw_published/failed`
  - `mqtt_detect_published/failed`
  - `mqtt_position_published/failed`
  - `mqtt_health_published/failed`
- Validation:
  - `python3 -m py_compile thread/SocketThread.py app.py config.py` passed
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v` passed
  - smoke run log `logs/debug/mqtt_restore_optionA_20260506.log` shows sustained:
    - `mqtt_publish_ok ... raw/ublox/v1`
    - `mqtt_publish_ok ... health/v1`

## Documentation Intent

The `docs/` directory exists to:

- help new developers understand the repo quickly
- identify the main entry points and edit surfaces
- preserve operational knowledge for future work

## Verification Scope

The statements in this file were derived directly from:

- `app.py`
- `config.py`
- `thread/ReadSerialThread.py`
- `thread/SocketThread.py`
- `draws/UbloxChart.py`
- `models/*.py`
- `logs/RawDataLogger.py`
- `templates/*.html`

No statement in this document is based on external assumptions beyond the current source tree.

## MQTT Runtime Check (2026-05-06)

- Runtime config check from `config.py` in current environment reports:
  - `MQTT_ENABLED=True`
  - `MQTT_HOST=localhost`
  - `MQTT_PORT=1883`
  - `MQTT_USERNAME=rw_user`
  - `MQTT_PASSWORD` is not set.
- Validation rule in `telemetry/mqtt_publisher.py` requires non-empty `MQTT_PASSWORD` when MQTT is enabled.
- Practical effect:
  - publisher marks config invalid (`mqtt_config_invalid`) and skips publish attempts until password is provided via env.
- Deterministic validation:
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v`
  - result: 4 tests passed.

## MQTT Host Update (2026-05-06)

- Updated runtime `.env` to set `MQTT_HOST=192.168.1.50` so the app publishes to LAN broker instead of local-only host reference.
- Updated `README_MQTT_DATA_SCHEMA_VI.md` publisher config example to use `MQTT_HOST=192.168.1.50` for consistency with LAN broker deployment.

## MQTT Dedicated Log File (2026-05-06)

- Added MQTT-focused logging setup in `app.py`:
  - create `mqtt.log` at repo root
  - attach a dedicated file handler with filter rules that keep only MQTT-related records (by logger name/message content)
  - include startup MQTT runtime config log (`enabled`, `host`, `port`, `username`, `password_set`) without exposing plaintext password

## MQTT Connect Timeout Finding (2026-05-06)

- Observed runtime errors in `mqtt.log`:
  - `mqtt_publish_error ... socket.timeout: timed out` when connecting to `192.168.1.50:1883`.
- Network evidence from app host:
  - host IP: `192.168.5.2/24`
  - route to broker: `192.168.1.50 via 192.168.5.1`
  - direct TCP test to `192.168.1.50:1883` times out
  - ping to `192.168.1.50` has 100% packet loss
- Conclusion:
  - failure occurs before MQTT auth/ACL stage; root cause is network reachability path (routing/firewall/broker bind) between app host and `192.168.1.50`.

## Pending Backlog RCA (2026-05-20)

- Symptom:
  - dashboard `pending_events` grows quickly during runtime.
- Log evidence (startup `2026-05-20 09:28 UTC`):
  - producer rate estimate from `epoch_pair_enqueued seq` delta:
    - first sample: `09:28:09.842 seq=69`
    - last sample: `09:30:59.298 seq=40934`
    - derived ingest rate: about `241 events/s`.
  - MQTT raw consumer publish rate from `mqtt_publish_ok ... raw/ublox/v1`:
    - about `10.41 raw messages/s` average in the same window.
  - health publish rate is also about `10.41 messages/s`, indicating one extra MQTT publish per raw flush.
- Deterministic code-level repro:
  - `MqttSubscribeSettings` currently has no `validate()` method.
  - `MqttCommandSubscriber.__init__()` calls `self.settings.validate()` and raises:
    - `AttributeError: 'MqttSubscribeSettings' object has no attribute 'validate'`.
  - effect: detect consumer setup stops before `detect_consumer_started` log.
- Root causes:
  - raw path bottleneck: synchronous QoS1 MQTT publish + wait for every raw frame, plus health publish every flush, limits consumer throughput far below ingest rate.
  - detect path unavailable: subscriber init crash prevents detect consumer loop from running, so detect queue backlog contributes to `pending_events`.

## Pending Backlog Fix (2026-05-20)

- Implemented fixes:
  - Added `MqttSubscribeSettings.validate()` in `telemetry/mqtt_subscriber.py` to stop `AttributeError` during detect-consumer initialization.
  - Added optional `wait_for_ack` flag to `MqttTelemetryPublisher.publish()` and switched raw UBX publish path to `wait_for_ack=False` in `thread/SocketThread.py` so raw consumer does not block on per-frame ACK waits.
  - Added `RAM_HEALTH_PUBLISH_INTERVAL` in `config.py` (default `1.0s`) and throttled health-topic publishing in raw consumer loop to reduce extra MQTT load.
- Validation:
  - `python3 -m py_compile telemetry/mqtt_subscriber.py telemetry/mqtt_publisher.py thread/SocketThread.py config.py tests/test_mqtt_telemetry.py`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v` -> `6 passed`
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v` -> `3 passed`
  - deterministic repro script now shows:
    - `has_validate True`
    - `subscriber_init_ok`

## Raw MQTT Worker Queue Split (2026-05-20)

- Implemented step 2 to decouple raw MQTT publishing from `raw_consumer_thread`:
  - `thread/SocketThread.py` now creates `mqtt_publish_queue` and starts `raw_mqtt_publish_worker` thread.
  - `raw_consumer_thread` only enqueues raw events for MQTT via `_enqueue_raw_mqtt_publish()` and continues UI batch emission independently.
  - Worker thread performs `_publish_raw_ublox()` calls.
- New runtime config:
  - `RAM_RAW_MQTT_QUEUE_SIZE` in `config.py` (default `200000`).
- New observability metric:
  - `mqtt_raw_queue_dropped` added to runtime metrics and `health/v1` payload.
- Validation:
  - `python3 -m py_compile thread/SocketThread.py telemetry/mqtt_schema.py config.py tests/test_ram_queue_flow.py tests/test_mqtt_telemetry.py`
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v` -> `4 passed`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v` -> `6 passed`

## Command Topic Contract Alignment (2026-05-20)

- Updated MQTT command subscriber path to match README command contract:
  - subscribe pattern is now `gnss/{site_id}/{device_id}/cmd/+/+/v1` (covers current `cmd/ublox/{action}/v1`).
  - command topic parsing now extracts `command_type` from `cmd/{command_type}/v1` suffix (`ublox/configure`, `ublox/restart`, ...).
  - invalid topic shapes (for example `cmd/configure/v1`) are rejected with explicit `invalid_command_topic` error.
- This preserves existing behavior for:
  - `cmd/init/v1` publish on startup (retain=true)
  - `cmd/ack/v1` publish after command handling
- Validation:
  - `python3 -m py_compile telemetry/mqtt_subscriber.py tests/test_mqtt_telemetry.py`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v` -> `9 passed`
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v` -> `4 passed`

## Command Observability Logs (2026-05-20)

- Added explicit log markers for command branch observability:
  - `cmd_init_published` when client publishes `cmd/init/v1` at startup.
  - `cmd_ack_published` when client publishes `cmd/ack/v1` after processing a server command.
- Validation:
  - `python3 -m py_compile thread/SocketThread.py telemetry/mqtt_subscriber.py`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v` -> `9 passed`

## Legacy Command Topic Compatibility (2026-05-20)

- MQTT command subscriber now supports both topic shapes:
  - `gnss/{site_id}/{device_id}/cmd/{command_type}/v1` (one-level)
  - `gnss/{site_id}/{device_id}/cmd/{namespace}/{command}/v1` (nested, current ublox shape)
- Added one-level handler aliases:
  - `reboot` -> restart handler
  - `set_rate` -> configure handler
  - `start`, `stop`, `status` -> matching handlers
- This keeps backward compatibility with server topics like:
  - `.../cmd/reboot/v1`
  - `.../cmd/set_rate/v1`
- Validation:
  - `python3 -m py_compile telemetry/mqtt_subscriber.py tests/test_mqtt_telemetry.py`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v` -> `10 passed`

## Command ID Fallback for Server Payloads (2026-05-20)

- Subscriber now falls back to `event_id` when `data.command_id` is missing:
  - `command_id = data.command_id or event_id`
- This allows client to process and ACK legacy server messages like:
  - `cmd/set_rate/v1` where payload contains `event_id` but no `data.command_id`.
- ACK behavior remains unchanged:
  - `cmd/ack/v1` publishes `acknowledged: [command_id]`, now using `event_id` fallback when needed.
- Validation:
  - `python3 -m py_compile telemetry/mqtt_subscriber.py tests/test_mqtt_telemetry.py`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v` -> `11 passed`

## Skip Internal Command Topics (2026-05-20)

- Subscriber now ignores internal command branch topics:
  - `cmd/init/v1`
  - `cmd/ack/v1`
- Reason:
  - prevent self-processing loop where client receives its own `cmd/ack` and emits another ACK with `unknown_command_type:ack`.
- Validation:
  - `python3 -m py_compile telemetry/mqtt_subscriber.py tests/test_mqtt_telemetry.py`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v` -> `13 passed`

## SDR Flow Analysis (2026-06-05)

- Added `docs/sdr-flow-analysis.md` documenting the current bladeRF SDR path:
  - `app.py` exposes `/sdr`, `/sdr/latest_bmp`, `/sdr/bmp/<filename>`, and `/sdr/stop`.
  - `SDRThread` starts `reader_process`, `plotter_process`, and a result consumer thread.
  - `reader_process` reads bladeRF SC16_Q11 samples, converts them to `complex64`, accumulates 8 chunks of 8192 samples, and pushes one 65536-sample frame about every 0.1 seconds.
  - `plotter_process` creates a BMP spectrogram, saves it under `BKDATASET/`, runs the ResNet18 classifier, and emits `sdr_classify` through Socket.IO.
  - `templates/sdr.html` receives class/probability data through Socket.IO but polls `/sdr/latest_bmp` every 500 ms for the actual image.
- Important finding:
  - `thread/SDRThread.py` currently hardcodes `60 MHz`, FFT `512/384`, dB power, custom colormap, BMP, raw 0-1 preprocessing, and labels `Clean/Narrowband/Pulsed/Swept/Multi-tone/Partial-band`.
  - `SDR/README_bladerf_integration.md` describes the model contract as `5 MHz`, 8192 samples, `iq.real`, STFT `256/128`, magnitude, matplotlib default rendering, PNG, ImageNet normalization, and labels `DME/NB/NoJam/SingleAM/SingleChirp/SingleFM`.
  - Because these contracts conflict, SDR jamming detection should be treated as unverified until the runtime preprocessing and model label map are reconciled.

## SDR Raw/MQTT Design Note (2026-06-05)

- User requested feasibility for:
  - saving raw bladeRF data as `.bin` files and sending those files through EMQX/MQTT
  - sending base64-encoded spectrum images through EMQX/MQTT when jamming is detected
- Feasible with bounded snapshots/chunking, not as continuous full-rate MQTT payloads:
  - `5 Msps * 4 bytes/sample = 20 MB/s` raw SC16_Q11, about `26.7 MB/s` after base64.
  - current SDR runtime hardcoded `60 Msps` would be about `240 MB/s` raw, about `320 MB/s` after base64.
- Recommended architecture:
  - add SDR raw capture before `Receiver.parse_samples()` so `.bin` stores original interleaved little-endian int16 I/Q (`SC16_Q11`) plus JSON metadata.
  - publish raw SDR snapshots on `gnss/{site_id}/{device_id}/raw/sdr/v1` as chunked messages with `file_id`, `chunk_index`, `chunk_count`, `chunk_base64`, `sha256`, sample-rate/frequency/gain metadata, and QoS 1.
  - publish jamming results on a separate lightweight detect topic, with the spectrum image base64 included only when `class != Clean` and confidence passes a configured threshold.
  - keep a dedicated SDR MQTT worker queue with drop/failed/published metrics so heavy SDR payloads cannot block the UI or GNSS detect pipeline.

## SDR Snapshot Option A Decision (2026-06-05)

- User selected Option A for SDR raw publishing:
  - keep a local ring buffer of recent bladeRF raw samples
  - when jamming is detected, publish a bounded forensic snapshot instead of continuous raw SDR streaming
  - default target window is `1s` before detection and `2s` after detection
- Implementation should use explicit runtime config:
  - `SDR_SNAPSHOT_PRE_SECONDS`
  - `SDR_SNAPSHOT_POST_SECONDS`
  - `SDR_JAMMING_CONFIDENCE_THRESHOLD`
  - `SDR_MQTT_CHUNK_BYTES`
  - `SDR_SNAPSHOT_DIR`
  - `SDR_SNAPSHOT_COOLDOWN_SECONDS`
- Raw `.bin` snapshot format should be original bladeRF SC16_Q11 interleaved little-endian int16 I/Q, not normalized `complex64`.
- MQTT publishing should be chunked on `raw/sdr/v1`; jamming detection and spectrum image should be separate from raw chunks so subscribers can avoid heavy raw payloads.
- MQTT topic assignment before implementation:
  - raw SDR `.bin` snapshot chunks: `gnss/{site_id}/{device_id}/raw/sdr/v1`
  - SDR detection result plus spectrum image base64: `gnss/{site_id}/{device_id}/detect/sdr/v1`
  - health/metrics for SDR MQTT queue should remain under the existing `health/v1` family or extend it with SDR-specific counters.

## SDR Snapshot MQTT Implementation (2026-06-05)

- Implemented Option A runtime support:
  - `SDR/src/receiver.py` now has `receive_with_raw()` returning both normalized `complex64` samples and original SC16_Q11 raw bytes.
  - `thread/SDRThread.py` now sends `{samples, raw_bytes, captured_at_utc}` from reader to plotter.
  - Plotter keeps a ring buffer for pre-detection raw frames.
  - On jamming trigger (`class != Clean/Unknown` and `confidence >= SDR_JAMMING_CONFIDENCE_THRESHOLD`), plotter starts a pending snapshot, collects post-detection frames, saves `{file_id}.bin` and `{file_id}.json` in `SDR_SNAPSHOT_DIR`, and forwards one MQTT event to the main process.
  - `SDRThread` now has a dedicated SDR MQTT worker queue; it publishes:
    - `detect/sdr/v1` once per SDR threat snapshot, including class, confidence, probabilities, spectrum PNG base64, and snapshot metadata.
    - `raw/sdr/v1` chunk messages for the `.bin` snapshot using `SDR_MQTT_CHUNK_BYTES`.
- Added runtime config:
  - `SDR_SNAPSHOT_PRE_SECONDS`
  - `SDR_SNAPSHOT_POST_SECONDS`
  - `SDR_JAMMING_CONFIDENCE_THRESHOLD`
  - `SDR_MQTT_CHUNK_BYTES`
  - `SDR_SNAPSHOT_DIR`
  - `SDR_SNAPSHOT_COOLDOWN_SECONDS`
  - `SDR_MQTT_QUEUE_SIZE`
- Added schema builders:
  - `build_raw_sdr_snapshot_chunk_message()`
  - `build_detect_sdr_message()`
  - `build_detect_ublox_message()`
- Updated `README_MQTT_DATA_SCHEMA_VI.md` with the server-facing topic contract and chunk reassembly rules.
- Validation:
  - `python3 -m py_compile config.py SDR/src/receiver.py telemetry/mqtt_schema.py thread/SDRThread.py tests/test_mqtt_telemetry.py`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v` -> `15 passed`
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v` -> `4 passed`

## MQTT Detect Topic Rename (2026-06-05)

- Renamed public detect topics for source clarity and SDR extensibility:
  - u-blox/GNSS receiver pair detect: `gnss/{site_id}/{device_id}/detect/ublox/v1`
  - SDR AI detect: `gnss/{site_id}/{device_id}/detect/sdr/v1`
- Rationale:
  - SDR may detect both jamming and spoofing, so `detect/sdr_jamming/v1` was too narrow.
  - `detect/ublox/v1` is easier for server subscribers to distinguish from SDR than `detect/epoch/v1`.
- Schema names now match topics:
  - `gnss.detect.ublox.v1`
  - `gnss.detect.sdr.v1`
- `telemetry/mqtt_schema.py` now exposes:
  - `build_detect_ublox_message()`
  - `build_detect_sdr_message()`
  - `build_detect_epoch_message` remains as an alias for compatibility.
- Validation after rename:
  - `python3 -m py_compile config.py SDR/src/receiver.py telemetry/mqtt_schema.py thread/SDRThread.py thread/SocketThread.py tests/test_mqtt_telemetry.py`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v` -> `15 passed`
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v` -> `4 passed`

## SDR Startup Debug Fix (2026-06-05)

- User observed `python3 app.py` failing during import with:
  - `TypeError: 'type' object is not subscriptable`
  - source line: `SDR/src/receiver.py`, annotation `tuple[np.ndarray, bytes]`
- Evidence:
  - pre-fix repro log: `logs/debug/app_start_tuple_type_20260605.log`
  - runtime Python is 3.8, where built-in generic annotations such as `tuple[...]` are evaluated at import time unless postponed.
- Fix:
  - added `from __future__ import annotations` to `SDR/src/receiver.py`.
  - updated `thread/SDRThread.py` `_result_consumer()` to treat empty result queue timeout as a normal idle condition with `except queue_module.Empty: continue`; real queue read failures still log as `sdr_result_consumer_read_error`.
- Verification:
  - `python3 -m py_compile SDR/src/receiver.py thread/SDRThread.py app.py`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v` -> `15 passed`
  - startup repro: `timeout 12s python3 app.py > logs/debug/app_start_result_consumer_fixed_20260605.log 2>&1`
  - startup exit status was `124` because `timeout` stopped the running Flask server after 12 seconds.
  - filtered startup log shows `SDR pipeline started` and Flask listening on `0.0.0.0`, `127.0.0.1:5000`, and `192.168.5.2:5000`.
  - filtered startup log has no `TypeError`, no `Traceback`, no `sdr_result_consumer_error`, and no `sdr_result_consumer_read_error`.
- Residual observation:
  - `sdr_reader_queue_drop` warnings can still appear under load, indicating SDR reader/plotter throughput pressure; this is a performance/backpressure tuning topic, not the Python 3.8 import crash.
