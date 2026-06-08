# Codebase Map

## Snapshot

- Purpose: read GNSS UBX data, compute carrier phase double differences, render real-time dashboards, flag potential spoofing, and classify bladeRF SDR threat spectrograms
- Primary stack: Python, Flask, Flask-SocketIO, multiprocessing, pyserial, pyubx2, matplotlib, scikit-learn, NumPy, PyTorch, bladeRF bindings
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
- `telemetry/`: MQTT schema builders and publisher adapter for external server consumption
- `SDR/`: bladeRF wrapper, examples/tests, and jamming classifier model artifacts
- `thread/`: serial ingestion worker and Socket.IO streaming worker
- `draws/`: plotting and detection logic
- `logs/`: raw UBX logging helper
- `templates/`: HTML frontend templates
- `docs/`: project memory and repository documentation
- `docs/dev-hoantran-vs-main.md`: Vietnamese per-commit ledger of `dev/hoantran` changes compared with `main`
- `docs/sdr-flow-analysis.md`: SDR runtime flow and model-contract mismatch analysis
- `record_ubx.sh`, `log.py`, `send_command.py`, `test.py`: operational and debugging scripts
- `README_RAW_UBX_STREAM_VI.md`: Vietnamese field-by-field reference for realtime detector outputs, raw stream payloads, UI metrics, status meanings, and identity groups
- `README_MQTT_DATA_SCHEMA_VI.md`: Vietnamese MQTT topic and JSON schema contract for external server subscribers

## Module Map

| Module | Role | Key files | Edit here when | Depends on | Used by |
| --- | --- | --- | --- | --- | --- |
| Web runtime | Builds the Flask app, routes, and startup flow | `app.py`, `templates/index.html`, `templates/about.html` | changing routes, startup behavior, or dashboard rendering | `flask`, `flask_socketio`, `thread/*`, `config.py` | web users, background workers |
| Serial ingestion | Reads UBX messages from two receivers, runs RTKLIB-stage normalization, and emits events into RAM ingress queue | `thread/ReadSerialThread.py`, `thread/RTKLIBStage.py` | changing serial ports, message types, normalization shape, or event payload mapping | `serial`, `pyubx2`, `models/RAWXData.py`, `config.py`, `multiprocessing.Queue` | `app.py`, `thread/SocketThread.py` |
| Realtime detector skeleton | Converts normalized epochs into measurement frames and writes separated detector outputs | `realtime/pipeline.py`, `realtime/measurement_builders/*`, `realtime/detector_engines/*`, `realtime/output_writer.py` | adding live SoS/D3 flow, changing output format, preparing MQTT/REST integration | `models`-compatible RAWX objects, `numpy`, filesystem output | future live detector workers or publishers |
| MQTT telemetry | Builds MQTT JSON envelopes and publishes them to Mosquitto-compatible brokers with QoS 1 | `telemetry/mqtt_schema.py`, `telemetry/mqtt_publisher.py`, `.env.example` | changing broker schema, topic mapping, QoS/publish behavior, or MQTT config defaults | `paho-mqtt`, `config.py` | `thread/SocketThread.py`, external server subscribers |
| SDR detect pipeline | Captures bladeRF IQ samples, renders BMP spectrograms, runs ResNet18 SDR classifier, emits `sdr_classify`, and publishes bounded SDR threat snapshots over MQTT | `thread/SDRThread.py`, `SDR/src/*`, `telemetry/mqtt_schema.py`, `templates/sdr.html`, `SDR/model/*` | changing bladeRF RX settings, spectrogram preprocessing, class labels, model runtime, SDR dashboard behavior, or SDR snapshot MQTT publishing | `bladerf`, `numpy`, `torch`, `Pillow`, `matplotlib`, `flask_socketio`, `paho-mqtt` | `app.py`, `/sdr` dashboard, EMQX/MQTT subscribers |
| Standalone live runner | Reads live UBX streams and feeds synchronized epochs into the realtime pipeline | `realtime/live_runner.py` | running the detector stack without touching the web app runtime | `serial`, `pyubx2`, `config.py`, `models/RAWXData.py`, `realtime/pipeline.py` | operators, live smoke tests |
| Threshold calibration | Reads clean recorded UBX files, synchronizes epochs, and estimates four initial thresholds for the current realtime stack | `realtime/calibrate_thresholds.py` | deriving initial SoS/D3 thresholds from clean baseline data | `pyubx2`, `models/RAWXData.py`, `realtime/measurement_builders/*`, `numpy` | operators, future config wiring |
| Visualization + detection | Computes carrier phase differences, creates skyplot/spectrum/DPS images, flags spoofing | `draws/UbloxChart.py` | changing the algorithm, plotting, or thresholds | `numpy`, `matplotlib`, `sklearn`, `config.py` | `thread/SocketThread.py` |
| Data model | Converts parsed UBX messages into Python objects for downstream processing | `models/RAWXData.py`, `models/SatelliteData.py` | changing extracted fields or per-satellite metadata | parsed UBX objects | `thread/ReadSerialThread.py`, `draws/UbloxChart.py` |
| Streaming worker | Routes ingress events into detect/raw RAM queues, runs realtime detectors, emits plot updates and raw frame batches | `thread/SocketThread.py` | changing fan-out policy, overflow policy, emit cadence, payload shape, or metrics | `queue`, `realtime/pipeline.py`, `draws/UbloxChart.py`, `psutil`, `config.py` | `app.py`, frontend |
| Logging / capture | Persists raw UBX data for debugging and later analysis | `logs/RawDataLogger.py`, `log.py`, `record_ubx.sh` | changing log format, storage path, or number of receivers | `os`, `datetime`, `serial`, `pyubx2` | operators, debugging flow |
| Device config tools | Sends UBX commands to configure the receiver | `send_command.py` | changing baudrate, message enablement, or persisted receiver config | `serial`, custom UBX message builder | operators |

