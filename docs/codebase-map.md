# Codebase Map

Last source review: 2026-06-15.

## Snapshot

- Purpose: real-time GNSS spoofing detection from two u-blox receivers plus SDR jamming detection from USRP X300 or legacy bladeRF.
- Primary stack: Python, Flask, Flask-SocketIO, multiprocessing/threading queues, pyserial, pyubx2, NumPy, matplotlib, scikit-learn, PyTorch, paho-mqtt, UHD Python API, legacy bladeRF Python bindings.
- Main runtime: `app.py`.
- Main dashboards:
  - `/` -> `templates/index.html`
  - `/sdr` -> `templates/sdr.html`
- Source review scope: application source only. Excluded vendor/generated areas include `SDR/bladeRF/`, `venv/`, `__pycache__/`, `output_rt/`, `output_sdr/`, `BKDATASET/`, `logs/`, `data/`.

## Top-Level Layout

- `app.py`: Flask routes, Socket.IO bootstrap, queue creation, serial process startup, SocketThread background tasks, optional SDR startup.
- `config.py`: `.env` loading, queue sizes, thresholds, MQTT settings, SDR settings.
- `.env.example`: shareable runtime template for GNSS ports, MQTT placeholders, and USRP/bladeRF SDR source selection.
- `thread/`: live runtime workers for serial ingest, RAM routing, Socket.IO/MQTT streaming, SDR capture/classification.
- `realtime/`: detector pipeline, measurement builders, detector engines, JSONL writer, live/test/calibration runners.
- `telemetry/`: MQTT schema builders, publisher adapter, command subscriber/handler.
- `models/`: light wrappers around parsed `RXM-RAWX` satellite measurements.
- `draws/`: plot generation and sliding-window carrier-phase visual detector.
- `templates/`: browser UI for GNSS and SDR dashboards.
- `sdr_sources/`: selectable SDR source adapters for USRP X300 and legacy bladeRF.
- `SDR/src/`: legacy bladeRF RX/TX wrapper library.
- `SDR/tests/`, `SDR/examples/`: hardware-oriented SDR utilities.
- `tests/`: deterministic unit tests for RAM queue helpers, MQTT telemetry, MQTT identity, and EMQX provisioning helpers.
- `scripts/`: operator utilities, including EMQX MQTT device-user provisioning.
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
| Config | Centralizes env/defaults for ports, queues, thresholds, MAC-derived MQTT device identity, MQTT, SDR | `config.py` | changing runtime defaults, env names, or per-device MQTT identity rules | `.env`, `/sys/class/net`, `os.environ` | all runtime modules |
| Serial ingest | Reads two u-blox receivers, parses UBX/NMEA, emits RAM events | `thread/ReadSerialThread.py`, `thread/RTKLIBStage.py` | changing serial ports, message parsing, event payload shape, TOW pairing | `serial`, `pyubx2`, `models`, `config.py` | `app.py`, `SocketThread.router_thread()` |
| RAWX model | Wraps pyubx2 `RXM-RAWX` fields into simple objects | `models/RAWXData.py`, `models/SatelliteData.py` | adding/removing satellite fields consumed downstream | pyubx2 parsed object shape | serial ingest, realtime, plotting, MQTT schema |
| RAM router / stream worker | Routes events, runs detect/raw consumers, emits Socket.IO, publishes MQTT | `thread/SocketThread.py` | changing queue policy, Socket.IO payloads, MQTT publication, metrics | `realtime`, `telemetry`, `draws`, `psutil`, queues | `app.py`, dashboards, MQTT subscribers |
| Realtime spoofing pipeline | Builds carrier/smoothed PR measurement frames and runs SoS/D3 engines | `realtime/pipeline.py`, `realtime/measurement_builders/*`, `realtime/detector_engines/*`, `realtime/types.py` | changing detector math, thresholds, output fields, output folders | `config.py`, `models`-compatible RAWX objects, NumPy | `SocketThread`, `live_runner`, `test_runner`, calibration |
| Realtime output/calibration | Writes detector JSONL and estimates thresholds from clean UBX | `realtime/output_writer.py`, `realtime/calibrate_thresholds.py`, `realtime/live_runner.py`, `realtime/test_runner.py` | smoke testing, threshold calibration, standalone live operation | pyubx2, serial, realtime builders | operators/developers |
| Plotting + visual detector | Generates skyplot/spectrum/DPS images and slope-cluster spoofing bool | `draws/UbloxChart.py` | changing dashboard plots or the sliding-window visual detector | NumPy, matplotlib, sklearn, `config.ELE_MASK` | `SocketThread.detect_consumer_thread()` |
| MQTT schema | Builds versioned topic payloads for UBX raw/detect/position/health, SDR detect/raw chunks, commands/ACK | `telemetry/mqtt_schema.py` | changing external server contract or payload normalization | runtime event payloads | `SocketThread`, `SDRThread`, tests |
| MQTT publish | Validates settings and publishes JSON through paho-mqtt with QoS 1 | `telemetry/mqtt_publisher.py` | changing broker connection, QoS, retain/wait behavior | paho-mqtt | `SocketThread`, `SDRThread`, tests |
| MQTT command subscriber | Subscribes command topics, dedupes command IDs, configures/resets realtime pipeline, publishes ACK | `telemetry/mqtt_subscriber.py` | adding commands, changing command topic grammar, changing ACK semantics | paho-mqtt, `config.py`, `RealtimeSpoofingPipeline` | `SocketThread.detect_consumer_thread()` |
| SDR runtime | Drains selected SDR source frames, renders BMP, runs classifier, emits UI result, publishes threat snapshot | `thread/SDRThread.py` | changing SDR frame assembly, jamming classifier runtime, snapshot logic, SDR MQTT publish, `/sdr` behavior | torch, PIL, matplotlib, multiprocessing queues, telemetry, `sdr_sources` | `app.py`, `/sdr`, MQTT subscribers |
| SDR source adapters | Selects and reads IQ from USRP X300 over UHD or legacy bladeRF behind one `receive_with_raw()` contract | `sdr_sources/*` | changing SDR hardware selection, USRP/bladeRF RX setup, source validation, raw-byte compatibility | UHD Python API or bladeRF wrapper, NumPy, `config.py` settings | `thread/SDRThread.py`, source tests |
| Legacy SDR wrapper | Minimal bladeRF RX/TX abstraction | `SDR/src/common.py`, `SDR/src/receiver.py`, `SDR/src/transmitter.py` | changing legacy bladeRF sync config or IQ conversion | `bladerf._bladerf`, NumPy | `sdr_sources.bladerf_source`, SDR examples/tests |
| Frontend UI | Shows GNSS plots/cards/raw table/summary chart and SDR spectrogram/classifier | `templates/index.html`, `templates/sdr.html`, `templates/about.html` | changing Socket.IO event handling, display fields, client endpoints | Socket.IO CDN, Chart.js CDN, Flask routes | browser users |
| Tests | Deterministic helper/schema tests | `tests/test_ram_queue_flow.py`, `tests/test_mqtt_telemetry.py`, `tests/test_mqtt_device_identity.py`, `tests/test_emqx_provisioning.py`, `tests/test_ublox_dashboard_config.py` | validating queue, MQTT schema, per-device MQTT identity, EMQX provisioning, and u-blox command generation changes | unittest, fake objects | developers/agents |
| Ops utilities | Manual capture/config/provisioning scripts | `scripts/configure_ublox_dashboard_messages.py`, `scripts/ublox_dashboard_config.py`, `scripts/provision_current_device.sh`, `scripts/provision_emqx_device.py`, `log.py`, `record_ubx.sh`, `send_command.py` | EMQX MQTT user provisioning, receiver output configuration, raw UBX capture, local debug | EMQX REST API, serial, pyubx2 | operators |

