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
8. If `config.SDR_ENABLED` is true, `thread/SDRThread.py` starts SDR reader/plotter processes plus result/MQTT worker threads.

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
- Current default SDR source is USRP X300 over Ethernet:
  - `SDR_SOURCE=usrp_x300`
  - `SDR_USRP_ADDR=192.168.5.111`
  - `SDR_USRP_ARGS=addr=192.168.5.111`
- `thread/SDRThread.py` uses UHD Python API lazily for USRP mode, so `app.py` can import without `uhd` installed; runtime startup with `SDR_SOURCE=usrp_x300` still requires UHD with Python bindings on the RK3588 host.
- Legacy bladeRF remains available by setting `SDR_SOURCE=bladerf`.
- Current SDR runtime parameters come from `config.py`:
  - sample rate `SDR_SAMPLE_RATE`
  - center frequency `SDR_FREQ`
  - gain `SDR_GAIN`
  - bandwidth `SDR_BANDWIDTH`
  - chunk size `SDR_NUM_SAMPLES`
  - frame assembly `8 * SDR_NUM_SAMPLES`
  - Hann STFT window `512`, overlap `384`, FFT `512`
  - custom colormap and 640x480 BMP output
- USRP receive uses `uhd.usrp.MultiUSRP(SDR_USRP_ARGS)`, configures RX rate/frequency/gain/optional antenna, creates `StreamArgs("fc32", "sc16")`, and reconstructs interleaved int16 raw bytes from received `complex64` samples so the old snapshot/MQTT path still gets `raw_bytes`.
- For X300 with UBX-40 v2, `uhd_usrp_probe` reported RX bandwidth fixed at `40000000.0 Hz`; runtime therefore does not call UHD `set_rx_bandwidth()` by default. Set `SDR_USRP_SET_BANDWIDTH=1` only when using a daughterboard/configuration that accepts the requested bandwidth.
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
- MQTT is enabled by default in `config.py`; device identity now defaults to `device_<mac_suffix>` and `MQTT_USERNAME` must equal `MQTT_DEVICE_ID` for the EMQX per-device ACL. `MQTT_PASSWORD` has no code fallback and must be provisioned through environment/local config. Do not expose or copy secrets from `.env`.
- MQTT identity defaults:
  - `MQTT_DEVICE_MAC_INTERFACE=""` (auto-select first usable non-loopback interface)
  - `MQTT_DEVICE_MAC_SUFFIX_LENGTH=4`
  - `MQTT_DEVICE_ID=device_<last 4 MAC hex chars>` unless explicitly set
  - `MQTT_USERNAME=MQTT_DEVICE_ID` unless explicitly set to the same value
  - `MQTT_PASSWORD=""`; MQTT publisher/subscriber settings reject empty password when MQTT is enabled
- EMQX device account provisioning is automated by `scripts/provision_emqx_device.py`:
  - uses EMQX REST API credentials from `EMQX_API_BASE_URL`, `EMQX_API_KEY`, and `EMQX_API_SECRET`;
  - targets the built-in database authenticator by default: `password_based:built_in_database`;
  - creates or, with `--update-existing`, rotates the MQTT user whose username equals `device_id`;
  - writes only device-scoped runtime credentials to `.env` when invoked with `--write-env`;
  - must not leave EMQX admin/API credentials on deployed RK3588 devices after provisioning.
- `scripts/provision_current_device.sh` is the operator-friendly wrapper for provisioning the current RK3588. It prompts for EMQX API key/secret when not exported, calls `scripts/provision_emqx_device.py`, updates `.env`, and does not store admin API credentials in source.
- `scripts/provision_emqx_device.py` inserts the repository root into `sys.path` at startup so it can be executed directly as `python3 scripts/provision_emqx_device.py` without `PYTHONPATH`.
- SDR defaults:
  - `SDR_SOURCE=usrp_x300`
  - `SDR_USRP_ADDR=192.168.5.111`
  - `SDR_USRP_ARGS=addr=192.168.5.111`
  - `SDR_SAMPLE_RATE=5e6`
  - `SDR_FREQ=1575.42e6`
  - `SDR_GAIN=30`
  - `SDR_BANDWIDTH=2.5e6`
  - `SDR_USRP_SET_BANDWIDTH=False`
  - `SDR_NUM_SAMPLES=8192`
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
  - `tests/test_mqtt_device_identity.py`
  - `tests/test_emqx_provisioning.py`
  - `tests/test_usrp_sdr_source.py`
