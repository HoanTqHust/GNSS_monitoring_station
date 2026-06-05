# Double Difference CP — GNSS Spoofing & Jamming Detection Platform

## 1. Product Overview

**Double Difference CP** is a real-time GNSS integrity monitoring platform that fuses two
information sources to detect spoofing and jamming attacks on GPS L1:

- **Two u-blox GNSS receivers** mounted on a single device, processed through carrier-phase
  double-difference (DD) algorithms to detect *spoofing* (synthetic signals that mimic
  authentic satellites).
- **One bladeRF software-defined radio (SDR)** front-end, processed through a deep-learning
  classifier to detect *jamming* (RF interference patterns: narrowband, swept, pulsed, etc.).

The platform runs on an embedded Linux host (Firefly RK3588 class), publishes telemetry over
**MQTT** to a central server, and exposes a local web dashboard built on Flask + Socket.IO.

### 1.1. Target Use Cases

- Fixed-installation GNSS integrity monitor (perimeter, runway, port).
- Fleet/pre-deployment integrity check for mission-critical GNSS receivers.
- R&D testbed for evaluating spoofing/jamming detector algorithms with real hardware.

### 1.2. Hardware & Software Stack

| Layer | Component | Notes |
|---|---|---|
| GNSS front-end #1 | u-blox ZED-F9P / equivalent (UBX over USB-CDC) | `/dev/ttyACM0` |
| GNSS front-end #2 | u-blox ZED-F9P / equivalent (UBX over USB-CDC) | `/dev/ttyACM1` |
| RF front-end | Nuand bladeRF (libbladeRF, FPGA loaded) | `libusb:device=6:3` |
| AI runtime | PyTorch (CPU) + RKNN (NPU port available) | `gnss_jamming_classifier_mps.pth` / `.rknn` |
| Compute host | Linux (Firefly RK3588) | `python3.10`, `pyubx2`, `paho-mqtt`, `numpy`, `torch`, `flask-socketio` |
| Telemetry | MQTT v3.1.1, QoS 1 | Broker: `gnss.soict.io:1883` (default) |
| UI | Flask + Socket.IO + Chart.js | `http://<host>:5000` |

---

## 2. Runtime Architecture

```text
                         ┌──────────────────────────────────────┐
                         │              app.py                  │
                         │  Flask + Socket.IO bootstrap         │
                         └──────────────────────────────────────┘
                                          │
                ┌─────────────────────────┼─────────────────────────────┐
                ▼                         ▼                             ▼
┌─────────────────────────┐  ┌──────────────────────────┐   ┌─────────────────────────┐
│  ReadSerial (Process)   │  │   SocketThread (Threads) │   │   SDRThread (Process)   │
│  – pyubx2 UBX decode    │  │   – router fan-out       │   │   – BladeRF Receiver    │
│  – RTKLIB normalize     │  │   – detect consumer      │   │   – Spectrogram BMP     │
│  – epoch_pair build     │  │   – raw consumer         │   │   – ResNet18 classify   │
└────────────┬────────────┘  └────────────┬─────────────┘   └────────────┬────────────┘
             │                            │                              │
   multiprocessing.Queue        ThreadQueue (detect / raw)    mp.Queue → result_queue
             │                            │                              │
             ▼                            ▼                              ▼
       RAM ingress                 Realtime pipeline                 Socket.IO
       (epoch_pair / ubx_frame)    (DD-carrier, DD-smoothPR)         `sdr_classify`
                                          │
                                          ▼
                         ┌──────────────────────────────────────┐
                         │              MQTT Broker             │
                         │   raw/ublox  detect/epoch  health    │
                         │   state/position  cmd/init  cmd/ack  │
                         └──────────────────────────────────────┘
```

### 2.1. Processes & Threads

