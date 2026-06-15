# Codebase Map

Last source review: 2026-06-15.

## Snapshot

- Purpose: real-time GNSS spoofing detection from two u-blox receivers plus SDR jamming detection from bladeRF.
- Primary stack: Python, Flask, Flask-SocketIO, multiprocessing/threading queues, pyserial, pyubx2, NumPy, matplotlib, scikit-learn, PyTorch, paho-mqtt, bladeRF Python bindings.
- Main runtime: `app.py`.
- Main dashboards:
  - `/` -> `templates/index.html`
  - `/sdr` -> `templates/sdr.html`
- Source review scope: application source only. Excluded vendor/generated areas include `SDR/bladeRF/`, `venv/`, `__pycache__/`, `output_rt/`, `output_sdr/`, `BKDATASET/`, `logs/`, `data/`.

## Top-Level Layout

- `app.py`: Flask routes, Socket.IO bootstrap, queue creation, serial process startup, SocketThread background tasks, optional SDR startup.
- `config.py`: `.env` loading, queue sizes, thresholds, MQTT settings, SDR settings.
- `thread/`: live runtime workers for serial ingest, RAM routing, Socket.IO/MQTT streaming, SDR capture/classification.
- `realtime/`: detector pipeline, measurement builders, detector engines, JSONL writer, live/test/calibration runners.
- `telemetry/`: MQTT schema builders, publisher adapter, command subscriber/handler.
- `models/`: light wrappers around parsed `RXM-RAWX` satellite measurements.
- `draws/`: plot generation and sliding-window carrier-phase visual detector.
- `templates/`: browser UI for GNSS and SDR dashboards.
- `SDR/src/`: bladeRF RX/TX wrapper library.
- `SDR/tests/`, `SDR/examples/`: hardware-oriented SDR utilities.
- `tests/`: deterministic unit tests for RAM queue helpers and MQTT telemetry.
- `clone/`: batch/reference algorithm experiments for AOA/SoS/D3/smoothed pseudorange; not wired into live app.
- `docs/`: core memory and analysis notes.
- `README.md`: product/runtime architecture overview.
- `README_RAW_UBX_STREAM_VI.md`: Vietnamese dashboard/raw stream data dictionary.
- `README_MQTT_DATA_SCHEMA_VI.md`: Vietnamese MQTT topic/schema contract.
- `docs/sdr-flow-analysis.md`: SDR runtime and model-contract mismatch analysis.

## Module Map

