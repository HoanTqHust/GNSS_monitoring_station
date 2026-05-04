# Code Structure

## Purpose

This file explains the code structure by responsibility so that a new developer can find the right edit point quickly.

## Group 1: Web Runtime

- `app.py`
  - creates the Flask app
  - registers the `/` and `/about` routes
  - initializes RAM ingress/detect/raw queues
  - starts the serial-reading process
  - starts router + detect consumer + raw consumer background tasks

## Group 2: Configuration

- `config.py`
  - loads `.env`
  - stores runtime settings such as serial ports, buffer size, plotting interval, elevation mask, and server host/port

## Group 3: Ingestion and Data Synchronization

- `thread/ReadSerialThread.py`
  - opens `PORT1` and `PORT2`
  - reads `RXM-RAWX`, `NAV-PVT`, `NAV-SAT`, and `MON-SPAN`
  - calls RTKLIB-stage normalization for parsed frames
  - writes `ubx_frame` events (full raw UBX payload) into RAM ingress queue
  - pairs data when both receivers have matching observation time
  - writes synchronized `epoch_pair` events into RAM ingress queue

## Group 4: RTKLIB Stage Adapter

- `thread/RTKLIBStage.py`
  - normalizes parsed UBX data into RTKLIB-stage payloads
  - provides frame payload and synchronized epoch payload builders

## Group 5: Data Models

- `models/RAWXData.py`
  - converts a parsed `RXM-RAWX` message into an object with `rcvTow`, `week`, and `satData`
- `models/SatelliteData.py`
  - extracts per-satellite measurement fields from the parsed UBX object

## Group 6: Processing and Visualization

- `draws/UbloxChart.py`
  - `parseSatelliteInfo()`: extracts skyplot satellite information
  - `create_skyplot()`: renders the skyplot image
  - `processDataMonSpan()`: extracts spectrum data
  - `create_spectrum_plot()`: renders the spectrum plot
  - `calc_pseudorange()`: computes the values used for receiver comparison
  - `process_ubx_data()`: computes DPS, fits regressions, and detects suspicious satellite clusters
  - `raw2Image*()`: converts generated plots to base64 strings for the web client

## Group 7: Streaming to the Client

- `thread/SocketThread.py`
  - routes RAM ingress events into detect and raw consumer queues
  - applies drop policy when bounded queues are full
  - measures CPU load
  - calls detector and plotting functions on detect stream
  - emits `update_image` to the frontend
  - emits `raw_data_batch` with raw frames from raw stream

## Group 8: Frontend

- `templates/index.html`
  - main dashboard
  - listens for `update_image`
  - listens for `raw_data_batch`
  - updates skyplot, spectrum, DPS, CPU load, and spoofing status
- `templates/about.html`
  - simple about page

## Group 9: Logging and Operational Utilities

- `logs/RawDataLogger.py`
  - writes raw UBX data into date-based folders
- `log.py`
  - logs data from three receivers
- `record_ubx.sh`
  - quick shell-based recording script using `dd`
- `send_command.py`
  - sends UBX commands to disable NMEA, update port protocol settings, and save configuration
- `test.py`
  - simple direct-read script for one serial port

## Suggested Reading Order for Onboarding

1. `README.md`
2. `docs/context.md`
3. `docs/codebase-map.md`
4. `app.py`
5. `thread/ReadSerialThread.py`
6. `thread/SocketThread.py`
7. `draws/UbloxChart.py`

## Main Edit Guidance

- For ingestion changes: start with `thread/ReadSerialThread.py`
- For payload normalization stage: update `thread/RTKLIBStage.py`
- For queue routing/overflow behavior: update `thread/SocketThread.py`
- For dashboard changes: update both `thread/SocketThread.py` and `templates/index.html`
- For algorithm changes: focus on `draws/UbloxChart.py`
- For runtime/config changes: review `config.py` and `.env`
