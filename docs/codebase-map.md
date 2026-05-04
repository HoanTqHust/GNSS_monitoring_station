# Codebase Map

## Snapshot

- Purpose: read GNSS UBX data, compute carrier phase double differences, render a real-time dashboard, and flag potential spoofing
- Primary stack: Python, Flask, Flask-SocketIO, multiprocessing, pyserial, pyubx2, matplotlib, scikit-learn
- Main runtimes: 1 Flask process, 1 serial-reading process, 1 Socket.IO background task
- Entry points:
  - `app.py`
  - `log.py`
  - `send_command.py`
  - `record_ubx.sh`

## Top-Level Layout

- `app.py`: web app bootstrap and runtime orchestration
- `config.py`: environment loading and runtime settings
- `models/`: data wrappers for parsed RAWX messages
- `realtime/`: realtime measurement-builder and detector-engine skeleton for live spoofing outputs
- `thread/`: serial ingestion worker and Socket.IO streaming worker
- `draws/`: plotting and detection logic
- `logs/`: raw UBX logging helper
- `templates/`: HTML frontend templates
- `docs/`: project memory and repository documentation
- `record_ubx.sh`, `log.py`, `send_command.py`, `test.py`: operational and debugging scripts

## Module Map

| Module | Role | Key files | Edit here when | Depends on | Used by |
| --- | --- | --- | --- | --- | --- |
| Web runtime | Builds the Flask app, routes, and startup flow | `app.py`, `templates/index.html`, `templates/about.html` | changing routes, startup behavior, or dashboard rendering | `flask`, `flask_socketio`, `thread/*`, `config.py` | web users, background workers |
| Serial ingestion | Reads UBX messages from two receivers, emits raw frame events, and emits synchronized epoch-pair events into durable storage | `thread/ReadSerialThread.py` | changing serial ports, message types, synchronization logic, or event payload mapping | `serial`, `pyubx2`, `models/RAWXData.py`, `config.py`, `thread/DurableRawQueue.py` | `app.py`, `thread/SocketThread.py` |
| Realtime detector skeleton | Converts normalized epochs into measurement frames and writes separated detector outputs | `realtime/pipeline.py`, `realtime/measurement_builders/*`, `realtime/detector_engines/*`, `realtime/output_writer.py` | adding live SoS/D3 flow, changing output format, preparing MQTT/REST integration | `models`-compatible RAWX objects, `numpy`, filesystem output | future live detector workers or publishers |
| Standalone live runner | Reads live UBX streams and feeds synchronized epochs into the realtime pipeline | `realtime/live_runner.py` | running the detector stack without touching the web app runtime | `serial`, `pyubx2`, `config.py`, `models/RAWXData.py`, `realtime/pipeline.py` | operators, live smoke tests |
| Threshold calibration | Reads clean recorded UBX files, synchronizes epochs, and estimates four initial thresholds for the current realtime stack | `realtime/calibrate_thresholds.py` | deriving initial SoS/D3 thresholds from clean baseline data | `pyubx2`, `models/RAWXData.py`, `realtime/measurement_builders/*`, `numpy` | operators, future config wiring |
| Visualization + detection | Computes carrier phase differences, creates skyplot/spectrum/DPS images, flags spoofing | `draws/UbloxChart.py` | changing the algorithm, plotting, or thresholds | `numpy`, `matplotlib`, `sklearn`, `config.py` | `thread/SocketThread.py` |
| Data model | Converts parsed UBX messages into Python objects for downstream processing | `models/RAWXData.py`, `models/SatelliteData.py` | changing extracted fields or per-satellite metadata | parsed UBX objects | `thread/ReadSerialThread.py`, `draws/UbloxChart.py` |
| Streaming worker | Consumes durable queue events, runs realtime detectors, emits plot updates and raw frame batches | `thread/SocketThread.py` | changing consumer ACK policy, emit cadence, payload shape, or metrics | `thread/DurableRawQueue.py`, `realtime/pipeline.py`, `draws/UbloxChart.py`, `psutil`, `config.py` | `app.py`, frontend |
| Durable raw queue | Persists raw events and tracks per-consumer ACK offsets for replay | `thread/DurableRawQueue.py` | changing durability, batch read semantics, or consumer ACK policy | `sqlite3`, `pickle`, filesystem | serial producer, socket consumer |
| Logging / capture | Persists raw UBX data for debugging and later analysis | `logs/RawDataLogger.py`, `log.py`, `record_ubx.sh` | changing log format, storage path, or number of receivers | `os`, `datetime`, `serial`, `pyubx2` | operators, debugging flow |
| Device config tools | Sends UBX commands to configure the receiver | `send_command.py` | changing baudrate, message enablement, or persisted receiver config | `serial`, custom UBX message builder | operators |

## Interaction Map

- Request flow:
  - The browser opens `/` in `app.py`.
  - `templates/index.html` loads the Socket.IO client.
  - The client listens for the `update_image` event.