- RK3588 / USRP X300 hardware evidence from operator logs:
  - `python3 -c "import uhd; print('UHD Python OK')"` passed on the RK3588 host.
  - `uhd_find_devices --args "addr=192.168.5.111"` found USRP X300 serial `32244B4`, FPGA flavor `HG`, UHD host `3.15.0.0-2build5`.
  - Initial `uhd_usrp_probe --args "addr=192.168.5.111"` failed with FPGA compatibility mismatch: host expected `36`, device had `39`.
  - After downloading UHD images and running `sudo /usr/bin/uhd_image_loader --args="type=x300,addr=192.168.5.111,configure"`, `uhd_usrp_probe --args "addr=192.168.5.111"` no longer failed on compatibility and initialized X300 blocks.
  - Current remaining probe warning is Linux UDP send buffer size: target `2426666`, actual `1048576`; UHD prints `sudo sysctl -w net.core.wmem_max=2426666` as the immediate minimum.
  - Ettus X3x0 host configuration docs recommend setting both `net.core.rmem_max=33554432` and `net.core.wmem_max=33554432` for high-rate Ethernet streaming.
  - After `sudo sysctl -w net.core.wmem_max=33554432`, `uhd_usrp_probe --args "addr=192.168.5.111"` completed successfully and reported `FPGA Version: 36.0`, X300 serial `32244B4`, two UBX-40 v2 RX daughterboards, antennas `TX/RX`, `RX2`, `CAL`, RX frequency range `10 MHz` to `6000 MHz`, PGA0 gain range `0.0` to `31.5 dB`, and RX bandwidth range fixed at `40000000.0 Hz`.
  - Runtime evidence from `all.log` on `2026-06-15`: `SDR pipeline started`, `sdr_mqtt_worker_started`, and browser polling `/sdr/latest_bmp`, but no new `BKDATASET/*.bmp` or `output_sdr/*` after `2026-06-05`; this indicates reader/plotter produced no frames in that run.
  - Runtime evidence from `all.log` after child-process logging was added: `sdr_reader_process_error` was caused by UHD Python `set_rx_freq()` rejecting a plain float. UHD 3.15 Python binding on RK3588 reports supported signature `(tune_request, chan=0)`, so USRP frequency tuning now uses `uhd.types.TuneRequest(CENTER_FREQ)`.
  - Latest operator grep output after the `TuneRequest` fix shows the USRP path starting successfully on `2026-06-15 06:46`: `sdr_source_started source=usrp_x300 args=addr=192.168.5.111`, followed by `sdr_reader_started source=usrp_x300`.
  - The same run produced new spectrogram BMPs under `BKDATASET/` through at least `2026-06-15 06:47:20`, including `BKDATASET/20260615_064720_694551_000038.bmp`; this proves the reader-to-plotter-to-UI image path is active.
  - Remaining SDR runtime warnings in that run are `usrp_rx_metadata_error error=rx_metadata_error_code.overflow` and repeated `sdr_reader_queue_drop`; these indicate streaming/backpressure loss, not total SDR startup failure.
  - No new `sdr_detect_published` line was present in the latest SDR grep output after `06:46`; SDR MQTT detect/raw publication is still expected only when the classifier emits a non-clean jamming event above threshold and snapshot finalization completes.
- Useful validation commands:
  - `python3 -m unittest discover -s tests -v`
  - `MQTT_DEVICE_ID=device_abcd MQTT_USERNAME=device_abcd MQTT_PASSWORD=secret python3 -m unittest discover -s tests -v`
  - `MQTT_DEVICE_ID=device_abcd MQTT_USERNAME=device_abcd MQTT_PASSWORD=secret python3 -m unittest discover -s tests -p 'test_emqx_provisioning.py' -v`
  - `python3 -m unittest discover -s tests -p 'test_ram_queue_flow.py' -v`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_telemetry.py' -v`
  - `python3 -m unittest discover -s tests -p 'test_mqtt_device_identity.py' -v`
  - `python3 -m unittest discover -s tests -p 'test_usrp_sdr_source.py' -v`
  - `python3 realtime/test_runner.py`
- Hardware/manual commands:
  - `python app.py`
  - `python3 -m realtime.live_runner`
  - `python3 realtime/calibrate_thresholds.py --file1 <rx1.ubx> --file2 <rx2.ubx>`
  - `python log.py`
  - `bash record_ubx.sh`

## Important Findings / Risks