## Interaction Map

### GNSS Request / Data Flow

1. Browser loads `/` from `app.py`.
2. `templates/index.html` loads Socket.IO and connects to `http://192.168.5.2:5000`.
3. `app.py` starts `ReadSerial.read_serial()` in a multiprocessing process.
4. `ReadSerial` reads `PORT1` and `PORT2` at 115200 baud.
5. `ReadSerial._should_emit_raw_frame()` checks `RAW_UBX_ALLOWED_IDENTITIES`; allowed frames become raw `ubx_frame` payloads through `RTKLIBStage.normalize_frame()`.
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
4. `reader_process` opens the selected source through `sdr_sources.factory.open_sdr_receiver_source()`:
   - default `SDR_SOURCE=usrp_x300`: UHD `MultiUSRP(SDR_USRP_ARGS)` with `addr=192.168.5.111`, RX `StreamArgs("fc32", "sc16")`, and continuous `recv()`;
   - legacy `SDR_SOURCE=bladerf`: `SDR/src/common.py::BladeRFSdr`.
5. USRP mode configures rate/frequency/gain/optional antenna; it does not call `set_rx_bandwidth()` by default because the deployed X300 UBX-40 v2 probe reports fixed RX bandwidth `40000000.0 Hz`. Override with `SDR_USRP_SET_BANDWIDTH=1` only for hardware that accepts the requested bandwidth.
6. USRP mode tunes RX frequency through `uhd.types.TuneRequest`; UHD Python 3.15 on RK3588 rejected direct `set_rx_freq(float, channel)`.
7. USRP mode reconstructs interleaved int16 raw bytes from `complex64` samples so the existing snapshot/MQTT raw path still receives `raw_bytes`; bladeRF mode keeps original `Receiver.receive_with_raw()` bytes.
8. `plotter_process` renders BMP spectrograms under `BKDATASET/`, runs ResNet18 inference if model loads, and sends `sdr_classify` results.
9. If jamming is detected above `SDR_JAMMING_CONFIDENCE_THRESHOLD`, it saves a bounded raw snapshot under `output_sdr/` and attaches an MQTT event.
10. SDR MQTT worker publishes event-driven outputs only when a threat snapshot exists:
   - `detect/sdr/v1`
   - chunked `raw/sdr/v1`
