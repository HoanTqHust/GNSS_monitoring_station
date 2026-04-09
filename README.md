# Double Difference CP

## Introduction

This is a Python project for reading UBX data from u-blox GNSS devices, computing and visualizing carrier phase double differences in real time, and flagging possible spoofing behavior based on carrier phase trend similarity.

The application has three main layers:

- `app.py`: Flask + Socket.IO web server
- `thread/ReadSerialThread.py`: serial ingestion and sample synchronization for two receivers
- `draws/UbloxChart.py`: data processing, skyplot generation, spectrum plotting, and carrier phase difference plotting

## Repository Goals

- Collect UBX data from multiple serial ports
- Align paired samples by `rcvTow`
- Compute carrier phase differences between two receivers
- Generate GNSS monitoring plots
- Stream processed results to a web dashboard through Socket.IO

## High-Level Architecture

Main runtime flow:

1. `app.py` creates a `multiprocessing.Queue`.
2. A separate process runs `ReadSerial.read_serial()` to read GNSS data from two serial ports.
3. When both devices have matching `RXM-RAWX` and `NAV-PVT` timestamps, the synchronized sample set is pushed into the queue.
4. `SocketThread.background_thread()` consumes queued data on a `PLOT_INTERVAL` cadence.
5. `UbloxChart` generates skyplot, spectrum, and carrier phase difference images.
6. Flask-SocketIO emits the `update_image` event to the frontend in `templates/index.html`.

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
- Pairs samples when `round(rawx1.rcvTow) == round(rawx2.rcvTow)`
- Pushes the combined sample window into a `multiprocessing.Queue`

### 3. Data Processing and Plotting

- File: `draws/UbloxChart.py`
- Main responsibilities:
  - extract satellite information for skyplots
  - extract spectrum data from `MON-SPAN`
  - compute carrier phase differences between two receivers
  - filter satellites using `ELE_MASK`
  - estimate per-satellite trend coefficients with `LinearRegression`
  - mark spoofing when a cluster of satellites shares similar trend coefficients

### 4. Socket Background Worker

- File: `thread/SocketThread.py`
- Reads data from the queue
- Calls `UbloxChart` to generate base64 images
- Emits the `update_image` event to the frontend

### 5. Data Models

- `models/RAWXData.py`: wraps a parsed `RXM-RAWX` message
- `models/SatelliteData.py`: extracts per-satellite fields such as `prMes`, `cpMes`, `doMes`, `gnssId`, `svId`, and `sigId`

### 6. Supporting Tools

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
```

Quick meaning:

- `PORT1`, `PORT2`, `PORT3`: receiver serial ports
- `BUFFER_SAMPLES`: sliding-window sample buffer size
- `PLOT_INTERVAL`: plotting/update interval
- `FIX`: enables extra debug output
- `HOSTSOCKET`, `PORTSOCKET`: Flask-SocketIO bind address
- `ELE_MASK`: elevation threshold for satellite filtering

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
- There is currently no automated test suite for the main carrier phase / spoofing flow.
- Error handling and observability still rely heavily on `print`, not structured logging.

## Recommended Reading Order

If you continue working on this repository, read these files first:

1. `docs/context.md`
2. `docs/codebase-map.md`
3. `docs/structure.md`

These three files act as the project’s working memory and help new contributors understand the goal, flow, and main edit points quickly.