- `telemetry/mqtt_schema.py::build_ublox_command_message()` references `topic_prefix` but does not accept it in the function signature. This is a likely bug if that helper is used.
- MQTT security review on `2026-06-15` found the client implementation is still not security-complete: `config.py` defaults to `MQTT_PORT=1883`, `telemetry/mqtt_publisher.py` and `telemetry/mqtt_subscriber.py` call `username_pw_set()` but do not configure TLS, and command payloads are not signed or timestamp-window validated before mutating realtime detector state. The hardcoded password fallback was removed during per-device identity implementation.
- Broker-side MQTT ACL/TLS settings were not present in the repository during the review; do not claim end-to-end MQTT security until the broker listener, TLS certificates, and per-topic ACLs are verified.
- Per-device MQTT topic isolation cannot be guaranteed by RK3588/client code alone. It requires broker-enforced ACLs binding each authenticated device identity to only its own topic subtree, for example `gnss/<site_id>/<device_id>/...`; client-side topic validation and signed commands are defense-in-depth, not the primary access-control boundary.
- Proposed MQTT identity model: derive default `device_id` at boot as `device_<mac_suffix>` from a stable network interface MAC suffix, then authenticate to EMQX as the same identity and enforce per-device topic access with EMQX ACL placeholders such as `${username}` or `${clientid}`. A 4-hex-character MAC suffix has collision risk; provisioning must detect duplicates or use more MAC characters/full MAC for stronger uniqueness.
- EMQX account/ACL automation should run from a trusted provisioning service or operator script using EMQX REST API credentials, not from the RK3588 app with an admin API key. The device should receive only its own MQTT username/password or client certificate and its own topic-scoped config.
- Do not store an EMQX admin account or REST API key on deployed RK3588 devices. If automatic MQTT account creation is required, implement a provisioning service that authenticates the device with a one-time bootstrap token or factory certificate, calls the EMQX REST API server-side, returns only the per-device MQTT credential, and writes that credential to a root-owned local config file.
- `scripts/provision_emqx_device.py` is the current operator-side automation for this model. It can run on a trusted admin host or during controlled RK3588 setup, but the EMQX API key/secret must be unset/removed afterward; the long-lived application config should contain only `MQTT_DEVICE_ID`, `MQTT_USERNAME`, and `MQTT_PASSWORD`.
- Use `scripts/provision_current_device.sh` for manual device provisioning when an operator has an EMQX API key/secret. Do not hardcode those admin credentials into scripts, `.env`, or committed files.
- Recommended EMQX ACL shape is dynamic per-device authorization: match device MQTT usernames with a regex such as `^device_[0-9A-Fa-f]{4,12}$` and use topic placeholders like `gnss/+/${username}/raw/#`, `gnss/+/${username}/detect/#`, `gnss/+/${username}/state/#`, `gnss/+/${username}/health/#`, `gnss/+/${username}/cmd/init/v1`, `gnss/+/${username}/cmd/ack/v1`, and own command subscriptions. Do not keep a shared full-access MQTT user on deployed devices.
- Device-side implementation now derives `MQTT_DEVICE_ID` from MAC when not explicitly set, validates `MQTT_TOPIC_PREFIX`/`MQTT_SITE_ID`/`MQTT_DEVICE_ID`, requires `MQTT_USERNAME == MQTT_DEVICE_ID`, and includes `MQTT_DEVICE_ID` in MQTT client IDs so multiple devices do not collide on broker sessions.
- `templates/index.html` connects Socket.IO to fixed `http://192.168.5.2:5000` instead of the current host.
- `templates/index.html` labels the raw panel as "Durable Queue", but current runtime is RAM queue based.
- `draws/UbloxChart.py::process_ubx_data()` subtracts `dps[idx,1]` when any satellite exists; this is an index-based reference choice and may be fragile.
- `ReadSerial.read_serial()` catches broad exceptions and continues forever; logs are required before changing behavior.
- `SocketThread` catches broad exceptions in router/detect/raw loops; check `all.log` and `mqtt.log` before patching.
- `.env`, `cookies.txt`, and `login.txt` exist in the repo. Treat as sensitive; do not print contents.
- `requirements.txt` is not a minimal project dependency list; it includes many unrelated environment packages.
- UHD is installed on the RK3588 host per operator log; the local/dev environment used for the source review may still lack UHD (`import uhd` previously failed there).
- Before sustained USRP X300 streaming on RK3588, increase Linux UDP socket buffers; use Ettus X3x0 recommendation `net.core.rmem_max=33554432` and `net.core.wmem_max=33554432` unless constrained by the host OS.
- SDR MQTT is event-driven in current runtime: `detect/sdr/v1` and `raw/sdr/v1` are published only when the classifier detects a non-`Clean`/non-`Unknown` jamming state above `SDR_JAMMING_CONFIDENCE_THRESHOLD` and the snapshot finalizes. UI spectrogram/classifier updates should still appear continuously if reader and plotter are producing frames.
- For UHD Python 3.15 on RK3588, keep USRP RX frequency tuning through `TuneRequest`; direct `set_rx_freq(float, channel)` fails.
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