## Interaction Map

- Request flow:
  - The browser opens `/` in `app.py`.
  - `templates/index.html` loads the Socket.IO client.
  - The client listens for the `update_image` event.
  - The browser opens `/sdr` for the SDR jamming dashboard.
- Data flow:
  - Serial device -> `ReadSerial.read_serial()` -> RTKLIB-stage normalization -> RAM ingress queue
  - RAM ingress queue -> `SocketThread.router_thread()` -> detect queue + raw queue
  - Detect queue -> `SocketThread.detect_consumer_thread()` -> detector + `UbloxChart` -> `update_image`
  - Raw queue -> `SocketThread.raw_consumer_thread()` -> `raw_data_batch`
  - Raw queue -> MQTT `raw/ublox/v1`
  - Detect queue -> MQTT `detect/ublox/v1` + `state/position/v1`
  - Raw batch metrics -> MQTT `health/v1`
  - bladeRF -> `SDRThread.reader_process()` -> IQ frame queue -> `SDRThread.plotter_process()` -> `BKDATASET/*.bmp` + result queue -> Socket.IO `sdr_classify`
  - `/sdr` frontend polls `/sdr/latest_bmp` and fetches `/sdr/bmp/<filename>` for the latest spectrogram image.
  - On SDR threat detection -> `output_sdr/{file_id}.bin` + `.json` -> SDR MQTT worker -> `detect/sdr/v1` + chunked `raw/sdr/v1`
- External integrations:
  - Serial ports under `/dev/ttyACM*`
  - Socket.IO CDN loaded from `templates/index.html`
  - Planned MQTT broker publishing for external server consumption, with separate raw, detect, and health topic families
- Background work:
  - `multiprocessing.Process` for serial ingestion
  - `socketio.start_background_task()` for the streaming worker

## Change Guide

- If changing serial ingestion:
  - edit `config.py` and `thread/ReadSerialThread.py`
  - verify the required UBX message types and the `rcvTow` synchronization rule
  - keep RTKLIB-stage payload shape aligned in `thread/RTKLIBStage.py`
  - verify enqueue topics (`ubx_frame`, `epoch_pair`) and payload shape compatibility
- If changing the dashboard payload:
  - edit `thread/SocketThread.py` and `templates/index.html`
  - keep payload keys aligned between server and client
  - keep summary chart series mapping aligned with `realtime_outputs` and `raw_data_batch.queue_stats`
- If changing queue reliability behavior:
  - edit queue sizing / poll configs in `config.py`
  - edit overflow routing policy in `thread/SocketThread.py`
  - adjust health telemetry emission interval via `RAM_HEALTH_PUBLISH_INTERVAL` to avoid excessive publish overhead in high-rate runs
  - adjust `RAM_RAW_MQTT_QUEUE_SIZE` to tune decoupled raw publish worker backpressure
  - validate with `tests/test_ram_queue_flow.py`
- If changing the detection algorithm:
  - edit `draws/UbloxChart.py`
  - review `calc_pseudorange()`, `process_ubx_data()`, and `raw2ImageDps()`
- If adding persistence:
  - start with `logs/RawDataLogger.py` or add a separate persistence module
- If building live spoofing outputs:
  - start with `realtime/pipeline.py`
  - add logic in `realtime/measurement_builders/` before editing detector engines
  - keep realtime detectors decoupled from serial I/O and web transport
- If adding MQTT publishing:
  - edit `telemetry/mqtt_schema.py` for payload shape and topic mapping
  - edit `telemetry/mqtt_publisher.py` for broker publish behavior
  - use `wait_for_ack=False` only for high-rate non-critical paths (current raw UBX path) to avoid consumer-loop blocking
  - keep command subscriber topic contract aligned with README:
    - subscribe both `gnss/{site_id}/{device_id}/cmd/+/v1` and `gnss/{site_id}/{device_id}/cmd/+/+/v1`
    - parse command type from `cmd/{command_type}/v1` suffix (supports one-level and nested `ublox/*`)
    - fallback command id from `event_id` when `data.command_id` is missing, so ACK/dedupe still works with legacy server payloads
    - skip internal branch topics `cmd/init/v1` and `cmd/ack/v1` in subscriber receive path
  - prefer explicit log markers for command lifecycle in runtime logs (`cmd_init_published`, `cmd_ack_published`)
  - keep the transport adapter after RAM routing/consumer output boundaries, not inside detector engines
  - keep raw UBX/SDR payloads on raw topics and publish detector summaries on detect topics
  - version every published schema and include sequence numbers for duplicate/gap detection
