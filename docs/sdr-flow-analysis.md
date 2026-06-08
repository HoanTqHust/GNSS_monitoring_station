# SDR Flow Analysis

## Scope

This note documents the current bladeRF SDR runtime as implemented in the repository and the gaps between the runtime, integration guide, and dashboard behavior.

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
4. `reader_process` opens bladeRF through `SDR/src/common.py::BladeRFSdr`, configures RX, and reads SC16_Q11 samples through `SDR/src/receiver.py::Receiver.receive()`.
5. `Receiver.parse_samples()` converts interleaved int16 I/Q into `complex64` by dividing by `2048.0`.
6. `reader_process` accumulates 8 chunks of 8192 complex samples into one frame of 65536 samples, throttled at about 0.1 seconds, then pushes the frame to the SDR queue.
7. `reader_process` now sends both normalized `complex64` samples and original bladeRF SC16_Q11 raw bytes to the plotter queue.
8. `plotter_process` drains frames, computes the spectrogram, renders a 640x480 RGB BMP, saves it into `BKDATASET/`, runs the PyTorch ResNet18 classifier if model loading succeeded, and pushes `{class, confidence, probs, frame_idx, filename}` into the result queue.
9. When jamming is detected, `plotter_process` uses its raw-byte ring buffer to save a bounded snapshot under `SDR_SNAPSHOT_DIR` and attaches an MQTT event to the result queue.
10. `SDRThread._mqtt_event_worker()` publishes the SDR detection result plus spectrum PNG base64 on `detect/sdr/v1`, then publishes chunked `.bin` data on `raw/sdr/v1`.
11. `SDRThread._result_consumer()` emits each classifier record to Socket.IO event `sdr_classify`.
12. `templates/sdr.html` updates the jamming class/probability UI from `sdr_classify`, but fetches the spectrogram image by polling `/sdr/latest_bmp` every 500 ms and then loading `/sdr/bmp/<basename>`.

## Current Runtime Parameters

The live `thread/SDRThread.py` constants are:

- Center frequency: `1575.42 MHz`
- Sample rate: `60 MHz`
- RX gain: `20 dB`
- RX bandwidth: `30 MHz`
- Chunk size: `8192` complex samples
- Frame size: `8 * 8192 = 65536` complex samples
- Spectrogram: Hann window `512`, overlap `384`, FFT `512`
- Display band: `-15 MHz` to `+15 MHz`
- Render: dB power, custom colormap, `640x480` BMP
- Model classes: `Clean`, `Narrowband`, `Pulsed`, `Swept`, `Multi-tone`, `Partial-band`

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

`config.py` also defines SDR env settings (`SDR_SAMPLE_RATE=5e6`, `SDR_GAIN=30`, `SDR_BANDWIDTH=2.5e6`, `SDR_NUM_SAMPLES=8192`), but `thread/SDRThread.py` currently hardcodes `60e6`, gain `20`, and `8192 * 8` frame assembly instead of using those config values.

## Reliability And Observability Gaps

- `thread/SDRThread.py` imports `torch` and the bladeRF wrapper at module import time. Because `app.py` imports `SDRThread` unconditionally, missing SDR dependencies can break app startup even when `SDR_ENABLED` is false.
- SDR queue overflow is silently ignored with broad `except Exception: pass` in both frame and result queues.
- Reader/plotter worker status uses `print()` instead of structured logging, so the main `all.log` observability path is incomplete.
- `BKDATASET/` receives one BMP per processed frame and has no retention policy.
- The frontend has a Socket.IO listener for `sdr_data`, but current server code only emits `sdr_classify` and `sdr_stopped`.
- The spectrogram image and classifier result are coupled only through filename timing; the image is not pushed atomically with the classifier result.
- The MQTT snapshot path captures bounded frames produced by the current SDR pipeline; it is not intended to continuous-stream full-rate bladeRF data.

## Recommended Target Architecture

Keep SDR decoupled from the GNSS UBX double-difference pipeline, but make it a first-class data source with explicit contracts:

1. `sdr_ingest`: bladeRF init, RX config from `config.py`, SC16_Q11 -> complex64 conversion, capture metrics.
2. `sdr_features`: deterministic spectrogram/preprocess function that exactly matches the trained model contract.
3. `sdr_detector`: model runtime adapter for PyTorch first, RKNN optional later, with versioned class mapping.
4. `sdr_stream`: Socket.IO payload for UI plus MQTT payloads for `detect/sdr/v1` and chunked `raw/sdr/v1`.
5. `sdr_storage`: optional frame retention with a bounded latest-frame cache or cleanup policy.

Before relying on AI jamming status, first decide which contract is authoritative: the current `thread/SDRThread.py` BMP pipeline or `SDR/README_bladerf_integration.md`.
