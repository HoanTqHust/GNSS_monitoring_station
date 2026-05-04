from __future__ import annotations

import logging
import time
from typing import Any

import psutil

from config import config
from draws.UbloxChart import UbloxChart
from realtime.pipeline import RealtimeSpoofingPipeline
from realtime.types import RealtimeEpochPair
from thread.DurableRawQueue import DurableRawQueue

LOGGER = logging.getLogger("thread.socket_thread")


class SocketThread:
    @staticmethod
    def append_with_limit(queue: list[Any], item: Any, maxlen: int = config.BUFFER_SAMPLES) -> None:
        queue.append(item)
        if len(queue) > maxlen:
            del queue[0]

    @staticmethod
    def build_realtime_output_map(detector_results) -> dict[str, dict[str, Any]]:
        realtime_outputs: dict[str, dict[str, Any]] = {}
        for result in detector_results:
            output_name = result.metadata.get(
                "output_name", f"{result.detector_name}_{result.measurement_name}"
            )
            realtime_outputs[output_name] = {
                "tow_s": result.tow_s,
                "score": result.score,
                "threshold": result.threshold,
                "spoofing": result.spoofing,
                "reference_svid": result.reference_svid,
                "visible_svids": list(result.visible_svids),
                "suspect_svids": list(result.suspect_svids),
                "measurement_name": result.measurement_name,
                "detector_name": result.detector_name,
            }
        return realtime_outputs

    @staticmethod
    def _emit_raw_batch(socketio, frames: list[dict[str, Any]], queue_stats: dict[str, int]) -> None:
        socketio.emit(
            "raw_data_batch",
            {
                "frames": frames,
                "count": len(frames),
                "last_seq": frames[-1]["seq"],
                "queue_stats": queue_stats,
            },
        )

    @staticmethod
    def _process_epoch_record(
        payload: dict[str, Any],
        combined_samples: list[Any],
        realtime_pipeline: RealtimeSpoofingPipeline,
    ) -> tuple[dict[str, Any], Any, Any, Any, Any]:
        rawx_1 = payload["rawx_1"]
        rawx_2 = payload["rawx_2"]
        nav_1 = payload["nav_1"]
        nav_2 = payload["nav_2"]
        skyplot_data_1 = payload["skyplot_data_1"]
        skyplot_data_2 = payload["skyplot_data_2"]
        spectrum_data_1 = payload["spectrum_data_1"]
        spectrum_data_2 = payload["spectrum_data_2"]
        tow_s = float(payload["tow_s"])

        epoch_pair = RealtimeEpochPair(
            tow_s=tow_s,
            rawx_1=rawx_1,
            nav_1=nav_1,
            rawx_2=rawx_2,
            nav_2=nav_2,
        )
        detector_results = realtime_pipeline.process_epoch(epoch_pair)
        realtime_outputs = SocketThread.build_realtime_output_map(detector_results)
        SocketThread.append_with_limit(combined_samples, (rawx_1, nav_1, rawx_2, nav_2))
        return (
            realtime_outputs,
            skyplot_data_1,
            skyplot_data_2,
            spectrum_data_1,
            spectrum_data_2,
        )

    @staticmethod
    def background_thread(raw_queue_db_path: str, socketio) -> None:
        durable_queue = DurableRawQueue(raw_queue_db_path)
        durable_queue.register_consumer(config.RAW_QUEUE_CONSUMER_ID)
        realtime_pipeline = RealtimeSpoofingPipeline()
        combined_samples: list[Any] = []
        last_plot_time = time.time()
        LOGGER.info(
            "socket_consumer_started consumer_id=%s queue_db_path=%s",
            config.RAW_QUEUE_CONSUMER_ID,
            raw_queue_db_path,
        )

        while True:
            try:
                records = durable_queue.get_pending_batch(
                    config.RAW_QUEUE_CONSUMER_ID,
                    config.RAW_QUEUE_BATCH_SIZE,
                )
                if not records:
                    time.sleep(config.RAW_QUEUE_POLL_INTERVAL)
                    continue

                raw_frames_to_emit: list[dict[str, Any]] = []
                last_processed_seq = 0

                for record in records:
                    if record.topic == "ubx_frame":
                        raw_frames_to_emit.append(
                            {
                                "seq": record.seq,
                                "created_at_utc": record.created_at_utc,
                                **record.payload,
                            }
                        )
                        if len(raw_frames_to_emit) >= config.RAW_EMIT_BATCH_SIZE:
                            stats = durable_queue.get_stats(config.RAW_QUEUE_CONSUMER_ID)
                            SocketThread._emit_raw_batch(socketio, raw_frames_to_emit, stats)
                            raw_frames_to_emit = []
                    elif record.topic == "epoch_pair":
                        (
                            realtime_outputs,
                            skyplot_data_1,
                            skyplot_data_2,
                            spectrum_data_1,
                            spectrum_data_2,
                        ) = SocketThread._process_epoch_record(
                            record.payload,
                            combined_samples,
                            realtime_pipeline,
                        )

                        current_time = time.time()
                        if current_time - last_plot_time >= config.PLOT_INTERVAL:
                            last_plot_time = current_time
                            dps_plot, spoofing_detected = UbloxChart.raw2ImageDps(
                                combined_samples,
                                skyplot_data_1,
                            )
                            if dps_plot != "":
                                skyplot_1 = UbloxChart.raw2ImageSkyplot(skyplot_data_1)
                                skyplot_2 = UbloxChart.raw2ImageSkyplot(skyplot_data_2)
                                spectrum_1 = UbloxChart.raw2ImageSpectrum(spectrum_data_1)
                                spectrum_2 = UbloxChart.raw2ImageSpectrum(spectrum_data_2)
                                cpu_load = psutil.cpu_percent(interval=None)
                                socketio.emit(
                                    "update_image",
                                    {
                                        "skyplot1": "data:image/png;base64," + skyplot_1,
                                        "spectrum1": "data:image/png;base64," + spectrum_1,
                                        "skyplot2": "data:image/png;base64," + skyplot_2,
                                        "spectrum2": "data:image/png;base64," + spectrum_2,
                                        "cpu_load": cpu_load,
                                        "dps": "data:image/png;base64," + dps_plot,
                                        "spoofing": spoofing_detected,
                                        "realtime_outputs": realtime_outputs,
                                    },
                                )
                    else:
                        LOGGER.warning("unknown_queue_topic seq=%s topic=%s", record.seq, record.topic)

                    last_processed_seq = record.seq

                if raw_frames_to_emit:
                    stats = durable_queue.get_stats(config.RAW_QUEUE_CONSUMER_ID)
                    SocketThread._emit_raw_batch(socketio, raw_frames_to_emit, stats)

                if last_processed_seq > 0:
                    durable_queue.ack(config.RAW_QUEUE_CONSUMER_ID, last_processed_seq)
                    LOGGER.debug(
                        "queue_ack_success consumer_id=%s ack_seq=%s",
                        config.RAW_QUEUE_CONSUMER_ID,
                        last_processed_seq,
                    )
            except Exception:
                LOGGER.exception("socket_consumer_error")
                time.sleep(config.RAW_QUEUE_POLL_INTERVAL)
