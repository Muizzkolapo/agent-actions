"""Module for writing data loading and processing."""
import os
import json
import csv

class FileWriter:
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_type = os.path.splitext(file_path)[1].lower()

    def write_staging(self, data):
        try:
            with open(self.file_path, 'w', encoding='utf-8') as file:
                if self.file_type == '.json':
                    json.dump(data, file, indent=4)
                elif self.file_type == '.txt':
                    if isinstance(data, list):
                        file.write('\n'.join(data))
                    else:
                        file.write(data)
                elif self.file_type == '.csv':
                    writer = csv.writer(file)
                    writer.writerows(data)
                else:
                    print(f"Unsupported file type: {self.file_type}")
        except Exception as e:
            print(f"Error writing file {self.file_path}: {str(e)}")

    def write_target(self, data):
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)
        except Exception as e:
            print(f"Error writing file {self.file_path}: {str(e)}")

    def write_source(self, data):
        try:
            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)
        except Exception as e:
            print(f"Error writing file {self.file_path}: {str(e)}")
