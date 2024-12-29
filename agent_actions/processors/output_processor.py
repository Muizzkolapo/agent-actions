import os
import json


class OutputProcessor:
    def __init__(self, parent_output, constructor_path):
        self.parent_output = parent_output
        self.constructor_path = constructor_path
        self.failed = False

    def combine_json_arrays(self,dir_1, dir_2, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        
        files_dir_1 = set([f for f in os.listdir(dir_1) if f.endswith('.json')])
        files_dir_2 = set([f for f in os.listdir(dir_2) if f.endswith('.json')])
        
        common_files = files_dir_1.intersection(files_dir_2)
        
        for filename in common_files:
            file_path_1 = os.path.join(dir_1, filename)
            file_path_2 = os.path.join(dir_2, filename)
            
            with open(file_path_1, 'r') as f1:
                data1 = json.load(f1)
            with open(file_path_2, 'r') as f2:
                data2 = json.load(f2)
            
            combined_data = data1 + data2
            
            output_path = os.path.join(output_dir, filename)
            with open(output_path, 'w') as out_f:
                json.dump(combined_data, out_f, indent=2)
        
        files_only_in_dir_1 = files_dir_1 - common_files
        for filename in files_only_in_dir_1:
            file_path_1 = os.path.join(dir_1, filename)
            with open(file_path_1, 'r') as f:
                data = json.load(f)
            output_path = os.path.join(output_dir, filename)
            with open(output_path, 'w') as out_f:
                json.dump(data, out_f, indent=2)
            print(f"Copied {filename} from dir_1 to {output_path}")
        
        files_only_in_dir_2 = files_dir_2 - common_files
        for filename in files_only_in_dir_2:
            file_path_2 = os.path.join(dir_2, filename)
            with open(file_path_2, 'r') as f:
                data = json.load(f)
            output_path = os.path.join(output_dir, filename)
            with open(output_path, 'w') as out_f:
                json.dump(data, out_f, indent=2)
            print(f"Copied {filename} from dir_2 to {output_path}")


    def process_final_output(self, ephemeral_directories):
        if not ephemeral_directories:
            return None

        final_agent_output_folder = ephemeral_directories[-1]['output_folder']
        final_workflow_output = os.path.join(os.path.dirname(final_agent_output_folder), 'final_workflow_output')
        os.makedirs(final_workflow_output, exist_ok=True)

        side_output_dir = os.path.join(os.path.dirname(final_agent_output_folder), 'side_output')

        if os.path.exists(side_output_dir):
            self.combine_json_arrays(final_agent_output_folder, side_output_dir, final_workflow_output)
        else:
            pass
            # Option 1: Skip the combination step
            # shutil.copytree(final_agent_output_folder, final_workflow_output)
            
            # Option 2: Create the side_output_dir if it doesn't exist
            # os.makedirs(side_output_dir, exist_ok=True)
            # self.combine_json_arrays(final_agent_output_folder, side_output_dir, final_workflow_output)
   