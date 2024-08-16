import os
import json
import pandas as pd

def read_json_files_from_directory(directory_path):
    data = []
    for filename in os.listdir(directory_path):
        if filename.endswith('.json'):
            with open(os.path.join(directory_path, filename), 'r', encoding='utf-8') as file:
                data.extend(json.load(file))
    return data

def save_to_csv(data, output_path):
    df = pd.DataFrame(data)
    df.to_csv(output_path, index=False)

def main(directory_path, output_path):
    data = read_json_files_from_directory(directory_path)
    save_to_csv(data, output_path)

directory_path = '/Users/muizz/Documents/codeshop/qanalabs/qanalabs-actions/flashcard_enhancer'  # Replace with your directory path
output_path = 'merged_output.csv'  # Replace with your desired output CSV file path
main(directory_path, output_path)
