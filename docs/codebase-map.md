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
| Serial ingestion | Reads UBX messages from two receivers, synchronizes samples, pushes data into the queue | `thread/ReadSerialThread.py` | changing serial ports, message types, or synchronization logic | `serial`, `pyubx2`, `models/RAWXData.py`, `config.py` | `app.py`, `thread/SocketThread.py` |
| Realtime detector skeleton | Converts normalized epochs into measurement frames and writes separated detector outputs | `realtime/pipeline.py`, `realtime/measurement_builders/*`, `realtime/detector_engines/*`, `realtime/output_writer.py` | adding live SoS/D3 flow, changing output format, preparing MQTT/REST integration | `models`-compatible RAWX objects, `numpy`, filesystem output | future live detector workers or publishers |
| Standalone live runner | Reads live UBX streams and feeds synchronized epochs into the realtime pipeline | `realtime/live_runner.py` | running the detector stack without touching the web app runtime | `serial`, `pyubx2`, `config.py`, `models/RAWXData.py`, `realtime/pipeline.py` | operators, live smoke tests |
| Visualization + detection | Computes carrier phase differences, creates skyplot/spectrum/DPS images, flags spoofing | `draws/UbloxChart.py` | changing the algorithm, plotting, or thresholds | `numpy`, `matplotlib`, `sklearn`, `config.py` | `thread/SocketThread.py` |
| Data model | Converts parsed UBX messages into Python objects for downstream processing | `models/RAWXData.py`, `models/SatelliteData.py` | changing extracted fields or per-satellite metadata | parsed UBX objects | `thread/ReadSerialThread.py`, `draws/UbloxChart.py` |
| Streaming worker | Pulls queue data, encodes images, emits frontend events | `thread/SocketThread.py` | changing emit cadence, payload shape, or metrics | `draws/UbloxChart.py`, `psutil`, `config.py` | `app.py`, frontend |
| Logging / capture | Persists raw UBX data for debugging and later analysis | `logs/RawDataLogger.py`, `log.py`, `record_ubx.sh` | changing log format, storage path, or number of receivers | `os`, `datetime`, `serial`, `pyubx2` | operators, debugging flow |
| Device config tools | Sends UBX commands to configure the receiver | `send_command.py` | changing baudrate, message enablement, or persisted receiver config | `serial`, custom UBX message builder | operators |

## Interaction Map

- Request flow:
  - The browser opens `/` in `app.py`.
  - `templates/index.html` loads the Socket.IO client.
  - The client listens for the `update_image` event.
- Data flow:
  - Serial device -> `ReadSerial.read_serial()` -> `data_queue` -> `SocketThread.background_thread()` -> `UbloxChart` -> base64 PNG -> browser
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
- If changing the dashboard payload:
  - edit `thread/SocketThread.py` and `templates/index.html`
  - keep payload keys aligned between server and client
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
- Manual capture utilities:
  - `python log.py`
  - `bash record_ubx.sh`
  - `python test.py`
- Regression attention:
  - whether the queue fills and drops samples
  - whether `rcvTow` synchronization remains correct
  - whether the frontend still receives `update_image`
  - whether satellite filtering by `ELE_MASK` still behaves correctly
  - whether the hard-coded frontend IP still matches the actual server

## Cross-Cutting Concerns

- Config and env:
  - `config.py` loads `.env` and centralizes runtime settings
- Auth:
  - there is no authentication in the web app
- Persistence:
  - raw UBX logging is the only persistence currently present
- Testing:
  - there is no automated unit or integration test suite
- Build and deploy:
  - no build or deployment pipeline is present in the repo
- Hotspots:
  - `draws/UbloxChart.py` carries the most mixed responsibilities
  - `thread/ReadSerialThread.py` and `thread/SocketThread.py` rely on broad `except Exception` handling and `print`
  - `templates/index.html` is tightly coupled to a specific server address

## Unknowns

- Unknowns:
  - the repo does not explain the source or validation basis for the spoofing threshold `delta_a = 0.0001`
  - there is no documentation describing the exact expected UBX message configuration for each receiver
  - `requirements.txt` appears to describe a larger environment, not the minimal dependency set for this repo
- Inference:
  - this looks more like a GNSS research or experiment codebase than a production-hardened application because of the debugging scripts and manual logging workflow
