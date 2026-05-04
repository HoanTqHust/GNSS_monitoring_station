# Double Difference CP

## Introduction

This project reads UBX data from u-blox GNSS devices, computes carrier phase double differences in real time, and streams spoofing indicators to a web dashboard.

Current runtime is RAM-only (no SQLite runtime queue).

## Runtime Architecture

```text
u-blox serial
   -> RTKLIB stage adapter (normalize payload)
   -> RAM ingress queue (multiprocessing.Queue)
   -> router fan-out
      -> consumer 1 (detect) -> update_image
      -> consumer 2 (raw)    -> raw_data_batch
```

### Main Flow

1. `app.py` creates one ingress queue and two consumer queues in RAM.
2. A serial process runs `ReadSerial.read_serial()` and publishes events:
   - `ubx_frame`
   - `epoch_pair`
3. Router thread in `SocketThread` fans out events:
   - `ubx_frame` -> raw queue
   - `epoch_pair` -> detect queue
4. Detect consumer runs realtime pipeline and `UbloxChart`, then emits `update_image`.
5. Raw consumer batches frames and emits `raw_data_batch`.

## Key Files

- `app.py`: process + queue bootstrap, background workers
- `thread/ReadSerialThread.py`: u-blox ingest and event production
- `thread/RTKLIBStage.py`: RTKLIB-stage payload normalization
- `thread/SocketThread.py`: router + detect/raw consumers
- `draws/UbloxChart.py`: detection plotting and chart rendering
- `templates/index.html`: dashboard client

## Environment Variables

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
RAM_INGRESS_QUEUE_SIZE=5000
RAM_DETECT_QUEUE_SIZE=2000
RAM_RAW_QUEUE_SIZE=5000
RAM_QUEUE_POLL_INTERVAL=0.02
RAM_RAW_EMIT_BATCH_SIZE=100
```

## Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pyubx2
python3 app.py
```

## Tests

```bash
python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v
```

## Notes

- Frontend Socket.IO endpoint in `templates/index.html` is hard-coded (`192.168.5.2:5000`).
- Runtime is best-effort real-time in RAM; no crash-replay persistence in current mode.
- `docs/context.md` and `docs/codebase-map.md` are project memory and should be read first.
