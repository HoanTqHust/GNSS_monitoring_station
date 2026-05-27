#!/usr/bin/env python3
"""
SDR Web App: bladeRF -> HTTP API -> Browser (realtime chart).
Usage: python tests/sdr_web.py [freq] [sr] [port]
Access: http://localhost:5555
"""
import sys
import numpy as np
from datetime import datetime
from threading import Thread

sys.path.insert(0, "/home/ubuntu/sdr")
from src import BladeRFSdr, Receiver
from flask import Flask, render_template_string

app = Flask(__name__)

freq = float(sys.argv[1]) if len(sys.argv) > 1 else 2.4e9
sr = float(sys.argv[2]) if len(sys.argv) > 2 else 10e6
web_port = int(sys.argv[3]) if len(sys.argv) > 3 else 5555
chunk = 1024

latest_data = {"amp": [], "iq": [], "connected": False, "peak": 0.0, "mean": 0.0}
running = False

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>SDR Viewer</title>
    <meta charset="utf-8">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #0f1117; color: #e0e0e0; padding: 12px; font-size: 13px; }
        h1 { font-size: 15px; color: #4fc3f7; margin-bottom: 6px; }
        .stats { font-size: 12px; color: #90a4ae; margin-bottom: 8px; }
        .stats span { color: #4fc3f7; margin-right: 12px; }
        #status { position: fixed; top: 10px; right: 12px; font-size: 11px; }
        .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #f44336; margin-right: 5px; vertical-align: middle; }
        .dot.live { background: #4caf50; }
        #error { color: #f44336; font-size: 11px; margin: 4px 0; }
        .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 1100px; margin-top: 4px; }
        .chart-box { background: #1a1f2e; border-radius: 6px; padding: 10px; }
        .chart-box h3 { font-size: 11px; color: #78909c; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
        canvas { display: block; }
        .footer { margin-top: 8px; font-size: 11px; color: #455a64; }
        .footer a { color: #4fc3f7; }
    </style>
</head>
<body>
    <h1>bladeRF SDR Viewer</h1>
    <div class="stats">
        <span>Freq: <b>{{freq}} MHz</b></span>
        <span>SR: <b>{{sr}} Msps</b></span>
        <span>Samples: <b>{{chunk}}</b></span>
    </div>
    <div id="status"><span class="dot" id="dot"></span><span id="statusText">Connecting...</span></div>
    <div id="error"></div>
    <div class="charts">
        <div class="chart-box">
            <h3>Amplitude</h3>
            <canvas id="timeChart"></canvas>
        </div>
        <div class="chart-box">
            <h3>Constellation</h3>
            <canvas id="scatterChart"></canvas>
        </div>
    </div>
    <div class="footer"><a href="/data" target="_blank">/data</a> | bladeRF SDR</div>

    <script>
        var CHUNK = {{chunk}};
        var timeChart, scatterChart;

        function log(msg) {
            console.log("[SDR]", msg);
        }

        function showError(msg) {
            document.getElementById("error").textContent = msg;
            log("ERROR: " + msg);
        }

        function clearError() {
            document.getElementById("error").textContent = "";
        }

        function initCharts() {
            var timeCtx = document.getElementById("timeChart").getContext("2d");
            timeChart = new Chart(timeCtx, {
                type: "line",
                data: {
                    labels: Array.from({length: CHUNK}, function(_, i) { return i; }),
                    datasets: [{
                        label: "|IQ|",
                        data: [],
                        borderColor: "#4fc3f7",
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: true,
                        backgroundColor: "rgba(79,195,247,0.1)"
                    }]
                },
                options: {
                    responsive: true,
                    animation: false,
                    plugins: { legend: { display: false }, tooltip: { enabled: false } },
                    scales: {
                        x: { display: false },
                        y: { min: 0, max: 0.3, grid: { color: "#263238" }, ticks: { color: "#546e7a", font: { size: 10 } } }
                    }
                }
            });

            var scatterCtx = document.getElementById("scatterChart").getContext("2d");
            scatterChart = new Chart(scatterCtx, {
                type: "scatter",
                data: {
                    datasets: [{
                        label: "IQ",
                        data: [],
                        backgroundColor: "rgba(76,175,80,0.4)",
                        pointRadius: 2
                    }]
                },
                options: {
                    responsive: true,
                    animation: false,
                    plugins: { legend: { display: false }, tooltip: { enabled: false } },
                    scales: {
                        x: { min: -0.25, max: 0.25, grid: { color: "#263238" }, ticks: { color: "#546e7a", font: { size: 10 } } },
                        y: { min: -0.25, max: 0.25, grid: { color: "#263238" }, ticks: { color: "#546e7a", font: { size: 10 } } }
                    }
                }
            });

            log("Charts initialized");
            fetchData();
            setInterval(fetchData, 1000);
        }

        function fetchData() {
            var xhr = new XMLHttpRequest();
            xhr.open("GET", "/data", true);
            xhr.onreadystatechange = function() {
                if (xhr.readyState !== 4) return;
                if (xhr.status !== 200) {
                    showError("HTTP " + xhr.status);
                    return;
                }
                try {
                    var data = JSON.parse(xhr.responseText);
                } catch (e) {
                    showError("JSON parse error: " + e.message + " | Response: " + xhr.responseText.substring(0, 200));
                    return;
                }
                clearError();
                document.getElementById("statusText").textContent =
                    "peak=" + data.peak.toFixed(4) + " mean=" + data.mean.toFixed(4);
                document.getElementById("dot").className = "dot live";

                if (data.amp && data.amp.length > 0) {
                    timeChart.data.datasets[0].data = data.amp;
                    timeChart.update("none");

                    var points = [];
                    var maxPoints = 500;
                    for (var i = 0; i < Math.min(data.iq.length / 2, maxPoints) * 2; i += 2) {
                        points.push({ x: data.iq[i], y: data.iq[i + 1] });
                    }
                    scatterChart.data.datasets[0].data = points;
                    scatterChart.update("none");
                }
            };
            xhr.onerror = function() { showError("Network error"); };
            xhr.send();
        }

        window.addEventListener("load", initCharts);
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(
        HTML,
        freq=freq / 1e6,
        sr=sr / 1e6,
        chunk=chunk
    )


@app.route("/data")
def get_data():
    return {"amp": latest_data["amp"], "iq": latest_data["iq"],
            "peak": latest_data["peak"], "mean": latest_data["mean"]}


def stream_loop():
    global running, latest_data
    print("[{}] Stream thread starting...".format(datetime.now().strftime("%H:%M:%S")))
    running = True
    try:
        with BladeRFSdr() as sdr:
            print("[{}] BladeRF: {}".format(datetime.now().strftime("%H:%M:%S"), sdr.sdr.board_name))
            sdr.config_rx(freq=freq, sr=sr, gain=50)
            rx = Receiver(sdr)
            latest_data["connected"] = True
            while running:
                samples = rx.receive(chunk)
                samples = samples - samples.mean()
                latest_data = {
                    "amp": np.abs(samples).tolist(),
                    "iq": samples.real.tolist() + samples.imag.tolist(),
                    "connected": True,
                    "peak": float(np.abs(samples).max()),
                    "mean": float(np.abs(samples).mean())
                }
    except Exception as e:
        latest_data["connected"] = False
        print("[{}] Stream error: {}".format(datetime.now().strftime("%H:%M:%S"), e))


if __name__ == "__main__":
    t = Thread(target=stream_loop, daemon=True)
    t.start()
    print("[{}] Server: http://0.0.0.0:{}".format(datetime.now().strftime("%H:%M:%S"), web_port))
    print("[{}] Open http://localhost:{} in browser".format(datetime.now().strftime("%H:%M:%S"), web_port))
    app.run(host="0.0.0.0", port=web_port, debug=False, threaded=True, use_reloader=False)
