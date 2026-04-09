import os
from dotenv import load_dotenv

load_dotenv()
class config:
     
    PORT1 = os.environ.get("PORT1", "/dev/ttyACM0")
    
    PORT2 = os.environ.get("PORT2", "/dev/ttyACM1")
    
    PORT3 = os.environ.get("PORT3", "/dev/ttyACM2")
    
    # BUFFER_SAMPLES = int(os.environ.get("BUFFER_SAMPLES", 30))
    BUFFER_SAMPLES = int(os.environ.get("BUFFER_SAMPLES", 150))
    
    PLOT_INTERVAL = float(os.environ.get("PLOT_INTERVAL", 2.0))
    
    FIX = int(os.environ.get("FIX", 0))
    
    HOSTSOCKET = os.environ.get("HOSTSOCKET", "0.0.0.0")
    
    PORTSOCKET = int(os.environ.get("PORTSOCKET", 5000))
    
    ELE_MASK = int(os.environ.get("ELE_MASK", 15))
