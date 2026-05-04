# Double Difference CP

## Introduction

This is a Python project for reading UBX data from u-blox GNSS devices, computing and visualizing carrier phase double differences in real time, and flagging possible spoofing behavior based on carrier phase trend similarity.

The application has four main layers:

- `app.py`: Flask + Socket.IO web server
- `thread/ReadSerialThread.py`: serial ingestion and durable queue producer for two receivers
- `thread/DurableRawQueue.py`: SQLite WAL queue with per-consumer ACK offsets
- `draws/UbloxChart.py`: data processing, skyplot generation, spectrum plotting, and carrier phase difference plotting

## Repository Goals

- Collect UBX data from multiple serial ports
- Align paired samples by `rcvTow`
- Compute carrier phase differences between two receivers
- Generate GNSS monitoring plots
- Stream processed results to a web dashboard through Socket.IO

## High-Level Architecture

Main runtime flow:

1. `app.py` initializes a durable SQLite queue database.
2. A separate process runs `ReadSerial.read_serial()` to read GNSS data from two serial ports.
3. Serial ingestion writes:
   - `ubx_frame` events (full raw UBX payload in base64)
   - `epoch_pair` events (synchronized RAWX/NAV pair for detector processing)
4. `SocketThread.background_thread()` consumes durable queue events using ACK offsets.
5. `UbloxChart` generates skyplot, spectrum, and carrier phase difference images from `epoch_pair` records.
6. Flask-SocketIO emits:
   - `update_image` for detector/plot updates
   - `raw_data_batch` for raw stream monitoring in the frontend

## Directory Structure

```text
double_difference_cp/
|-- app.py
|-- config.py
|-- requirements.txt
|-- send_command.py
|-- log.py
|-- record_ubx.sh
|-- models/
|   |-- RAWXData.py
|   `-- SatelliteData.py
|-- thread/
|   |-- DurableRawQueue.py
|   |-- ReadSerialThread.py
|   `-- SocketThread.py
|-- draws/
|   `-- UbloxChart.py
|-- logs/
|   `-- RawDataLogger.py
|-- templates/
|   |-- index.html
|   `-- about.html
`-- docs/
    |-- context.md
    |-- codebase-map.md
    `-- structure.md
```

## Main Components

### 1. Web Server

- File: `app.py`
- Uses `Flask`, `Flask-CORS`, and `Flask-SocketIO`
- Exposes two routes:
  - `/`: main dashboard
  - `/about`: simple about page

### 2. GNSS Data Ingestion and Synchronization

- File: `thread/ReadSerialThread.py`
- Opens `config.PORT1` and `config.PORT2`
- Uses `pyubx2.UBXReader` to read:
  - `RXM-RAWX`
  - `NAV-PVT`
  - `NAV-SAT`
  - `MON-SPAN`
- Emits one durable event per parsed UBX frame (`ubx_frame`)
- Pairs samples when `round(rawx1.rcvTow) == round(rawx2.rcvTow)` and writes `epoch_pair` events

### 3. Durable Queue

- File: `thread/DurableRawQueue.py`
- Uses SQLite WAL mode
- Stores events in append-only sequence order
- Tracks consumer ACK offsets for replay and retry behavior
- Enables at-least-once delivery semantics across process restarts

### 4. Data Processing and Plotting

- File: `draws/UbloxChart.py`
- Main responsibilities:
  - extract satellite information for skyplots
  - extract spectrum data from `MON-SPAN`
  - compute carrier phase differences between two receivers
  - filter satellites using `ELE_MASK`
  - estimate per-satellite trend coefficients with `LinearRegression`
  - mark spoofing when a cluster of satellites shares similar trend coefficients

### 5. Socket Background Worker

- File: `thread/SocketThread.py`
- Reads from durable queue using consumer ID + ACK offset
- Runs realtime detectors from `epoch_pair` events
- Calls `UbloxChart` to generate base64 images
- Emits:
  - `update_image` event to frontend
  - `raw_data_batch` event with raw frame batches

### 6. Data Models

- `models/RAWXData.py`: wraps a parsed `RXM-RAWX` message
- `models/SatelliteData.py`: extracts per-satellite fields such as `prMes`, `cpMes`, `doMes`, `gnssId`, `svId`, and `sigId`

### 7. Supporting Tools

- `send_command.py`: sends UBX commands to configure the receiver
- `log.py`: logs raw UBX data from three serial ports into `logs_data/YYYY-MM-DD/`
- `record_ubx.sh`: captures data from three serial ports with `dd`
- `test.py`: simple script for reading UBX data directly from one serial port

## Environment Variables

The repo loads runtime settings from `.env` through `config.py`:

```env
PORT1=/dev/ttyACM0
PORT2=/dev/ttyACM1
PORT3=/dev/ttyACM2
BUFFER_SAMPLES=150
PLOT_INTERVAL=1
FIX=0
HOSTSOCKET=0.0.0.0
PORTSOCKET=5000
ELE_MASK=13
RAW_QUEUE_DB_PATH=logs_data/raw_bus.sqlite3
RAW_QUEUE_CONSUMER_ID=socket_pipeline
RAW_QUEUE_BATCH_SIZE=200
RAW_QUEUE_POLL_INTERVAL=0.05
RAW_EMIT_BATCH_SIZE=100
```

Quick meaning:

- `PORT1`, `PORT2`, `PORT3`: receiver serial ports
- `BUFFER_SAMPLES`: sliding-window sample buffer size
- `PLOT_INTERVAL`: plotting/update interval
- `FIX`: enables extra debug output
- `HOSTSOCKET`, `PORTSOCKET`: Flask-SocketIO bind address
- `ELE_MASK`: elevation threshold for satellite filtering
- `RAW_QUEUE_*`: durable queue storage and consumer tuning knobs

## How to Run

### 1. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pyubx2
```

Important note: the code imports `pyubx2`, but that package does not appear in `requirements.txt`, so it must be installed separately if you want to run the repo as-is.

### 2. Configure the environment

- Update `.env` with the correct serial devices for your machine
- Make sure the current user has permission to access `/dev/ttyACM*`

### 3. Start the application

```bash
python app.py
```

By default, the server listens on `0.0.0.0:5000`.

## Web Dashboard

The dashboard in `templates/index.html` displays:

- CPU load
- spoofing status
- carrier phase difference plot
- spectrum view for both devices
- skyplot view for both devices
- a raw UBX stream panel (sequence, gaps, duplicate replay indicators)

Important note:

- The frontend currently hard-codes the Socket.IO endpoint as `http://192.168.5.2:5000`.
- If the server IP changes, `templates/index.html` must be updated.

## Additional Documentation

- [docs/context.md](docs/context.md): project context, operational notes, and business/domain summary
- [docs/codebase-map.md](docs/codebase-map.md): module map and code change guide
- [docs/structure.md](docs/structure.md): code structure overview by responsibility

## Important Notes

- `requirements.txt` is very large and does not reflect the minimal runtime dependencies of the current repo.
- The frontend depends on a fixed IP address.
- The repo contains files such as `cookies.txt`, `login.txt`, and `.env`; these should be treated as sensitive data.
- Automated tests currently cover durable queue semantics (`tests/test_durable_raw_queue.py`), but there is still no broad automated suite for the end-to-end spoofing pipeline.
- Error handling and observability still rely heavily on `print`, not structured logging.

## Recommended Reading Order

If you continue working on this repository, read these files first:

1. `docs/context.md`
2. `docs/codebase-map.md`
3. `docs/structure.md`

These three files act as the project’s working memory and help new contributors understand the goal, flow, and main edit points quickly.