- If debugging receiver configuration:
  - inspect `send_command.py`, `test.py`, `record_ubx.sh`, and `log.py`
- If changing the SDR jamming pipeline:
  - start with `docs/sdr-flow-analysis.md`, `thread/SDRThread.py`, and `SDR/README_bladerf_integration.md`
  - reconcile sample rate, frame size, STFT settings, colormap/render format, normalization, and class label order before trusting classifier results
  - avoid importing bladeRF/PyTorch dependencies unconditionally when `SDR_ENABLED` is false
  - add queue drop metrics and structured logs before tuning throughput
  - for Option A raw publishing, keep raw SC16_Q11 bytes in a ring buffer and publish only bounded snapshots around jamming events; do not continuous-stream full-rate SDR over MQTT
  - keep `README_MQTT_DATA_SCHEMA_VI.md` aligned with `telemetry/mqtt_schema.py` for server subscribers

## Validation Guide

- Main run command:
  - `python app.py`
- RAM queue flow tests:
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v`
- Manual capture utilities:
  - `python log.py`
  - `bash record_ubx.sh`
  - `python test.py`
- Regression attention:
  - whether ingress queue backlog grows without bound
  - whether detect/raw queue drop counters increase under expected load
  - whether detect consumer actually enters run loop (`detect_consumer_started`) after startup
  - whether raw MQTT publish throughput is materially below ingest throughput (for example, around `~10/s` publish vs `~200+/s` ingest), which will force `pending_events` growth
  - whether `raw_data_batch` sequence gaps stay at zero in stable runs
  - whether frontend raw tables for `rx1` and `rx2` stay separated and ordered by latest-first index
  - whether `rcvTow` synchronization remains correct
  - whether the frontend still receives `update_image`
  - whether satellite filtering by `ELE_MASK` still behaves correctly
  - whether the hard-coded frontend IP still matches the actual server
  - whether SDR modules remain import-compatible with Python 3.8 annotation behavior
  - whether SDR result queue idle timeout remains treated as normal control flow, not logged as an exception

## Forward Architecture Note (Raw Throughput, Historical)

- Before Option B implementation, bottleneck surfaces for high-rate raw streams were:
  - `thread/ReadSerialThread.py` drops oldest entry when queue is full and keeps only a bounded in-memory sample window.
  - `thread/SocketThread.py` does CPU-heavy image generation in the same consumer loop that drains `data_queue`.
- Current runtime split:
  - `serial_ingest` (read + RTKLIB-stage normalization + event enqueue)
  - `raw_bus` in RAM (`multiprocessing.Queue` ingress + routed detect/raw queues)
  - `consumers` (detect/app and raw/app) as independent workers
- Observability required before/after changes:
  - ingress rate (bytes/s, frames/s)
  - queue depth and max depth
  - end-to-end lag per consumer
  - dropped frame counter (must stay zero for raw guarantee scope)

## Cross-Cutting Concerns

- Config and env:
  - `config.py` loads `.env` and centralizes runtime settings
  - realtime detector thresholds are now configurable from env (`SOS_*`, `D3_*`) and wired into `realtime/pipeline.py`
- Auth:
  - there is no authentication in the web app
- Persistence:
  - runtime path is RAM-only (no SQLite persistence)
  - raw UBX file logging still exists through `logs/RawDataLogger.py`
- Testing:
  - deterministic unit tests exist for RAM queue sequencing and overflow helper logic (`tests/test_ram_queue_flow.py`)
  - end-to-end automated tests for the full spoofing flow are still missing
- Build and deploy:
  - no build or deployment pipeline is present in the repo
- Hotspots:
  - `draws/UbloxChart.py` carries the most mixed responsibilities
  - `thread/ReadSerialThread.py` and `thread/SocketThread.py` still rely on broad `except Exception` handling
  - `thread/SocketThread.py` now routes raw MQTT publish to a dedicated worker queue; if sustained overload occurs, monitor `mqtt_raw_queue_dropped` and `mqtt_raw_failed`
  - `telemetry/mqtt_subscriber.py` uses strict MQTT settings validation; invalid credential/port/qos config blocks subscriber startup by design
  - `templates/index.html` is tightly coupled to a specific server address

## Unknowns

- Unknowns:
  - the repo does not explain the source or validation basis for the spoofing threshold `delta_a = 0.0001`
  - there is no documentation describing the exact expected UBX message configuration for each receiver
  - `requirements.txt` appears to describe a larger environment, not the minimal dependency set for this repo
- Inference:
  - this looks more like a GNSS research or experiment codebase than a production-hardened application because of the debugging scripts and manual logging workflow
