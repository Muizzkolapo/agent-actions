"""Module for writing data loading and processing."""
import json
import csv
from pathlib import Path
from agent_actions.shared.exceptions import AgentActionsException
from agent_actions.utilities.error_handling import ProcessorErrorHandlerMixin

class FileWriter(ProcessorErrorHandlerMixin):

    def __init__(self, file_path):
        super().__init__()
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
                    raise AgentActionsException(f'Unsupported file type for staging: {self.file_type} for file {self.file_path}')
        except IOError as e:
            self.handle_file_error(e, 'write_staging', self.file_path, file_type=self.file_type)
        except Exception as e:
            self.handle_processing_error(e, f'Write staging file {self.file_path}', file_path=self.file_path, file_type=self.file_type)

    def write_target(self, data):
        try:
            Path(self.file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)
        except IOError as e:
            self.handle_file_error(e, 'write_target', self.file_path, file_type=self.file_type)
        except Exception as e:
            self.handle_processing_error(e, f'Write target file {self.file_path}', file_path=self.file_path, file_type=self.file_type)

    def write_source(self, data):
        try:
            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)
        except IOError as e:
            self.handle_file_error(e, 'write_source', self.file_path, file_type=self.file_type)
        except Exception as e:
            self.handle_processing_error(e, f'Write source file {self.file_path}', file_path=self.file_path, file_type=self.file_type)