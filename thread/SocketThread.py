import time
import psutil
from draws.UbloxChart import UbloxChart
from config import config
class SocketThread:
    @staticmethod
    def background_thread(data_queue, socketio):
       print("Background thread started")
       last_plot_time = time.time()
       while True:
           try:
               # Plot if enough time passed and buffer is full
               current_time = time.time()
               dps_plot = ""
               cpu_load = psutil.cpu_percent(interval=0.5)
               combined_samples, skyplot_data_1, skyplot_data_2, spectrum_data_1, spectrum_data_2 = data_queue.get()
               print(f"combined_samples: {len(combined_samples)}")
               if current_time - last_plot_time >= config.PLOT_INTERVAL:
                   if config.FIX == 1:
                       print("combined_samples", combined_samples)
                   last_plot_time = current_time
                   dps_plot = UbloxChart.raw2ImageDps(combined_samples)
               if (dps_plot == ""):
                   print("Dont send")

               else:
                   print("Sended data")
                   skyplot_1 = UbloxChart.raw2ImageSkyplot(skyplot_data_1)
                   skyplot_2 = UbloxChart.raw2ImageSkyplot(skyplot_data_2)
                   spectrum_1 = UbloxChart.raw2ImageSpectrum(spectrum_data_1)
                   spectrum_2 = UbloxChart.raw2ImageSpectrum(spectrum_data_2)
                   socketio.emit("update_image", {
                       "skyplot1": "data:image/png;base64," + skyplot_1,
                       "spectrum1": "data:image/png;base64," + spectrum_1,
                       "skyplot2": "data:image/png;base64," + skyplot_2,
                       "spectrum2": "data:image/png;base64," + spectrum_2,
                       "cpu_load": cpu_load,
                       "dps": "data:image/png;base64," + dps_plot,
                   })
           except Exception as e:
               print("Error in background thread:", e)