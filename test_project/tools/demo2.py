import os
import json
import csv

def convert_json_to_csv(json_folder, output_csv):
    # Initialize an empty list to hold all terms and definitions
    combined_data = []

    # Iterate over all files in the specified folder
    for filename in os.listdir(json_folder):
        if filename.endswith('.json'):
            filepath = os.path.join(json_folder, filename)
            # Open and load the JSON file
            with open(filepath, 'r') as json_file:
                data = json.load(json_file)
                # Extend the combined_data list with the contents of the current JSON file
                combined_data.extend(data)
    
    # Write the combined data to the output CSV file
    with open(output_csv, 'w', newline='', encoding='utf-8') as csv_file:
        csv_writer = csv.writer(csv_file)
        # Write the header
        csv_writer.writerow(['term', 'definition'])
        # Write each term and definition
        for item in combined_data:
            csv_writer.writerow([item['term'], item['definition']])

# Specify the folder containing JSON files and the output CSV file
json_folder = '/Users/muizz/Documents/codeshop/qanalabs/qanalabs-actions/flashcards/formated'
output_csv = './terms_definitions.csv'

# Call the function to perform the conversion
convert_json_to_csv(json_folder, output_csv)