1. **`ReadSerial` process** ([thread/ReadSerialThread.py](thread/ReadSerialThread.py))
   reads UBX from the two u-blox ports, decodes `RXM-RAWX`, `NAV-PVT`, `NAV-SAT`,
   `MON-SPAN`, normalizes them via [thread/RTKLIBStage.py](thread/RTKLIBStage.py),
   pairs `RAWX` epochs by receiver-time-of-week (`rcvTow`), and pushes two event types
   into the **RAM ingress queue**:
   - `ubx_frame` — every parsed UBX frame with raw base64 payload (for replay/MQTT).
   - `epoch_pair` — synchronized `(rawx_1, nav_1, rawx_2, nav_2)` tuple ready for
     detectors.

2. **Router thread** ([thread/SocketThread.py](thread/SocketThread.py)) drains the
   ingress queue and fans the events out:
   - `epoch_pair` → **detect queue**
   - `ubx_frame`  → **raw queue**
   On overflow, detect/raw queues drop **oldest** (priority = freshness for the dashboard);
   the ingress queue drops **newest** with a warning so producer back-pressure is visible.

3. **Detect consumer thread** runs the realtime spoofing pipeline
   ([realtime/pipeline.py](realtime/pipeline.py)) on each `epoch_pair`, draws the
   carrier-phase DD chart with [draws/UbloxChart.py](draws/UbloxChart.py), and emits
   `update_image` + `realtime_outputs` to the dashboard. It also publishes
   `detect/epoch/v1` and `state/position/v1` MQTT messages.

4. **Raw consumer thread** batches `ubx_frame` events and emits `raw_data_batch` to the
   dashboard. A **separate worker thread** (`raw_mqtt_publish_worker`) drains a dedicated
   MQTT publish queue so the QoS-1 publish path cannot stall the UI emit path.

5. **SDR process pair** ([thread/SDRThread.py](thread/SDRThread.py)) runs two
   multiprocessing workers:
   - `reader_process` — captures IQ samples from bladeRF, accumulates `NUM_BUFFERS`
     chunks, throttles to ~10 Hz, and pushes `complex64` frames into a queue.
   - `plotter_process` — computes a Hann-windowed STFT, renders a 640×480 BMP
     spectrogram, runs the ResNet18 classifier, and publishes results on
     `result_queue`. The main thread re-emits results via Socket.IO `sdr_classify`.

### 2.2. Queue Sizing & Back-Pressure

| Queue | Default size | Overflow policy | Source |
|---|---|---|---|
| `RAM_INGRESS_QUEUE_SIZE` | 500 000 | drop-new + warn | `config.py` |
| `RAM_DETECT_QUEUE_SIZE`  | 200 000 | drop-oldest | `config.py` |
| `RAM_RAW_QUEUE_SIZE`     | 500 000 | drop-oldest | `config.py` |
| `RAM_RAW_MQTT_QUEUE_SIZE` | 200 000 | drop-oldest, counted as `mqtt_raw_queue_dropped` | `config.py` |
| `QUEUE_MAXSIZE` (SDR)    | 32 | put-nowait, drop-new | `thread/SDRThread.py` |

Backlog and drop counters are reported in every `health/v1` MQTT message.

---

## 3. Spoofing-Detection Algorithms (u-blox × 2)

The platform implements **two independent measurement families** built from synchronized
GPS L1 epoch pairs. Each measurement family is fed into **two detector engines**, giving
**four detector outputs** in parallel.

### 3.1. Notation

For a satellite `i` observed simultaneously by receivers `A` and `B` at epoch `t`:

- `φᵢᴬ(t)`, `φᵢᴮ(t)` — carrier-phase observation (cycles).
- `Pᵢᴬ(t)`, `Pᵢᴮ(t)` — pseudorange (metres).
- A **single difference** between the two receivers cancels satellite clock & ionosphere:
  `SDᵢ(t) = φᵢᴮ(t) − φᵢᴬ(t)`.
