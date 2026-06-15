# Project Context

Last source review: 2026-06-15.

## Current Role Truth

- This repository is a real-time GNSS integrity monitoring platform for spoofing and jamming detection.
- The main runtime is Python/Flask/Socket.IO with multiprocessing and thread queues.
- The system has two live frontends:
  - `/` for u-blox GNSS spoofing dashboard.
  - `/sdr` for bladeRF SDR jamming dashboard.
- Core memory files are `docs/context.md` and `docs/codebase-map.md`; use them before changing code.

## Runtime Summary

1. `app.py` initializes Flask, Socket.IO, logging to `all.log` and MQTT-filtered `mqtt.log`.
2. `app.py` creates:
   - one multiprocessing RAM ingress queue;
   - one detect thread queue;
   - one raw UBX thread queue;
   - shared metrics via `SocketThread.create_metrics()`.
3. `thread/ReadSerialThread.py` runs in a separate process and reads two serial ports from `config.PORT1` and `config.PORT2`.
4. `ReadSerial` uses `pyubx2.UBXReader` to parse UBX/NMEA and `thread/RTKLIBStage.py` to normalize:
   - `ubx_frame` events for every parsed frame;
   - `epoch_pair` events when both receivers have `RXM-RAWX` and `NAV-PVT` with matching rounded `rcvTow`.
5. `thread/SocketThread.py::router_thread()` fans out events:
   - `ubx_frame` -> raw queue;
   - `epoch_pair` -> detect queue.
6. `SocketThread.detect_consumer_thread()` runs `RealtimeSpoofingPipeline`, publishes MQTT detect/state messages, and emits Socket.IO `update_image`.
7. `SocketThread.raw_consumer_thread()` batches raw UBX frames for Socket.IO `raw_data_batch`, publishes raw UBX over MQTT through a dedicated worker queue, and periodically publishes `health/v1`.
8. If `config.SDR_ENABLED` is true, `thread/SDRThread.py` starts bladeRF reader/plotter processes plus result/MQTT worker threads.

## Main Data Contracts

- Internal RAM event envelope:
  - `seq`
  - `event_type`
  - `created_at_utc`
  - `payload`
- `ubx_frame.payload` contains:
  - `stage`
  - `received_at_utc`
  - `receiver`
  - `identity`
  - `tow_s`
  - `raw_len`
  - `raw_base64`
- `epoch_pair.payload` contains:
  - `rawx_1`, `nav_1`, `rawx_2`, `nav_2`
  - `skyplot_data_1`, `skyplot_data_2`
  - `spectrum_data_1`, `spectrum_data_2`
  - `tow_s`
- Realtime detector outputs are a map keyed by:
  - `sos_carrier`
  - `sos_smoothed_pseudorange`
  - `d3_carrier`
  - `d3_smoothed_pseudorange`
- MQTT topic families:
  - `raw/ublox/v1`
  - `detect/ublox/v1`
  - `state/position/v1`
  - `health/v1`
  - `detect/sdr/v1`
  - `raw/sdr/v1`
  - `cmd/init/v1`
  - `cmd/ack/v1`
  - inbound command subscriptions: `cmd/+/v1` and `cmd/+/+/v1`

## Spoofing Detection Truth

- `realtime/measurement_builders/carrier.py` builds fractional carrier-phase double differences for GPS L1 only (`gnssId == 0`, `sigId == 0`).
- `realtime/measurement_builders/smoothed_pseudorange.py` builds Hatch-filtered pseudorange double differences.
- `realtime/detector_engines/sos.py` computes mean squared DD residuals; low score means spoofing when threshold is set.
- `realtime/detector_engines/d3.py` marks satellites suspect when pairwise DD distance is within the similarity threshold; spoofing is true when suspect count reaches `min_cluster_size`.
- `realtime/pipeline.py` wires two measurement builders to four detector engines and writes JSONL records under `output_rt/<output_name>/events.jsonl`.
- `draws/UbloxChart.py` also runs a separate sliding-window visual detector using linear-regression slope clustering. This is independent from the realtime SoS/D3 detector outputs.

## Jamming / SDR Truth

- `thread/SDRThread.py` is the runtime SDR path used by `app.py`.
- It imports torch and bladeRF wrapper at module import time, so missing SDR dependencies can break `app.py` import even if `SDR_ENABLED` is false.
- Current runtime hardcodes major SDR parameters in `thread/SDRThread.py`:
  - sample rate `60e6`
  - center frequency `1575.42e6`
  - gain `20`
  - frame assembly `8 * 8192`
  - Hann STFT window `512`, overlap `384`, FFT `512`
  - custom colormap and 640x480 BMP output