11. `templates/sdr.html` listens for `sdr_classify`; it separately polls `/sdr/latest_bmp` every 500 ms for the latest BMP.

## Change Guide

- If changing serial ingestion:
  - start with `thread/ReadSerialThread.py` and `thread/RTKLIBStage.py`;
  - keep `ubx_frame` and `epoch_pair` payload contracts aligned with `SocketThread` and `telemetry/mqtt_schema.py`;
  - keep `RAW_UBX_ALLOWED_IDENTITIES` aligned with the dashboard-required identities unless full pass-through raw logging is explicitly needed;
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
- If changing MQTT device identity or provisioning:
  - edit `telemetry/mqtt_identity.py` for device ID derivation and validation rules;
  - edit `config.py` only for runtime env/default wiring;
  - edit `scripts/provision_emqx_device.py` for EMQX REST API user creation/rotation;
  - edit `scripts/provision_current_device.sh` for operator-side wrapper behavior;
  - update `tests/test_mqtt_device_identity.py` and `tests/test_emqx_provisioning.py`;
  - never hardcode or print real `.env` secrets.
- If changing MQTT commands:
  - edit `telemetry/mqtt_subscriber.py`;
  - add tests for `_build_command_topics()`, `_dispatch_command()`, `_on_message()`, and ACK output.
- If changing SDR classifier behavior:
  - read `docs/sdr-flow-analysis.md` first;
  - decide whether runtime or `SDR/README_bladerf_integration.md` is authoritative;
  - update `thread/SDRThread.py`, `SDR/README_bladerf_integration.md`, and tests/docs together.
- If changing USRP X300 ingest:
  - edit `config.py` for `SDR_SOURCE`, `SDR_USRP_*`, and SDR rate/frequency/gain/bandwidth defaults;
  - edit `sdr_sources/usrp_source.py`;
  - keep `sdr_sources/factory.py` mapping aligned with `SDR_SOURCE` aliases;
  - validate adapter behavior with `tests/test_usrp_sdr_source.py`;
  - hardware-smoke on RK3588 with UHD installed and `uhd_find_devices --args "addr=192.168.5.111"`.
- If fixing frontend Socket.IO host:
  - edit `templates/index.html` at the `io("http://192.168.5.2:5000")` call;
  - prefer same-origin `io()` unless cross-host behavior is required.
- If touching sensitive/config files:
  - do not print `.env`, `cookies.txt`, or `login.txt`;
  - use `.env.example` or docs placeholders for examples.

## Validation Guide

- Full available unit suite:
  - `python3 -m unittest discover -s tests -v`
- USRP SDR adapter tests:
  - `python3 -m unittest discover -s tests -p 'test_usrp_sdr_source.py' -v`
- RAM queue helper tests:
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v`
- MQTT schema/publisher/subscriber tests:
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v`
- MQTT device identity tests:
  - `python3 -m unittest discover -s tests -p 'test_mqtt_device_identity.py' -v`
  - If the local `.env` still has legacy MQTT identity values, run with explicit test credentials: `MQTT_DEVICE_ID=device_abcd MQTT_USERNAME=device_abcd MQTT_PASSWORD=secret python3 -m unittest discover -s tests -p 'test_mqtt_device_identity.py' -v`
- EMQX provisioning helper tests:
  - `python3 -m unittest discover -s tests -p 'test_emqx_provisioning.py' -v`
  - If the local `.env` still has legacy MQTT identity values, run with explicit test credentials: `MQTT_DEVICE_ID=device_abcd MQTT_USERNAME=device_abcd MQTT_PASSWORD=secret python3 -m unittest discover -s tests -p 'test_emqx_provisioning.py' -v`
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
  - `python3 scripts/configure_ublox_dashboard_messages.py --dry-run`
  - `python3 scripts/configure_ublox_dashboard_messages.py --no-save`
  - `python3 scripts/configure_ublox_dashboard_messages.py`
  - `python send_command.py`
