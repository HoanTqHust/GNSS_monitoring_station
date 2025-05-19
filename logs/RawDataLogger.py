import os
from datetime import datetime

class RawDataLogger:
    def __init__(self, base_dir="logs_data"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_current_folder_path(self):
        # Tạo tên thư mục theo định dạng YYYY-MM-DD_HH
        now = datetime.now()
        folder_name = now.strftime("SP-%Y-%m-%d_%H")
        return os.path.join(self.base_dir, folder_name)

    def log(self, raw_data_1, raw_data_2):
        folder_path = self._get_current_folder_path()
        os.makedirs(folder_path, exist_ok=True)

        file1_path = os.path.join(folder_path, "raw_data_1.ubx")
        file2_path = os.path.join(folder_path, "raw_data_2.ubx")

        with open(file1_path, "ab") as f1:
            f1.write(raw_data_1)

        with open(file2_path, "ab") as f2:
            f2.write(raw_data_2)