| Module | Role | Key files | Edit here when | Depends on | Used by |
| --- | --- | --- | --- | --- | --- |
| Web bootstrap | Creates Flask app, routes, queues, background workers, logs | `app.py` | changing routes, startup, queue ownership, SDR startup, logging | `config.py`, `thread/*`, Flask, Socket.IO | operators, browsers |
| Config | Centralizes env/defaults for ports, queues, thresholds, MQTT, SDR | `config.py` | changing runtime defaults or env names | `.env`, `os.environ` | all runtime modules |
| Serial ingest | Reads two u-blox receivers, parses UBX/NMEA, emits RAM events | `thread/ReadSerialThread.py`, `thread/RTKLIBStage.py` | changing serial ports, message parsing, event payload shape, TOW pairing | `serial`, `pyubx2`, `models`, `config.py` | `app.py`, `SocketThread.router_thread()` |
| RAWX model | Wraps pyubx2 `RXM-RAWX` fields into simple objects | `models/RAWXData.py`, `models/SatelliteData.py` | adding/removing satellite fields consumed downstream | pyubx2 parsed object shape | serial ingest, realtime, plotting, MQTT schema |
| RAM router / stream worker | Routes events, runs detect/raw consumers, emits Socket.IO, publishes MQTT | `thread/SocketThread.py` | changing queue policy, Socket.IO payloads, MQTT publication, metrics | `realtime`, `telemetry`, `draws`, `psutil`, queues | `app.py`, dashboards, MQTT subscribers |
| Realtime spoofing pipeline | Builds carrier/smoothed PR measurement frames and runs SoS/D3 engines | `realtime/pipeline.py`, `realtime/measurement_builders/*`, `realtime/detector_engines/*`, `realtime/types.py` | changing detector math, thresholds, output fields, output folders | `config.py`, `models`-compatible RAWX objects, NumPy | `SocketThread`, `live_runner`, `test_runner`, calibration |
| Realtime output/calibration | Writes detector JSONL and estimates thresholds from clean UBX | `realtime/output_writer.py`, `realtime/calibrate_thresholds.py`, `realtime/live_runner.py`, `realtime/test_runner.py` | smoke testing, threshold calibration, standalone live operation | pyubx2, serial, realtime builders | operators/developers |
| Plotting + visual detector | Generates skyplot/spectrum/DPS images and slope-cluster spoofing bool | `draws/UbloxChart.py` | changing dashboard plots or the sliding-window visual detector | NumPy, matplotlib, sklearn, `config.ELE_MASK` | `SocketThread.detect_consumer_thread()` |
| MQTT schema | Builds versioned topic payloads for UBX raw/detect/position/health, SDR detect/raw chunks, commands/ACK | `telemetry/mqtt_schema.py` | changing external server contract or payload normalization | runtime event payloads | `SocketThread`, `SDRThread`, tests |
| MQTT publish | Validates settings and publishes JSON through paho-mqtt with QoS 1 | `telemetry/mqtt_publisher.py` | changing broker connection, QoS, retain/wait behavior | paho-mqtt | `SocketThread`, `SDRThread`, tests |
| MQTT command subscriber | Subscribes command topics, dedupes command IDs, configures/resets realtime pipeline, publishes ACK | `telemetry/mqtt_subscriber.py` | adding commands, changing command topic grammar, changing ACK semantics | paho-mqtt, `config.py`, `RealtimeSpoofingPipeline` | `SocketThread.detect_consumer_thread()` |
| SDR runtime | Captures bladeRF IQ, renders BMP, runs classifier, emits UI result, publishes threat snapshot | `thread/SDRThread.py` | changing jamming classifier runtime, snapshot logic, SDR MQTT publish, `/sdr` behavior | torch, PIL, matplotlib, bladeRF wrapper, telemetry | `app.py`, `/sdr`, MQTT subscribers |
| SDR wrapper | Minimal bladeRF RX/TX abstraction | `SDR/src/common.py`, `SDR/src/receiver.py`, `SDR/src/transmitter.py` | changing bladeRF sync config or IQ conversion | `bladerf._bladerf`, NumPy | `SDRThread`, SDR examples/tests |
| Frontend UI | Shows GNSS plots/cards/raw table/summary chart and SDR spectrogram/classifier | `templates/index.html`, `templates/sdr.html`, `templates/about.html` | changing Socket.IO event handling, display fields, client endpoints | Socket.IO CDN, Chart.js CDN, Flask routes | browser users |
| Tests | Deterministic helper/schema tests | `tests/test_ram_queue_flow.py`, `tests/test_mqtt_telemetry.py` | validating queue and MQTT changes | unittest, fake objects | developers/agents |
| Ops utilities | Manual capture/config scripts | `log.py`, `record_ubx.sh`, `send_command.py`, `test.py`, `log_fake.py` | receiver configuration, raw UBX capture, local debug | serial, pyubx2 | operators |

## Interaction Map

### GNSS Request / Data Flow

1. Browser loads `/` from `app.py`.
2. `templates/index.html` loads Socket.IO and connects to `http://192.168.5.2:5000`.
3. `app.py` starts `ReadSerial.read_serial()` in a multiprocessing process.
4. `ReadSerial` reads `PORT1` and `PORT2` at 115200 baud.
5. `RTKLIBStage.normalize_frame()` creates raw `ubx_frame` payloads.
6. `RTKLIBStage.normalize_receiver_state()` stores latest `RXM-RAWX`, `NAV-PVT`, `NAV-SAT`, `MON-SPAN` per receiver.
7. When both receivers have synchronized RAWX/NAV by rounded `rcvTow`, `RTKLIBStage.normalize_epoch_pair()` creates an `epoch_pair`.
8. `SocketThread.router_thread()` routes:
   - `ubx_frame` to raw queue;
   - `epoch_pair` to detect queue.
9. Detect consumer:
   - builds `RealtimeEpochPair`;
   - runs `RealtimeSpoofingPipeline.process_epoch()`;
   - publishes `detect/ublox/v1` and `state/position/v1`;
   - updates sliding window;
   - periodically emits `update_image`.
10. Raw consumer:
   - batches raw frames;
   - emits `raw_data_batch`;
   - enqueues raw MQTT publish to a dedicated thread;
   - periodically publishes `health/v1`.

### Realtime Detector Flow

1. `RealtimeSpoofingPipeline` creates:
   - `CarrierMeasurementBuilder`
   - `SmoothedPseudorangeMeasurementBuilder`
   - `SoSDetectorEngine` for carrier
   - `SoSDetectorEngine` for smoothed pseudorange
   - `D3DetectorEngine` for carrier
   - `D3DetectorEngine` for smoothed pseudorange
