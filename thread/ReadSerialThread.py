import serial
from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL   
from models.RAWXData import RAWXData
from config import config
from logs.RawDataLogger import RawDataLogger
from realtime.pipeline import RealtimeSpoofingPipeline
from realtime.types import RealtimeEpochPair


#config


class ReadSerial:
    def append_with_limit(queue, item, maxlen=config.BUFFER_SAMPLES):
        queue.append(item)
        if len(queue) > maxlen:
            del queue[0]

    @staticmethod
    def build_realtime_output_map(detector_results):
        realtime_outputs = {}
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
    def read_serial(data_queue):
        logger = RawDataLogger()
        realtime_pipeline = RealtimeSpoofingPipeline()
        ser1 = serial.Serial(config.PORT1, baudrate=115200, timeout=1)
        ser2 = serial.Serial(config.PORT2, baudrate=115200, timeout=1)
        ubr1 = UBXReader(ser1, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, validate=1)
        ubr2 = UBXReader(ser2, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, validate=1)
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
                #logger.log(raw_data_1, raw_data_2)
                if (raw_data_1 is None) or (raw_data_2 is None):
                    continue
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
                #print(f"{rawx1.rcvTow} and {rawx2.rcvTow}")
                if rawx1 and nav1 and rawx2 and nav2 and (round(rawx1.rcvTow) == round(rawx2.rcvTow)):
                # if rawx1 and nav1 and rawx2 and nav2:
                    print(f"{rawx1.rcvTow} and {rawx2.rcvTow}")
                    epoch_pair = RealtimeEpochPair(
                        tow_s=min(float(rawx1.rcvTow), float(rawx2.rcvTow)),
                        rawx_1=rawx1,
                        nav_1=nav1,
                        rawx_2=rawx2,
                        nav_2=nav2,
                    )
                    detector_results = realtime_pipeline.process_epoch(epoch_pair)
                    realtime_outputs = ReadSerial.build_realtime_output_map(detector_results)
                    ReadSerial.append_with_limit(combined_samples, (rawx1, nav1, rawx2, nav2))
                    rawx1 = rawx2 = nav1 = nav2 = None
                    try:
                        if data_queue.full():
                            data_queue.get_nowait()  # bỏ phần tử cũ
                        data_queue.put(
                            (
                                combined_samples,
                                skyplot_data_1,
                                skyplot_data_2,
                                spectrum_data_1,
                                spectrum_data_2,
                                realtime_outputs,
                            )
                        )
                    except Exception as e:
                        print("Queue put error:", e)
            except Exception as e:
                print("\r\n")
                print("Error in get ublox data thread:", e)
