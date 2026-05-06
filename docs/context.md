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
  - `telemetry/mqtt_schema.py` builds `raw/ublox`, `detect/epoch`, `state/position`, and `health` JSON envelopes.
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
  - detect stream (`detect/epoch/v1`) and position (`state/position/v1`) in `detect_consumer_thread`
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
