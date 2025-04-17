from models.SatelliteData import SatelliteData
class RAWXData:
    def __init__(self, parsed_data):
        self.rcvTow = parsed_data.rcvTow
        self.week = parsed_data.week
        self.satData = []
        for i in range(1, parsed_data.numMeas + 1):
            self.satData.append(SatelliteData(parsed_data, i))