- USRP hardware smoke requires UHD Python bindings and reachable X300:
  - `uhd_find_devices --args "addr=192.168.5.111"`
  - `uhd_usrp_probe --args "addr=192.168.5.111"`
  - If probe warns that UDP socket buffers are too small, configure at least the reported minimum; Ettus X3x0 docs recommend `sudo sysctl -w net.core.rmem_max=33554432` and `sudo sysctl -w net.core.wmem_max=33554432` before sustained streaming.
  - Verified RK3588/X300 probe evidence: after setting `net.core.wmem_max=33554432`, probe completed with `FPGA Version: 36.0`, detected UBX-40 v2 RX/TX daughterboards, and reported fixed RX bandwidth `40000000.0 Hz`.
  - `python app.py`
- Legacy bladeRF hardware tests require bladeRF hardware and dependencies:
  - `python -m pytest SDR/tests/test_bladerf.py`
  - `python SDR/examples/receive_loop.py`

## Cross-Cutting Concerns

- Config/env:
  - `config.py` loads `.env` at import time.
  - `.env` is local/ignored; `.env.example` is the committed template and must use placeholders only.
  - `RAW_UBX_ALLOWED_IDENTITIES` defaults to `RXM-RAWX,NAV-PVT,NAV-SAT,MON-SPAN`; use `*` only for pass-through raw logging.
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
- SDR worker processes log reader/plotter/classifier startup and errors through structured logging to `all.log`.
- Backpressure:
  - Ingress queue uses drop-new in `ReadSerial._enqueue_with_backpressure()`.
  - Detect/raw/MQTT publish queues use drop-oldest helper in `SocketThread`.
  - SDR process queues use `put_nowait`; drops are logged in some paths.
- Security:
  - `.env`, `cookies.txt`, and `login.txt` are sensitive if present. Treat them as secrets and do not print contents.
  - `scripts/provision_emqx_device.py` needs EMQX REST API credentials only during provisioning; deployed app runtime should keep only device-scoped MQTT credentials.
  - `app.py` protects `/sdr/bmp/<filename>` against `..` and requires `.bmp`, then serves by basename from `BKDATASET/`.
- SDR source:
  - default is `usrp_x300` at `192.168.5.111`;
  - legacy bladeRF can be restored with `SDR_SOURCE=bladerf`.
- Vendor/source boundaries:
  - `SDR/bladeRF/` is vendor/submodule scale code, not normal app source.
  - Do not refactor vendor code unless requested.

## Known Hotspots

- `thread/SocketThread.py` is high-blast-radius: queues, detector execution, Socket.IO, MQTT, command subscriber state, and metrics all meet here.
- `draws/UbloxChart.py` mixes parsing, plotting, sleeps, prints, numeric algorithm, and spoofing decision.
- `thread/SDRThread.py` still mixes model definition, inference, rendering, snapshot storage, Socket.IO, and MQTT; SDR hardware source adapters now live in `sdr_sources/`.
- `telemetry/mqtt_schema.py::build_ublox_command_message()` likely has a `NameError` because `topic_prefix` is referenced but not accepted as an argument.
- `RealtimeSpoofingPipeline.set_reference_svid()` stores `_reference_svid`, but current builders choose their own lowest common SVID and do not use that override.
- `RealtimeSpoofingPipeline.set_min_sat_count()` stores `_min_sat_count`, but current detector engines use their own `min_cluster_size` value.
- `templates/index.html` hardcodes Socket.IO host and still labels raw queue as durable.
- SDR runtime and SDR integration guide still disagree on preprocessing, colormap, normalization, and class labels; runtime now at least consumes `config.py` rate/frequency/gain/bandwidth.
- `requirements.txt` appears to be an environment freeze, not a minimal dependency manifest.

## Unknowns

- Unknown: validation basis for `draws/UbloxChart.py` slope threshold `delta_a = 0.0001`.
- Unknown: exact u-blox firmware coverage for every disabled message in `scripts/ublox_dashboard_config.py`; unsupported messages may be NAKed or ignored, but the target dashboard messages are still explicitly enabled afterward.
- Unknown: authoritative SDR model contract: live runtime vs `SDR/README_bladerf_integration.md`.
- Unknown: exact UHD/FPGA/network tuning needed for sustained USRP X300 streaming on the deployed RK3588 interface; the repo dev environment used for this review did not have `uhd` installed.
- Unknown: whether default MQTT credentials in `config.py` are intended for local testing only.
- Inference: the project is a research/prototype runtime with production-facing telemetry contracts, not yet a fully hardened production service.