- A **double difference** against a reference satellite `r` cancels common-mode receiver
  clocks: `DDᵢʳ(t) = SDᵢ(t) − SDʳ(t)`.

Reference satellite is chosen as the lowest-numbered SVID common to both receivers
(`realtime/measurement_builders/common.py:choose_reference_svid`).

### 3.2. Measurement Builder #1 — Carrier-Phase DD

[realtime/measurement_builders/carrier.py](realtime/measurement_builders/carrier.py)

For every common GPS L1 SV (`gnssId == 0`, `sigId == 0`):

```
DDᵢʳ_carrier = frac( (φᵢᴮ − φᵢᴬ) − (φʳᴮ − φʳᴬ) )
```

The fractional-cycle wrap (`x − round(x)`) maps the integer carrier ambiguity away,
leaving only the centimetre-level residual. **Authentic** signals from independent SVs
produce DD residuals scattered in [−0.5, 0.5] cycles. **Spoofed** signals broadcast from
one transmitter produce highly correlated DDs because all SVs share the same fake
geometry.

### 3.3. Measurement Builder #2 — Carrier-Smoothed Pseudorange DD

[realtime/measurement_builders/smoothed_pseudorange.py](realtime/measurement_builders/smoothed_pseudorange.py)

The classic **Hatch filter** smooths noisy pseudorange with low-noise carrier-phase
deltas, per receiver and per SV:

```
P̂(k) = (P(k) / N) + ((N−1)/N) · ( P̂(k−1) + (φ(k) − φ(k−1)) · λ_L1 )
N = min(sample_count, hatch_window=30)
```

Lock-time regression in `RXM-RAWX` triggers a state reset (rebuild the filter from the
raw pseudorange). The DD is then computed in **metres**:

```
DDᵢʳ_smoothPR = (P̂ᵢᴮ − P̂ᵢᴬ) − (P̂ʳᴮ − P̂ʳᴬ)
```

This signal has a much larger dynamic range than the carrier residual (metres vs.
fractions of a cycle), so it is sensitive to coarse spoofing where the attacker fails to
align pseudoranges precisely.

### 3.4. Detector Engine #1 — Sum-of-Squares (SoS)

[realtime/detector_engines/sos.py](realtime/detector_engines/sos.py)

```
score(t) = (1/N) · Σᵢ DDᵢʳ(t)²        # mean square of DD residuals
spoofing(t) = score(t) < threshold     # "too coherent" → suspect
```

**Rationale.** Authentic multi-satellite geometry preserves non-zero DD dispersion
because each SV has independent multipath / clock jitter. A spoofer that broadcasts all
PRNs from one antenna produces near-identical DDs, collapsing the sum-of-squares toward
zero. Therefore **a low SoS is the alarm condition** (note: this is the inverse of the
naive intuition).

Default thresholds (`config.py`):

| Output | Default threshold |
|---|---|
| `sos_carrier` | `0.04` |
| `sos_smoothed_pseudorange` | `1.10` |

### 3.5. Detector Engine #2 — Distance-Distribution (D3)

[realtime/detector_engines/d3.py](realtime/detector_engines/d3.py)

For every pair of SVs `(a, b)` in the current epoch:

```
if |DDₐ − DD_b| ≤ similarity_threshold → mark a, b as suspect
score(t) = |suspect_svids|
spoofing(t) = score(t) ≥ min_cluster_size
```

**Rationale.** D3 looks for **clusters** of SVs whose DD residuals collapse onto the
same value. Under authentic conditions this almost never happens; under spoofing the
fake constellation produces several mutually-similar DDs that exceed `min_cluster_size`
(default 3).

Default thresholds (`config.py`):

| Output | Default threshold |
|---|---|
| `d3_carrier` | `0.001` cycles |
| `d3_smoothed_pseudorange` | `0.001` m |
| `min_cluster_size` | `3` |

### 3.6. Per-Window Linear-Regression Cluster (Dashboard Plot)

