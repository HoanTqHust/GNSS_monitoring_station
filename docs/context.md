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
3. Every parsed UBX frame is persisted to the durable SQLite queue as `ubx_frame`.
4. When both receivers provide synchronized `RXM-RAWX` + `NAV-PVT` by `rcvTow`, an `epoch_pair` event is persisted to the same durable queue.
5. `thread/SocketThread.py` consumes durable queue events, runs realtime detectors for `epoch_pair`, and calls `draws/UbloxChart.py` for plot generation.
6. The backend emits:
   - `update_image` (plots + detector outputs)
   - `raw_data_batch` (raw UBX stream batches)

## Main Functional Components

- `app.py`: web application entry point
- `thread/ReadSerialThread.py`: serial ingestion and durable queue producer
- `thread/DurableRawQueue.py`: durable append-only raw event queue with ACK offsets
- `draws/UbloxChart.py`: numeric processing and plot generation
- `thread/SocketThread.py`: durable queue consumer and client streaming worker
- `logs/RawDataLogger.py`: raw UBX file logging helper

## Operating Assumptions

- The runtime environment is Linux with available serial devices under `/dev/ttyACM*`.
- The main data ingestion flow expects u-blox receivers to produce UBX data at `115200` baud.
- The dashboard is expected to run on the same host or within the same local network as the server.

## Important Findings From Source Review

- The runtime code requires `pyubx2`, but that package is not listed in `requirements.txt`.
- The frontend connects to Socket.IO through a fixed endpoint, `192.168.5.2:5000`, instead of using the current host dynamically.
- `requirements.txt` contains many packages that do not appear to be directly used by the source code currently present in the repo.
- The repository now includes deterministic unit tests for durable queue semantics, but still lacks broad end-to-end automated tests for the full spoofing pipeline.
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
- The web runtime now computes realtime detector outputs inside `thread/SocketThread.py` from durable `epoch_pair` records and emits them to `templates/index.html` as `realtime_outputs`.
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

## Option B Implementation (2026-04-23)

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