2. Builders use only common GPS L1 observations.
3. Reference SVID defaults to lowest common SVID in each builder; pipeline has `set_reference_svid()` but builders currently do not consume `_reference_svid`.
4. Each detector result is written to `output_rt/<output_name>/events.jsonl`.
5. `SocketThread.build_realtime_output_map()` converts `DetectorResult` dataclasses into frontend/MQTT-friendly maps.

### MQTT Command Flow

1. Detect consumer creates a detect MQTT publisher.
2. It publishes retained command branch bootstrap messages on `cmd/init/v1` and `cmd/ack/v1`.
3. `MqttCommandSubscriber` subscribes to:
   - `gnss/<site>/<device>/cmd/+/v1`
   - `gnss/<site>/<device>/cmd/+/+/v1`
4. Supported command types:
   - legacy: `reboot`, `set_rate`, `start`, `stop`, `status`
   - nested: `ublox/configure`, `ublox/restart`, `ublox/start`, `ublox/stop`, `ublox/status`
5. Subscriber ignores internal `cmd/init/v1` and `cmd/ack/v1`.
6. Subscriber dedupes by `data.command_id`, falling back to top-level `event_id`.
7. Handler can mutate runtime thresholds, reference_svid, min_sat_count, pipeline status, or reset the realtime pipeline.
8. ACK is published to `cmd/ack/v1`.

### SDR Flow

1. Browser loads `/sdr` from `app.py`.
2. If `config.SDR_ENABLED`, `app.py` starts `SDRThread`.
3. `SDRThread.start()` creates:
   - multiprocessing IQ frame queue;
   - multiprocessing result queue;
   - in-process MQTT event queue;
   - `reader_process`;
   - `plotter_process`;
   - result consumer thread;
   - MQTT event worker thread.
4. `reader_process` opens bladeRF through `SDR/src/common.py::BladeRFSdr`, configures RX, reads raw SC16_Q11 samples via `Receiver.receive_with_raw()`, and pushes normalized samples plus raw bytes.
5. `plotter_process` renders BMP spectrograms under `BKDATASET/`, runs ResNet18 inference if model loads, and sends `sdr_classify` results.
6. If jamming is detected above `SDR_JAMMING_CONFIDENCE_THRESHOLD`, it saves a bounded raw snapshot under `output_sdr/` and attaches an MQTT event.
7. SDR MQTT worker publishes:
   - `detect/sdr/v1`
   - chunked `raw/sdr/v1`
8. `templates/sdr.html` listens for `sdr_classify`; it separately polls `/sdr/latest_bmp` every 500 ms for the latest BMP.

## Change Guide

- If changing serial ingestion:
  - start with `thread/ReadSerialThread.py` and `thread/RTKLIBStage.py`;
  - keep `ubx_frame` and `epoch_pair` payload contracts aligned with `SocketThread` and `telemetry/mqtt_schema.py`;
  - validate with `tests/test_ram_queue_flow.py` and a hardware/manual run if serial behavior changes.
- If changing queue reliability or metrics:
  - edit `SocketThread.create_metrics()`, `_put_with_drop_oldest()`, `_build_queue_stats()`, and raw/detect consumer paths together;
  - update `build_health_message()` and dashboard queue metrics if fields change.
- If changing realtime spoofing math:
  - edit `realtime/measurement_builders/*` for measurement construction first;
  - edit `realtime/detector_engines/*` for detector scoring;
  - update `realtime/test_runner.py` or add unit tests with fake RAWX data;
  - keep output names stable unless frontend/MQTT docs are updated.
- If changing dashboard detector cards:
  - edit `SocketThread.build_realtime_output_map()` and `templates/index.html`;
  - keep `README_RAW_UBX_STREAM_VI.md` aligned.
- If changing MQTT schema:
  - edit `telemetry/mqtt_schema.py`;
  - update `tests/test_mqtt_telemetry.py`;
  - update `README_MQTT_DATA_SCHEMA_VI.md`.
- If changing MQTT commands:
  - edit `telemetry/mqtt_subscriber.py`;
  - add tests for `_build_command_topics()`, `_dispatch_command()`, `_on_message()`, and ACK output.
- If changing SDR classifier behavior:
  - read `docs/sdr-flow-analysis.md` first;
  - decide whether runtime or `SDR/README_bladerf_integration.md` is authoritative;
  - update `thread/SDRThread.py`, `SDR/README_bladerf_integration.md`, and tests/docs together.
