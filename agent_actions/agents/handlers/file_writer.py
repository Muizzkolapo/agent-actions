"""Module for writing data loading and processing."""
import json
import csv
from pathlib import Path
from agent_actions.core.exceptions import AgentActionsException

class FileWriter:
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_type = Path(file_path).suffix.lower()

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
                    raise AgentActionsException(f"Unsupported file type for staging: {self.file_type} for file {self.file_path}")
        except IOError as e:
            raise AgentActionsException(f"IOError writing staging file {self.file_path}: {str(e)}") from e
        except Exception as e:
            raise AgentActionsException(f"Error writing staging file {self.file_path}: {str(e)}") from e

    def write_target(self, data):
        try:
            Path(self.file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)
        except IOError as e:
            raise AgentActionsException(f"IOError writing target file {self.file_path}: {str(e)}") from e
        except Exception as e:
            raise AgentActionsException(f"Error writing target file {self.file_path}: {str(e)}") from e

    def write_source(self, data):
        try:
            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)
        except IOError as e:
            raise AgentActionsException(f"IOError writing source file {self.file_path}: {str(e)}") from e
        except Exception as e:
            raise AgentActionsException(f"Error writing source file {self.file_path}: {str(e)}") from e