- `config.py` also defines SDR env settings (`SDR_SAMPLE_RATE=5e6`, `SDR_GAIN=30`, etc.), but the live `SDRThread` constants do not use those values except device/snapshot/MQTT controls.
- `docs/sdr-flow-analysis.md` records a model-contract mismatch between `thread/SDRThread.py` and `SDR/README_bladerf_integration.md`. Treat SDR classifier output as unverified until the model preprocessing contract is reconciled.

## Configuration Defaults

- Serial ports:
  - `PORT1=/dev/ttyACM0`
  - `PORT2=/dev/ttyACM1`
- Web:
  - `HOSTSOCKET=0.0.0.0`
  - `PORTSOCKET=5000`
- Queue sizes:
  - `RAM_INGRESS_QUEUE_SIZE=500000`
  - `RAM_DETECT_QUEUE_SIZE=200000`
  - `RAM_RAW_QUEUE_SIZE=500000`
  - `RAM_RAW_MQTT_QUEUE_SIZE=200000`
- MQTT is enabled by default in `config.py` and has default broker credentials. Do not expose or copy secrets from `.env`.
- Realtime default thresholds:
  - `SOS_CARRIER_THRESHOLD=0.04`
  - `SOS_SMOOTHED_PSEUDORANGE_THRESHOLD=1.10`
  - `D3_CARRIER_SIMILARITY_THRESHOLD=0.001`
  - `D3_SMOOTHED_PSEUDORANGE_SIMILARITY_THRESHOLD=0.001`
  - `D3_MIN_CLUSTER_SIZE=3`

## Current Tests / Evidence

- Deterministic tests present:
  - `tests/test_ram_queue_flow.py`
  - `tests/test_mqtt_telemetry.py`
  - `tests/test_generate_drawio_diagrams.py`
- Useful validation commands:
  - `python3 -m unittest discover -s tests -v`
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v`
  - `python3 -m unittest discover -s tests -p 'test_generate_drawio_diagrams.py' -v`
  - `python3 realtime/test_runner.py`
- Hardware/manual commands:
  - `python app.py`
  - `python3 -m realtime.live_runner`
  - `python3 realtime/calibrate_thresholds.py --file1 <rx1.ubx> --file2 <rx2.ubx>`
  - `python log.py`
  - `bash record_ubx.sh`

## Important Findings / Risks

- `telemetry/mqtt_schema.py::build_ublox_command_message()` references `topic_prefix` but does not accept it in the function signature. This is a likely bug if that helper is used.
- `templates/index.html` connects Socket.IO to fixed `http://192.168.5.2:5000` instead of the current host.
- `templates/index.html` labels the raw panel as "Durable Queue", but current runtime is RAM queue based.
- `draws/UbloxChart.py::process_ubx_data()` subtracts `dps[idx,1]` when any satellite exists; this is an index-based reference choice and may be fragile.
- `ReadSerial.read_serial()` catches broad exceptions and continues forever; logs are required before changing behavior.
- `SocketThread` catches broad exceptions in router/detect/raw loops; check `all.log` and `mqtt.log` before patching.
- `.env`, `cookies.txt`, and `login.txt` exist in the repo. Treat as sensitive; do not print contents.
- `requirements.txt` is not a minimal project dependency list; it includes many unrelated environment packages.
- The source tree includes huge vendor/build areas (`SDR/bladeRF/`, `venv/`, generated output dirs). Do not treat those as primary application source unless explicitly working on bladeRF vendor integration.
- `git status --short` currently shows untracked vendor subtrees:
  - `SDR/bladeRF/host/utilities/bladeRF-fsk/`
  - `SDR/bladeRF/thirdparty/analogdevicesinc/no-OS/`

## Documentation Update Rule

- Update `docs/context.md` when a command changes architectural truth, runtime data flow, operational defaults, or known risks.
- Update `docs/codebase-map.md` when adding/removing modules, changing entrypoints, changing validation commands, or changing cross-module dependencies.

## Report / Architecture Diagram Artifacts (2026-06-15)

- `scripts/generate_drawio_diagrams.py` generates editable draw.io XML diagrams, not embedded raster images.
- Architecture outputs:
  - combined file: `docs/diagrams/architecture_diagrams.drawio`
  - individual files: `docs/diagrams/hardware_flow.drawio`, `docs/diagrams/system_diagram.drawio`
- Report figure outputs:
  - combined file: `Hinhve/report_figures.drawio`
  - individual editable files under `Hinhve/*.drawio`
- Regenerate with:
  - `python3 scripts/generate_drawio_diagrams.py --output-root .`
