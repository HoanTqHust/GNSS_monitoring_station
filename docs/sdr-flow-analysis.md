# SDR Flow Analysis

## Scope

This note documents the current SDR runtime as implemented in the repository and the gaps between the runtime, integration guide, and dashboard behavior.

## Current Runtime Flow

1. `app.py` imports `thread.SDRThread.SDRThread` during startup and exposes:
   - `/sdr` -> `templates/sdr.html`
   - `/sdr/latest_bmp` -> latest `.bmp` filename from `BKDATASET/`
   - `/sdr/bmp/<filename>` -> serves one BMP file
   - `/sdr/stop` -> stops the SDR pipeline
2. If `config.SDR_ENABLED` is true, `app.py` starts `SDRThread`.
3. `SDRThread.start()` creates:
   - one multiprocessing queue for IQ frames
   - one multiprocessing queue for classification results
   - `reader_process`
   - `plotter_process`
   - one in-process result consumer thread
4. `reader_process` opens the configured SDR source through `sdr_sources.factory.open_sdr_receiver_source()`:
   - default `SDR_SOURCE=usrp_x300`: `sdr_sources.usrp_source.UhdUsrpReceiverSource`
   - legacy `SDR_SOURCE=bladerf`: `sdr_sources.bladerf_source.BladeRfReceiverSource`
5. In USRP mode, the source configures RX rate/frequency/gain/optional antenna, creates `StreamArgs("fc32", "sc16")`, starts continuous streaming, and calls `recv()` regularly so X300 UDP packets are drained by the RK3588 host.
   - UHD `set_rx_bandwidth()` is not called by default because the deployed X300 UBX-40 v2 probe reports fixed RX bandwidth `40000000.0 Hz`; set `SDR_USRP_SET_BANDWIDTH=1` only for hardware that accepts the requested bandwidth.
   - UHD `set_rx_freq()` is called with `uhd.types.TuneRequest(CENTER_FREQ)` because UHD Python 3.15 on RK3588 rejected direct `set_rx_freq(float, channel)`.
6. In bladeRF mode, `SDR/src/receiver.py::Receiver.parse_samples()` converts interleaved int16 I/Q into `complex64` by dividing by `2048.0`.
7. `reader_process` accumulates 8 chunks of `SDR_NUM_SAMPLES` complex samples into one frame, throttled at about 0.1 seconds, then pushes the frame to the SDR queue.
8. `reader_process` sends both normalized `complex64` samples and raw-byte-compatible data to the plotter queue. The shared source contract is `receive_with_raw(num_samples) -> (complex64 samples, SC16_Q11-compatible raw bytes)`.
   - USRP mode reconstructs interleaved int16 bytes from `complex64` samples to keep the snapshot/MQTT contract.
   - bladeRF mode keeps original SC16_Q11 bytes from the bladeRF sync buffer.
9. `plotter_process` drains frames, computes the spectrogram, renders a 640x480 RGB BMP, saves it into `BKDATASET/`, runs the PyTorch ResNet18 classifier if model loading succeeded, and pushes `{class, confidence, probs, frame_idx, filename}` into the result queue.
10. When jamming is detected, `plotter_process` uses its raw-byte ring buffer to save a bounded snapshot under `SDR_SNAPSHOT_DIR` and attaches an MQTT event to the result queue.
11. `SDRThread._mqtt_event_worker()` publishes the SDR detection result plus spectrum PNG base64 on `detect/sdr/v1`, then publishes chunked `.bin` data on `raw/sdr/v1`.
12. `SDRThread._result_consumer()` emits each classifier record to Socket.IO event `sdr_classify`.
13. `templates/sdr.html` updates the jamming class/probability UI from `sdr_classify`, but fetches the spectrogram image by polling `/sdr/latest_bmp` every 500 ms and then loading `/sdr/bmp/<basename>`.

## Current Runtime Parameters

The live `thread/SDRThread.py` runtime values now come from `config.py`:

- Center frequency: `1575.42 MHz`
- Sample rate: default `5 MHz`
- RX gain: default `30 dB`
- RX bandwidth metadata/request: default `2.5 MHz`
- UHD RX bandwidth setter: disabled by default with `SDR_USRP_SET_BANDWIDTH=0`
- Chunk size: default `8192` complex samples
- Frame size: default `8 * 8192 = 65536` complex samples
- Spectrogram: Hann window `512`, overlap `384`, FFT `512`
- Display band: `-15 MHz` to `+15 MHz`
- Render: dB power, custom colormap, `640x480` BMP
- Model classes: `Clean`, `Narrowband`, `Pulsed`, `Swept`, `Multi-tone`, `Partial-band`
- Default USRP X300 address: `192.168.5.111`

## Important Mismatches

The current runtime does not match `SDR/README_bladerf_integration.md`, which describes the model input contract as:

- sample rate `5 MHz`
- frame size `8192`
- use `iq.real`
- STFT `nperseg=256`, `noverlap=128`
- magnitude, not dB
- matplotlib default colormap
- PNG rendered at `figsize=(3,3), dpi=80`
- resize to `224x224`
- ImageNet normalization
- class labels: `DME`, `NB`, `NoJam`, `SingleAM`, `SingleChirp`, `SingleFM`

Because the image generation, sampling rate, normalization, and labels differ, the current `sdr_classify` output should be treated as an unverified runtime signal until the model training contract is reconciled with `thread/SDRThread.py`.

The previous runtime hardcoded `60e6`, gain `20`, and `8192 * 8` frame assembly. It now reads rate/frequency/gain/bandwidth/chunk size from `config.py`, but the image-generation/model-contract mismatch remains.

## Reliability And Observability Gaps

- `thread/SDRThread.py` imports `torch` at module import time. `sdr_sources` imports UHD and bladeRF lazily, but runtime startup still requires the selected source dependency.
- SDR queue overflow is silently ignored with broad `except Exception: pass` in both frame and result queues.
- Reader/plotter worker startup and errors are now logged to `all.log`; older runs may only have child-process failures on stderr.
- `BKDATASET/` receives one BMP per processed frame and has no retention policy.
- The frontend has a Socket.IO listener for `sdr_data`, but current server code only emits `sdr_classify` and `sdr_stopped`.
- The spectrogram image and classifier result are coupled only through filename timing; the image is not pushed atomically with the classifier result.
- The MQTT snapshot path captures bounded frames produced by the current SDR pipeline; it is not intended to continuous-stream full-rate bladeRF data.

## Recommended Target Architecture

Keep SDR decoupled from the GNSS UBX double-difference pipeline, but make it a first-class data source with explicit contracts:

1. `sdr_ingest`: source adapter init, RX config from `config.py`, source-specific IQ read, shared `(complex64, raw_bytes)` output contract, capture metrics.
2. `sdr_features`: deterministic spectrogram/preprocess function that exactly matches the trained model contract.
3. `sdr_detector`: model runtime adapter for PyTorch first, RKNN optional later, with versioned class mapping.
4. `sdr_stream`: Socket.IO payload for UI plus MQTT payloads for `detect/sdr/v1` and chunked `raw/sdr/v1`.
5. `sdr_storage`: optional frame retention with a bounded latest-frame cache or cleanup policy.

Before relying on AI jamming status, first decide which contract is authoritative: the current `thread/SDRThread.py` BMP pipeline or `SDR/README_bladerf_integration.md`.
