import pandas as pd
import json
import os
import re
from html import unescape

import json
import re
from typing import Dict, List, Union


def convert_html_json_to_thinkific(json_data):

    """
    Convert the specific HTML-based JSON format to Thinkific format and save as Excel file.
    
    :param json_data: list, JSON data containing questions with HTML content
    :param thinkific_template_path: str, path to the Thinkific template Excel file
    :param output_path: str, path where the output Excel file will be saved
    """

    # Prepare the transformed data
    transformed_data = []

    #batch_name = json_data[0]['content']['batch_name']
    batch_name = 'batch_1'
    
    for data in json_data:
        data = data['content']
        #is_multiple_answers = 'MA' if data['MultipleCorrect'] else 'SA'  # Check if multiple answers are present
        
        # Clean Unicode control characters from text fields
        question_text = re.sub(r'[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]', '', data["question_thinkific_loader"])
        explanation_text = re.sub(r'[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]', '', data["explanation_thinkific_loader"])
        
        transformed_row = {
            "QuestionType": "SA",
            "QuestionText": question_text,
            "Explanation": explanation_text
        }
        for i, choice in enumerate(data["options_thinkific_loader"], start=1):
            # Clean Unicode control characters from choices too
            clean_choice = re.sub(r'[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]', '', choice)
            transformed_row[f"Choice{i}"] = clean_choice
        transformed_data.append(transformed_row)

    # Save the transformed data into the Thinkific template format
    transformed_df = pd.DataFrame(transformed_data)
    

    output_path = f"/Users/muizz/Documents/codeshop/qanalabs/qanalabs-actions/qanalabs/tools/{batch_name}.xlsx"
    thinkific_template_path = "/Users/muizz/Documents/codeshop/qanalabs/qanalabs-actions/qanalabs/tools/thinkific_template/thinkific_quiz_question_import_template.xlsx"
    
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        try:
            # Try to preserve the original formatting of the Thinkific template
            template_workbook = pd.read_excel(thinkific_template_path, engine='openpyxl', sheet_name=None)
            for sheet_name, sheet_df in template_workbook.items():
                sheet_df.to_excel(writer, index=False, sheet_name=sheet_name)

            workbook = writer.book
            first_sheet_name = workbook.sheetnames[0]
            worksheet = workbook[first_sheet_name]

            # Write the transformed data to the worksheet
            for r_idx, row in enumerate(transformed_df.to_numpy(), 1):
                for c_idx, value in enumerate(row, 1):
                    if pd.notna(value):
                        worksheet.cell(row=r_idx + 1, column=c_idx, value=value)
                        
        except Exception as e:
            print(f"An error occurred while preserving template formatting: {e}")
            # Fallback: Save without formatting if an error occurs
            transformed_df.to_excel(writer, index=False)

    #print(f"JSON data transformation complete. {len(transformed_data)} questions processed. File saved to {output_path}")
    return json_data