class SatelliteData:
    def __init__(self, parsed_data, i):
        self.prMes = getattr(parsed_data, f'prMes_{i:02}', None)
        self.cpMes = getattr(parsed_data, f'cpMes_{i:02}', None)
        self.doMes = getattr(parsed_data, f'doMes_{i:02}', None)
        self.gnssId = getattr(parsed_data, f'gnssId_{i:02}', None)
        self.svId = getattr(parsed_data, f'svId_{i:02}', None)
        self.sigId = getattr(parsed_data, f'sigId_{i:02}', None)