[draws/UbloxChart.py](draws/UbloxChart.py) maintains a **sliding window** of
`BUFFER_SAMPLES = 150` epoch pairs and runs an additional, more visual detector for the
real-time chart:

1. For each common GPS L1 SV in the window, compute pseudorange differences
   `Δρᵢ(t) = ρᵢᴬ(t) − ρᵢᴮ(t)` (with carrier-Doppler clock adjustment via `NAV-PVT`).
2. Subtract the reference SV column and the integer wrap (`round`).
3. Fit a **linear regression** `Δρᵢ(t) = aᵢ · t + bᵢ` using `sklearn.LinearRegression`
   per SV.
4. Cluster slopes `aᵢ` with a 1D ε-clustering (`δa = 1e-4`).
5. **Spoofing alarm** when any cluster contains `≥ 4` SVs (clustered slopes mean SVs
   share a common motion induced by the spoofer's clock drift).

This serves as an independent, human-readable cross-check to the SoS/D3 outputs. The
chart and the Boolean alarm are emitted as the dashboard image.

### 3.7. Detector Output Contract

Every detector emits a `DetectorResult`
([realtime/types.py](realtime/types.py)) with:

```
detector_name      : "sos" | "d3"
measurement_name   : "carrier" | "smoothed_pseudorange"
tow_s              : GPS time-of-week (s)
score              : float | None
threshold          : float | None
spoofing           : True | False | None  # None = pending (not enough data)
visible_svids      : tuple[int, ...]
suspect_svids      : tuple[int, ...]      # D3 only
reference_svid     : int
metadata           : { output_name, received_at_utc, ... }
```

The frontend renders a card per output and maps `spoofing` to
`Detected / Normal / Pending`.

### 3.8. Online Threshold Calibration

[realtime/calibrate_thresholds.py](realtime/calibrate_thresholds.py) runs an offline pass
over a known-clean recording and emits a four-tuple of thresholds for the four
detector outputs above. Thresholds can also be hot-reloaded at runtime via
`gnss/.../cmd/ublox/configure/v1` (see Section 5.5).

---

## 4. AI Model Embedded for BladeRF (Jamming Classifier)

The bladeRF SDR feeds an embedded image classifier that labels the live spectrogram into
six interference categories.

### 4.1. Capture Pipeline

[thread/SDRThread.py](thread/SDRThread.py) (constants section)

| Parameter | Value |
|---|---|
| Center frequency | `1575.42 MHz` (GPS L1) |
| Sample rate | `60 MHz` |
| RX gain | `20 dB` |
| Bandwidth | `30 MHz` (sample_rate/2) |
| Buffer size | `8192` complex samples |
| Buffers per frame | `8` (concatenated → 65 536 samples) |
| Throttle | `0.1 s` (≈10 Hz) |

### 4.2. Spectrogram Front-End

`compute_spectrogram(x)` produces a windowed FFT magnitude image:

| Parameter | Value |
|---|---|
| STFT window | Hann, length `512` |
| FFT size | `512` |
| Hop | `128` (`WINDOW_LEN − NOVERLAP`) |
| Frequency band | `−15 … +15 MHz` around center (GPS L1 ±15 MHz) |
| Dynamic range | `55 dB` (top 99.5-th percentile reference) |

`render_bmp(power_db)` maps the dB matrix into a custom 9-stop perceptual colormap
(`black → indigo → blue → cyan → mint → lime → yellow → white`), resizes to **640 × 480**
RGB BMP, and writes one file per frame to `BKDATASET/`.

### 4.3. Model — ResNet18 (6-class)

```
ResNet18(num_classes=6)
   conv1: 7×7, stride=2, 64ch
   maxpool: 3×3, stride=2
   layer1..4: BasicBlock pairs, channels {64, 128, 256, 512}
   avgpool → fc(512 → 6)
```

| Class index | Label |
|---|---|
| 0 | `Clean`        |
| 1 | `Narrowband`   |
| 2 | `Pulsed`       |
| 3 | `Swept`        |
| 4 | `Multi-tone`   |
| 5 | `Partial-band` |

### 4.4. Inference

```
preprocess_image(img):
    resize(224, 224, BILINEAR)
    arr = float32 / 255.0           # raw 0-1 BMP pixels (no ImageNet norm)
    arr = arr.transpose(2, 0, 1)
    return torch.from_numpy(arr).unsqueeze(0)

predict_image(model, img):
    logits = model(tensor)
    probs  = softmax(logits, dim=1)[0]
    conf, idx = probs.max(0)
    return CLASS_NAMES[idx], conf, probs
```

The classifier is loaded **inside `plotter_process`** (not in the main process) so that
PyTorch fork-safety and CUDA/MPS state stay isolated from Flask. Inference runs on CPU by
default; the same weights export to RKNN for the Firefly RK3588 NPU.

### 4.5. Model Artifacts

| File | Purpose | Runtime |
|---|---|---|
| [SDR/model/gnss_jamming_classifier_mps.pth](SDR/model/gnss_jamming_classifier_mps.pth) | Trained PyTorch weights (state_dict) | CPU / MPS |
| [SDR/model/gnss_jamming_classifier_mps.rknn](SDR/model/gnss_jamming_classifier_mps.rknn) | RKNN-toolkit2 export | RK3588 NPU |

### 4.6. Output Channel

The plotter emits a result record on the inter-process result queue:

```json
{
  "class": "Narrowband",
  "confidence": 0.97,
  "probs": [0.01, 0.97, 0.00, 0.00, 0.01, 0.01],
  "frame_idx": 12345,
  "filename": "./BKDATASET/20260601_023545_678901_012345.bmp"
}
```

The main thread re-emits this record over Socket.IO as `sdr_classify`, which the SDR
dashboard ([templates/sdr.html](templates/sdr.html)) renders as a class-confidence bar
plus the matching BMP frame.

---

## 5. MQTT Telemetry Architecture

The platform publishes **structured, schema-versioned** telemetry to an MQTT broker so
that downstream consumers (server-side dashboards, alerting, archival) never have to
parse raw UBX or PyTorch outputs.

### 5.1. Connection

| Setting | Default | Source |
|---|---|---|
| `MQTT_HOST`        | `gnss.soict.io` | `config.py` |
| `MQTT_PORT`        | `1883` (TCP) | `config.py` |
| `MQTT_USERNAME`    | `rw_user` | `.env` |
| `MQTT_PASSWORD`    | (required, `.env` only — never committed) | `.env` |
| `MQTT_QOS`         | `1` (at-least-once) | enforced in publisher |
| `MQTT_KEEPALIVE_S` | `60` | `config.py` |
| `MQTT_CLIENT_ID_PREFIX` | `double-difference-cp` | per-component suffix appended |

The publisher [telemetry/mqtt_publisher.py](telemetry/mqtt_publisher.py) is single-locked,
auto-reconnects on socket loss, and rejects QoS values other than 1.

### 5.2. Topic Hierarchy

All topics follow the same shape:

```
{prefix}/{site_id}/{device_id}/{suffix}
```

with `prefix = MQTT_TOPIC_PREFIX` (default `gnss`).

| Direction | Suffix | Schema | QoS | Retain | Publisher |
|---|---|---|---|---|---|
| ↑ Up | `raw/ublox/v1`        | `gnss.raw.ublox.v1`     | 1 | false | raw consumer worker |
| ↑ Up | `detect/epoch/v1`     | `gnss.detect.epoch.v1`  | 1 | false | detect consumer |
| ↑ Up | `state/position/v1`   | `gnss.state.position.v1`| 1 | configurable | detect consumer |
| ↑ Up | `health/v1`           | `gnss.health.v1`        | 1 | false | raw consumer (throttled) |
| ↑ Up | `cmd/init/v1`         | `gnss.cmd.init.v1`      | 1 | true  | startup |
| ↑ Up | `cmd/ack/v1`          | `gnss.cmd.ack.v1`       | 1 | false | command handler |
| ↓ Down | `cmd/ublox/configure/v1` | `gnss.cmd.ublox.configure.v1` | 1 | false | server |
| ↓ Down | `cmd/ublox/restart/v1`   | `gnss.cmd.ublox.restart.v1`   | 1 | false | server |
| ↓ Down | `cmd/{set_rate, reboot, start, stop, status}/v1` | legacy aliases | 1 | false | server |

Subscribers should **deduplicate by `event_id`** and track `seq` gaps, since QoS 1 is
at-least-once and does not protect data lost before publish.

### 5.3. Common Envelope

[telemetry/mqtt_schema.py:build_envelope](telemetry/mqtt_schema.py)

Every message — up or down — uses the same outer envelope:

```json
{
  "schema":      "gnss.<family>.v1",
  "event_id":    "{device_id}-{seq:012d}[-{suffix}]",
  "seq":         123456,
  "device_id":   "test_device",
  "site_id":     "default_site",
  "frontend":    "ublox" | "sdr" | "mixed",
  "source":      "rx1" | "rx2" | "rx_pair" | "pipeline" | "server",
  "event_time":  "2026-06-02T09:35:12.345Z",
  "ingest_time": "2026-06-02T09:35:12.401Z",
  "data":        { ... payload ... }
}
```

`schema` and `event_id` are the contract the server consumes;
`event_time` is when the receiver observed the event (GPS-derived if available);
`ingest_time` is when the publisher built the message.

### 5.4. Payload Schemas

#### 5.4.1. `raw/ublox/v1` — every parsed UBX frame
```json
"data": {
  "receiver":      "rx1" | "rx2",
  "identity":      "RXM-RAWX" | "NAV-PVT" | "NAV-SAT" | "MON-SPAN",
  "tow_s":         412345.678,
  "raw_len":       312,
  "raw_encoding":  "base64",
  "raw_base64":    "<base64-encoded UBX bytes>"
}
```
Heavy payload — subscribers that only need detection should **not** subscribe to this.

#### 5.4.2. `detect/epoch/v1` — one synchronized epoch result
```json
"data": {
  "time":     { "tow_s": 412345.0, "gps_week": 2310 },
  "position": {
    "lat_deg": 21.0049, "lon_deg": 105.8431, "height_m": 22.4,
    "fix_type": "3d", "pdop": 1.2
  },
  "summary": {
    "sat_count": 18,
    "avg_cno_dbhz": 41.3,
    "spoofing": true | false | null,
    "status": "spoofed" | "normal" | "pending"
  },
  "signals": [
    { "gnss": "GPS", "svid": 5, "signal": "L1C", "prn": "G05",
      "cno_dbhz": 44.0, "used_in_fix": null, "receiver_ids": ["rx1","rx2"] },
    ...
  ],
  "detectors": {
    "sos_carrier":              { "score": 0.012, "threshold": 0.04, "spoofing": true,  "status": "spoofed",
                                  "reference_svid": 5, "visible_svids": [...], "suspect_svids": [] },
    "sos_smoothed_pseudorange": { ... },
    "d3_carrier":               { ... "suspect_svids": [12,18,22,30] },
    "d3_smoothed_pseudorange":  { ... }
  }
}
```

#### 5.4.3. `state/position/v1` — derived position-only state
Built from `detect/epoch/v1` (`position` + summary `sat_count`, `avg_cno_dbhz`).
Useful for thin clients that only render a map pin. May be retained
(`MQTT_POSITION_RETAIN`) so reconnecting consumers see the last known position
immediately.

#### 5.4.4. `health/v1` — runtime health
Published once per `RAM_HEALTH_PUBLISH_INTERVAL` (default 1 s):
```json
"data": {
  "status": "running" | "degraded",
  "ingress_backlog": 12, "detect_backlog": 0, "raw_backlog": 8,
  "ingress_dropped": 0, "detect_dropped": 0, "raw_dropped": 0,
  "raw_emitted": 12345,
  "unknown_events": 0,
  "last_seq": 67890,
  "mqtt_raw_published": 12340, "mqtt_raw_failed": 0,
  "mqtt_raw_queue_dropped": 0,
  "mqtt_detect_published": 1234, "mqtt_detect_failed": 0,
  "mqtt_position_published": 1234, "mqtt_position_failed": 0,
  "mqtt_health_published": 60, "mqtt_health_failed": 0,
  "cpu_percent": 27.4
}
```
`status = "degraded"` when any drop counter is non-zero.

#### 5.4.5. `cmd/init/v1` (retained) — device announces readiness on connect
```json
"data": { "status": "online", "ready": true }
```

#### 5.4.6. `cmd/ack/v1` — acknowledgement of every server command
```json
"data": {
  "acknowledged": ["<command_id>"],
  "result":       { "status": "ok" | "error", "errors": [...] }
}
```

### 5.5. Downlink Commands

The subscriber [telemetry/mqtt_subscriber.py](telemetry/mqtt_subscriber.py) listens on
`gnss/{site_id}/{device_id}/cmd/+/+/v1` and supports both the **nested** and
**legacy one-level** topic shapes for backward compatibility.

| Command | Effect |
|---|---|
| `cmd/ublox/configure/v1` | Hot-reload detector thresholds, reference SVID, min sat count via `realtime_pipeline.set_threshold(...)`, etc. |
| `cmd/ublox/restart/v1` | Restart serial workers (best-effort). |
| `cmd/set_rate/v1` | Legacy alias → `configure`. |
| `cmd/reboot/v1` | Legacy alias → `restart`. |
| `cmd/{start,stop,status}/v1` | Pipeline lifecycle / status query. |

Internal topics (`cmd/init`, `cmd/ack`) are **filtered out** by the subscriber to
prevent self-feedback loops. A missing `data.command_id` in legacy server payloads
falls back to the envelope `event_id`, so every command can still be ACKed.

### 5.6. Observability

- `mqtt.log` — dedicated file handler that captures every MQTT-related log line
  (publish ok/error, connect, disconnect, ACK, subscribe).
- `all.log` — full pipeline DEBUG log.
- Runtime metrics (`mqtt_raw_published`, `mqtt_raw_queue_dropped`, etc.) are mirrored
  into every `health/v1` message so the server can plot publish health without polling.

---

## 6. Configuration Reference (`.env`)

```env
# u-blox
PORT1=/dev/ttyACM0
PORT2=/dev/ttyACM1
PORT3=/dev/ttyACM2
BUFFER_SAMPLES=150
PLOT_INTERVAL=1
ELE_MASK=13

# Web server
HOSTSOCKET=0.0.0.0
PORTSOCKET=5000

# RAM queues
RAM_INGRESS_QUEUE_SIZE=500000
RAM_DETECT_QUEUE_SIZE=200000
RAM_RAW_QUEUE_SIZE=500000
RAM_RAW_MQTT_QUEUE_SIZE=200000
RAM_QUEUE_POLL_INTERVAL=0.02
RAM_RAW_EMIT_BATCH_SIZE=100
RAM_HEALTH_PUBLISH_INTERVAL=1.0

# Detectors
SOS_CARRIER_THRESHOLD=0.04
SOS_SMOOTHED_PSEUDORANGE_THRESHOLD=1.10
D3_CARRIER_SIMILARITY_THRESHOLD=0.001
D3_SMOOTHED_PSEUDORANGE_SIMILARITY_THRESHOLD=0.001
D3_MIN_CLUSTER_SIZE=3

# MQTT
MQTT_ENABLED=1
MQTT_HOST=gnss.soict.io
MQTT_PORT=1883
MQTT_USERNAME=rw_user
MQTT_PASSWORD=<set-out-of-band>
MQTT_TOPIC_PREFIX=gnss
MQTT_SITE_ID=default_site
MQTT_DEVICE_ID=test_device
MQTT_QOS=1
MQTT_POSITION_RETAIN=0

# SDR / BladeRF
SDR_ENABLED=1
SDR_DEVICE=libusb:device=6:3
SDR_FREQ=1575420000
SDR_SAMPLE_RATE=5000000
SDR_GAIN=30
SDR_BANDWIDTH=2500000
SDR_NUM_SAMPLES=8192
```

---

## 7. Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pyubx2

# (optional) build libbladeRF
./SDR/build_libbladerf.sh

python3 app.py
```

Dashboard: `http://<host>:5000` (UBX + detectors), `http://<host>:5000/sdr` (SDR jamming).

## 8. Tests

```bash
python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v
python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v
```

## 9. Key Files

| Path | Role |
|---|---|
| [app.py](app.py) | Flask + Socket.IO bootstrap, process/thread wiring |
| [config.py](config.py) | All runtime constants (env-overridable) |
| [thread/ReadSerialThread.py](thread/ReadSerialThread.py) | UBX ingest, epoch pairing |
| [thread/RTKLIBStage.py](thread/RTKLIBStage.py) | RTKLIB-stage payload normalization |
| [thread/SocketThread.py](thread/SocketThread.py) | Router, detect/raw consumers, MQTT publish |
| [thread/SDRThread.py](thread/SDRThread.py) | BladeRF capture + spectrogram + ResNet18 |
| [draws/UbloxChart.py](draws/UbloxChart.py) | DD chart + linear-regression cluster detector |
| [realtime/pipeline.py](realtime/pipeline.py) | Two-layer realtime spoofing pipeline |
| [realtime/measurement_builders/](realtime/measurement_builders/) | Carrier-DD, smoothed-PR-DD builders |
| [realtime/detector_engines/](realtime/detector_engines/) | SoS, D3 detector engines |
| [telemetry/mqtt_schema.py](telemetry/mqtt_schema.py) | Envelope + per-topic payload builders |
| [telemetry/mqtt_publisher.py](telemetry/mqtt_publisher.py) | QoS-1 publisher with reconnect |
| [telemetry/mqtt_subscriber.py](telemetry/mqtt_subscriber.py) | Command subscriber + handlers |
| [SDR/src/](SDR/src/) | BladeRF Receiver/Transmitter wrappers |
| [SDR/model/](SDR/model/) | ResNet18 weights (`.pth`) and RKNN port (`.rknn`) |
| [templates/index.html](templates/index.html) | Main dashboard |
| [templates/sdr.html](templates/sdr.html) | SDR/jamming dashboard |
| [docs/context.md](docs/context.md) | Project memory (architectural decisions, incidents) |
| [docs/codebase-map.md](docs/codebase-map.md) | Codebase map for new contributors |

## 10. Notes & Caveats

- The Socket.IO endpoint in [templates/index.html](templates/index.html) is hard-coded
  to `192.168.5.2:5000`; update when deploying to a different host.
- Runtime is **best-effort real-time in RAM** — there is no SQLite/WAL crash-replay
  queue; if the process dies, in-flight raw frames are lost (MQTT QoS 1 only protects
  data **after** publish).
- D3 with default `similarity_threshold = 0.001` may legitimately report `score = 0`
  when SVs are well-separated — this is the **normal** condition, not a bug.
- The RKNN model is targeted at the Firefly RK3588 NPU; on x86 / non-RK Linux, the
  `.pth` weights are used and inference runs on CPU.
- Sensitive files (`.env`, `cookies.txt`, `login.txt`) are present in the repo root —
  scrub before sharing.
