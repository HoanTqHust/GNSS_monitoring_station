# Code Structure

## Purpose

This file explains the code structure by responsibility so that a new developer can find the right edit point quickly.

## Group 1: Web Runtime

- `app.py`
  - creates the Flask app
  - registers the `/` and `/about` routes
  - initializes the durable raw queue DB
  - starts the serial-reading process
  - starts the Socket.IO background task

## Group 2: Configuration

- `config.py`
  - loads `.env`
  - stores runtime settings such as serial ports, buffer size, plotting interval, elevation mask, and server host/port

## Group 3: Ingestion and Data Synchronization

- `thread/ReadSerialThread.py`
  - opens `PORT1` and `PORT2`
  - reads `RXM-RAWX`, `NAV-PVT`, `NAV-SAT`, and `MON-SPAN`
  - writes `ubx_frame` events (full raw UBX payload) into the durable queue
  - creates `RAWXData` objects
  - pairs data when both receivers have matching observation time
  - writes synchronized `epoch_pair` events into the durable queue

## Group 4: Durable Event Queue

- `thread/DurableRawQueue.py`
  - stores append-only events in SQLite WAL
  - tracks consumer ACK offsets
  - replays unacked events (at-least-once)

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
  - reads data from durable queue with ACK offsets
  - measures CPU load
  - calls plotting functions
  - emits `update_image` to the frontend
  - emits `raw_data_batch` with raw frames

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
- For durability/retry behavior: update `thread/DurableRawQueue.py`
- For dashboard changes: update both `thread/SocketThread.py` and `templates/index.html`
- For algorithm changes: focus on `draws/UbloxChart.py`
- For runtime/config changes: review `config.py` and `.env`