- If fixing frontend Socket.IO host:
  - edit `templates/index.html` at the `io("http://192.168.5.2:5000")` call;
  - prefer same-origin `io()` unless cross-host behavior is required.
- If touching sensitive/config files:
  - do not print `.env`, `cookies.txt`, or `login.txt`;
  - use `.env.example` or docs placeholders for examples.

## Validation Guide

- Full available unit suite:
  - `python3 -m unittest discover -s tests -v`
- RAM queue helper tests:
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v`
- MQTT schema/publisher/subscriber tests:
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v`
- Realtime synthetic smoke:
  - `python3 realtime/test_runner.py`
- Main app:
  - `python app.py`
- Standalone realtime live runner:
  - `python3 -m realtime.live_runner`
  - `python3 realtime/live_runner.py`
- Threshold calibration:
  - `python3 realtime/calibrate_thresholds.py --file1 <rx1.ubx> --file2 <rx2.ubx>`
- Manual UBX capture/config:
  - `python log.py`
  - `bash record_ubx.sh`
  - `python send_command.py`
- SDR hardware tests require bladeRF hardware and dependencies:
  - `python -m pytest SDR/tests/test_bladerf.py`
  - `python SDR/examples/receive_loop.py`

## Cross-Cutting Concerns

- Config/env:
  - `config.py` loads `.env` at import time.
  - MQTT is enabled by default.
  - SDR is enabled by default.
- Auth:
  - Flask dashboards have no authentication.
- Persistence:
  - Current live GNSS runtime is RAM queue based.
  - Raw UBX file logging exists through utility scripts.
  - Realtime detector JSONL goes to `output_rt/`.
  - SDR snapshots go to `output_sdr/`.
  - `BKDATASET/` stores SDR BMP frames and has no retention policy in source.
- Observability:
  - `app.py` creates `all.log` and `mqtt.log`.
  - GNSS runtime uses Python logging.
  - SDR worker processes still use several `print()` calls.
- Backpressure:
  - Ingress queue uses drop-new in `ReadSerial._enqueue_with_backpressure()`.
  - Detect/raw/MQTT publish queues use drop-oldest helper in `SocketThread`.
  - SDR process queues use `put_nowait`; drops are logged in some paths.
- Security:
  - `.env`, `cookies.txt`, and `login.txt` exist. Treat as sensitive.
  - `app.py` protects `/sdr/bmp/<filename>` against `..` and requires `.bmp`, then serves by basename from `BKDATASET/`.
- Vendor/source boundaries:
  - `SDR/bladeRF/` is vendor/submodule scale code, not normal app source.
  - Do not refactor vendor code unless requested.

## Known Hotspots

- `thread/SocketThread.py` is high-blast-radius: queues, detector execution, Socket.IO, MQTT, command subscriber state, and metrics all meet here.
- `draws/UbloxChart.py` mixes parsing, plotting, sleeps, prints, numeric algorithm, and spoofing decision.
- `thread/SDRThread.py` mixes hardware ingest, model definition, inference, rendering, snapshot storage, Socket.IO, and MQTT.
- `telemetry/mqtt_schema.py::build_ublox_command_message()` likely has a `NameError` because `topic_prefix` is referenced but not accepted as an argument.
- `RealtimeSpoofingPipeline.set_reference_svid()` stores `_reference_svid`, but current builders choose their own lowest common SVID and do not use that override.
- `RealtimeSpoofingPipeline.set_min_sat_count()` stores `_min_sat_count`, but current detector engines use their own `min_cluster_size` value.
- `templates/index.html` hardcodes Socket.IO host and still labels raw queue as durable.
- SDR runtime and SDR integration guide disagree on sample rate, preprocessing, colormap, normalization, and class labels.
- `requirements.txt` appears to be an environment freeze, not a minimal dependency manifest.

## Unknowns

- Unknown: validation basis for `draws/UbloxChart.py` slope threshold `delta_a = 0.0001`.
- Unknown: exact required u-blox receiver message-rate configuration for reliable `RXM-RAWX`, `NAV-PVT`, `NAV-SAT`, and `MON-SPAN` streams.
- Unknown: authoritative SDR model contract: live runtime vs `SDR/README_bladerf_integration.md`.
- Unknown: whether default MQTT credentials in `config.py` are intended for local testing only.
- Inference: the project is a research/prototype runtime with production-facing telemetry contracts, not yet a fully hardened production service.
