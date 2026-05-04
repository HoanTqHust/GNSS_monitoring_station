from __future__ import annotations

import logging
import queue as queue_module
import threading
import time
from typing import Any

import psutil

from config import config
from draws.UbloxChart import UbloxChart
from realtime.pipeline import RealtimeSpoofingPipeline
from realtime.types import RealtimeEpochPair

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
    def create_metrics() -> tuple[dict[str, int], threading.Lock]:
        metrics = {
            "ingress_received": 0,
            "ingress_dropped": 0,
            "detect_enqueued": 0,
            "detect_dropped": 0,
            "detect_processed": 0,
            "raw_enqueued": 0,
            "raw_dropped": 0,
            "raw_emitted": 0,
            "unknown_events": 0,
            "last_seq": 0,
        }
        return metrics, threading.Lock()

    @staticmethod
    def _safe_qsize(the_queue) -> int:
        try:
            return int(the_queue.qsize())
        except Exception:
            return -1

    @staticmethod
    def _put_with_drop_oldest(target_queue, item, drop_key: str, metrics: dict[str, int], lock: threading.Lock) -> None:
        try:
            target_queue.put_nowait(item)
            return
        except queue_module.Full:
            pass

        try:
            target_queue.get_nowait()
        except queue_module.Empty:
            pass

        try:
            target_queue.put_nowait(item)
        except queue_module.Full:
            with lock:
                metrics[drop_key] += 1
            LOGGER.warning("queue_drop_new_event drop_key=%s", drop_key)
            return

        with lock:
            metrics[drop_key] += 1
        LOGGER.warning("queue_drop_oldest drop_key=%s", drop_key)

    @staticmethod
    def router_thread(ingress_queue, detect_queue, raw_queue, metrics: dict[str, int], lock: threading.Lock) -> None:
        LOGGER.info("ram_router_started")
        while True:
            try:
                event = ingress_queue.get(timeout=config.RAM_QUEUE_POLL_INTERVAL)
            except queue_module.Empty:
                continue
            except Exception:
                LOGGER.exception("ram_router_read_error")
                continue

            try:
                event_type = event.get("event_type")
                seq = int(event.get("seq", 0))
                with lock:
                    metrics["ingress_received"] += 1
                    metrics["last_seq"] = max(metrics["last_seq"], seq)

                if event_type == "ubx_frame":
                    SocketThread._put_with_drop_oldest(raw_queue, event, "raw_dropped", metrics, lock)
                    with lock:
                        metrics["raw_enqueued"] += 1
                elif event_type == "epoch_pair":
                    SocketThread._put_with_drop_oldest(detect_queue, event, "detect_dropped", metrics, lock)
                    with lock:
                        metrics["detect_enqueued"] += 1
                else:
                    with lock:
                        metrics["unknown_events"] += 1
                    LOGGER.warning("ram_router_unknown_event event_type=%s seq=%s", event_type, seq)
            except Exception:
                LOGGER.exception("ram_router_route_error")

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
    def detect_consumer_thread(detect_queue, socketio, metrics: dict[str, int], lock: threading.Lock) -> None:
        realtime_pipeline = RealtimeSpoofingPipeline()
        combined_samples: list[Any] = []
        last_plot_time = time.time()
        LOGGER.info("detect_consumer_started")

        while True:
            try:
                event = detect_queue.get(timeout=config.RAM_QUEUE_POLL_INTERVAL)
            except queue_module.Empty:
                continue
            except Exception:
                LOGGER.exception("detect_consumer_read_error")
                continue

            try:
                payload = event["payload"]
                (
                    realtime_outputs,
                    skyplot_data_1,
                    skyplot_data_2,
                    spectrum_data_1,
                    spectrum_data_2,
                ) = SocketThread._process_epoch_record(
                    payload,
                    combined_samples,
                    realtime_pipeline,
                )
                with lock:
                    metrics["detect_processed"] += 1

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
            except Exception:
                LOGGER.exception("detect_consumer_process_error")

    @staticmethod
    def _build_queue_stats(
        ingress_queue,
        detect_queue,
        raw_queue,
        metrics: dict[str, int],
        lock: threading.Lock,
    ) -> dict[str, int]:
        with lock:
            snapshot = dict(metrics)
        ingress_backlog = SocketThread._safe_qsize(ingress_queue)
        detect_backlog = SocketThread._safe_qsize(detect_queue)
        raw_backlog = SocketThread._safe_qsize(raw_queue)

        pending_events = 0
        if ingress_backlog >= 0 and detect_backlog >= 0 and raw_backlog >= 0:
            pending_events = ingress_backlog + detect_backlog + raw_backlog

        return {
            # Keep compatibility with existing frontend fields.
            "total_events": snapshot["ingress_received"],
            "last_seq": snapshot["last_seq"],
            "last_acked_seq": snapshot["detect_processed"],
            "pending_events": pending_events,
            # RAM queue specific stats.
            "ingress_backlog": ingress_backlog,
            "detect_backlog": detect_backlog,
            "raw_backlog": raw_backlog,
            "ingress_dropped": snapshot["ingress_dropped"],
            "detect_dropped": snapshot["detect_dropped"],
            "raw_dropped": snapshot["raw_dropped"],
            "raw_emitted": snapshot["raw_emitted"],
            "unknown_events": snapshot["unknown_events"],
        }

    @staticmethod
    def raw_consumer_thread(
        ingress_queue,
        detect_queue,
        raw_queue,
        socketio,
        metrics: dict[str, int],
        lock: threading.Lock,
    ) -> None:
        LOGGER.info("raw_consumer_started")
        frames_to_emit: list[dict[str, Any]] = []
        last_emit_time = time.time()

        while True:
            try:
                event = raw_queue.get(timeout=config.RAM_QUEUE_POLL_INTERVAL)
                seq = int(event.get("seq", 0))
                frames_to_emit.append(
                    {
                        "seq": seq,
                        "created_at_utc": event.get("created_at_utc"),
                        **event["payload"],
                    }
                )
            except queue_module.Empty:
                pass
            except Exception:
                LOGGER.exception("raw_consumer_read_error")

            now = time.time()
            should_flush = len(frames_to_emit) >= config.RAM_RAW_EMIT_BATCH_SIZE
            if not should_flush and frames_to_emit:
                should_flush = (now - last_emit_time) >= config.RAM_QUEUE_POLL_INTERVAL
            if not should_flush:
                continue

            if not frames_to_emit:
                continue

            try:
                stats = SocketThread._build_queue_stats(
                    ingress_queue,
                    detect_queue,
                    raw_queue,
                    metrics,
                    lock,
                )
                socketio.emit(
                    "raw_data_batch",
                    {
                        "frames": list(frames_to_emit),
                        "count": len(frames_to_emit),
                        "last_seq": frames_to_emit[-1]["seq"],
                        "queue_stats": stats,
                    },
                )
                with lock:
                    metrics["raw_emitted"] += len(frames_to_emit)
                frames_to_emit = []
                last_emit_time = now
            except Exception:
                LOGGER.exception("raw_consumer_emit_error")
