import serial
from pyubx2 import UBXReader
from models.RAWXData import RAWXData
from config import config


#config


class ReadSerial:
    def append_with_limit(queue, item, maxlen=config.BUFFER_SAMPLES):
        queue.append(item)
        if len(queue) > maxlen:
            del queue[0]
    @staticmethod
    def read_serial(data_queue):
        
        ser1 = serial.Serial(config.PORT1, baudrate=38400, timeout=1)
        ser2 = serial.Serial(config.PORT2, baudrate=38400, timeout=1)
        ubr1 = UBXReader(ser1, protfilter=2)
        ubr2 = UBXReader(ser2, protfilter=2)
        timer = 0
        rawx1 = rawx2 = nav1 = nav2 = None
    
        skyplot_data_1 = ""
        spectrum_data_1 = ""
        skyplot_data_2 = ""
        spectrum_data_2 = ""
        combined_samples = []
    
        while True:
            try:
                raw_data_1, parsed_data_1 = ubr1.read()
                raw_data_2, parsed_data_2 = ubr2.read()
                if (raw_data_1 is None) or (raw_data_2 is None):
                    continue
                # print(parsed_data_1)
                # print(parsed_data_2)
                if parsed_data_1.identity == "NAV-SAT":
                    skyplot_data_1 = parsed_data_1
    
                if parsed_data_1.identity == "MON-SPAN":
                    spectrum_data_1 = parsed_data_1
    
                if parsed_data_1.identity == "RXM-RAWX":
                    rawx1 = RAWXData(parsed_data_1)
                if parsed_data_1.identity == "NAV-PVT":
                    nav1 = parsed_data_1
    
                if parsed_data_2.identity == "NAV-SAT":
                    skyplot_data_2 = parsed_data_2
    
                if parsed_data_2.identity == "MON-SPAN":
                    spectrum_data_2 = parsed_data_2
    
                if parsed_data_2.identity == "RXM-RAWX":
                    rawx2 = RAWXData(parsed_data_2)
                if parsed_data_2.identity == "NAV-PVT":
                    nav2 = parsed_data_2
    
                # Append only if both devices have valid RAWX and NAV-PVT
                if rawx1 and nav1 and rawx2 and nav2 and (round(rawx1.rcvTow) == round(rawx2.rcvTow)):
                # if rawx1 and nav1 and rawx2 and nav2:
                    print(f"{rawx1.rcvTow} and {rawx2.rcvTow}")
                    ReadSerial.append_with_limit(combined_samples, (rawx1, nav1, rawx2, nav2))
                    rawx1 = rawx2 = nav1 = nav2 = None
                    try:
                        if data_queue.full():
                            data_queue.get_nowait()  # bỏ phần tử cũ
                        data_queue.put((combined_samples, skyplot_data_1, skyplot_data_2, spectrum_data_1, spectrum_data_2))
                    except Exception as e:
                        print("Queue put error:", e)
            except Exception as e:
                print("Error in get ublox data thread:", e)