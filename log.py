import serial
from pyubx2 import UBXReader
from config import config
from logs.RawDataLogger import RawDataLogger

# Initialize logger and serial connections
logger = RawDataLogger()
ser1 = serial.Serial(config.PORT1, baudrate=38400, timeout=1)
ser2 = serial.Serial(config.PORT2, baudrate=38400, timeout=1)
ser3 = serial.Serial(config.PORT3, baudrate=38400, timeout=1)


# Initialize UBXReaders with protocol filter set to 2 (UBX only)
ubr1 = UBXReader(ser1, protfilter=2)
ubr2 = UBXReader(ser2, protfilter=2)
ubr3 = UBXReader(ser3, protfilter=2)

# Read and log data in a loop
while True:
    try:
        raw_data_1, parsed_data_1 = ubr1.read()
        raw_data_2, parsed_data_2 = ubr2.read()
        raw_data_3, parsed_data_3 = ubr3.read()
        logger.log(raw_data_1, raw_data_2,raw_data_3)
    except KeyboardInterrupt:
        print("Terminated by user.")
        break
    except Exception as e:
        print(f"Error: {e}")
        break

# Close serial ports
ser1.close()
ser2.close()
ser3.close()