- Data flow:
  - Serial device -> `ReadSerial.read_serial()` -> durable raw queue (`thread/DurableRawQueue.py`)
  - Durable queue -> `SocketThread.background_thread()` -> detector + `UbloxChart` -> base64 PNG -> browser
  - Durable queue -> `SocketThread.background_thread()` -> `raw_data_batch` -> browser raw stream panel
- External integrations:
  - Serial ports under `/dev/ttyACM*`
  - Socket.IO CDN loaded from `templates/index.html`
- Background work:
  - `multiprocessing.Process` for serial ingestion
  - `socketio.start_background_task()` for the streaming worker

## Change Guide

- If changing serial ingestion:
  - edit `config.py` and `thread/ReadSerialThread.py`
  - verify the required UBX message types and the `rcvTow` synchronization rule
  - verify enqueue topics (`ubx_frame`, `epoch_pair`) and payload shape compatibility
- If changing the dashboard payload:
  - edit `thread/SocketThread.py` and `templates/index.html`
  - keep payload keys aligned between server and client
- If changing queue reliability behavior:
  - edit `thread/DurableRawQueue.py` and related config in `config.py`
  - validate ACK/replay behavior with `tests/test_durable_raw_queue.py`
- If changing the detection algorithm:
  - edit `draws/UbloxChart.py`
  - review `calc_pseudorange()`, `process_ubx_data()`, and `raw2ImageDps()`
- If adding persistence:
  - start with `logs/RawDataLogger.py` or add a separate persistence module
- If building live spoofing outputs:
  - start with `realtime/pipeline.py`
  - add logic in `realtime/measurement_builders/` before editing detector engines
  - keep realtime detectors decoupled from serial I/O and web transport
- If debugging receiver configuration:
  - inspect `send_command.py`, `test.py`, `record_ubx.sh`, and `log.py`

## Validation Guide

- Main run command:
  - `python app.py`
- Queue durability tests:
  - `python3 -m unittest discover -s tests -p 'test_durable_raw_queue.py' -v`
- Manual capture utilities:
  - `python log.py`
  - `bash record_ubx.sh`
  - `python test.py`
- Regression attention:
  - whether durable queue consumer lag grows without bound
  - whether ACK sequence advances for `RAW_QUEUE_CONSUMER_ID`
  - whether `raw_data_batch` sequence gaps stay at zero in stable runs
  - whether frontend raw tables for `rx1` and `rx2` stay separated and ordered by latest-first index
  - whether `rcvTow` synchronization remains correct
  - whether the frontend still receives `update_image`
  - whether satellite filtering by `ELE_MASK` still behaves correctly
  - whether the hard-coded frontend IP still matches the actual server

## Forward Architecture Note (Raw Throughput, Historical)

- Before Option B implementation, bottleneck surfaces for high-rate raw streams were:
  - `thread/ReadSerialThread.py` drops oldest entry when queue is full and keeps only a bounded in-memory sample window.
  - `thread/SocketThread.py` does CPU-heavy image generation in the same consumer loop that drains `data_queue`.
- Recommended split for reliable raw delivery:
  - `serial_ingest` (read + frame + seq + persist/spool)
  - `raw_bus` (bounded backpressure with drop policy disabled for raw path)
  - `consumers` (RTKLIB parser, detector pipeline, app publisher) as independent workers
- Observability required before/after changes:
  - ingress rate (bytes/s, frames/s)
  - queue depth and max depth
  - end-to-end lag per consumer
  - dropped frame counter (must stay zero for raw guarantee scope)

## Cross-Cutting Concerns

- Config and env:
  - `config.py` loads `.env` and centralizes runtime settings
- Auth:
  - there is no authentication in the web app
- Persistence:
  - durable raw queue persistence now exists via `thread/DurableRawQueue.py` (SQLite WAL)
  - raw UBX file logging still exists through `logs/RawDataLogger.py`
- Testing:
  - deterministic unit tests exist for queue ACK/replay semantics (`tests/test_durable_raw_queue.py`)
  - end-to-end automated tests for the full spoofing flow are still missing
- Build and deploy:
  - no build or deployment pipeline is present in the repo
- Hotspots:
  - `draws/UbloxChart.py` carries the most mixed responsibilities
  - `thread/ReadSerialThread.py` and `thread/SocketThread.py` still rely on broad `except Exception` handling
  - `templates/index.html` is tightly coupled to a specific server address

## Unknowns

- Unknowns:
  - the repo does not explain the source or validation basis for the spoofing threshold `delta_a = 0.0001`
  - there is no documentation describing the exact expected UBX message configuration for each receiver
  - `requirements.txt` appears to describe a larger environment, not the minimal dependency set for this repo
- Inference:
  - this looks more like a GNSS research or experiment codebase than a production-hardened application because of the debugging scripts and manual logging workflow
