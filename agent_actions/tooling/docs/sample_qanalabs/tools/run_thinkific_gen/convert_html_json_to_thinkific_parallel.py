import pandas as pd
import json
import os
import re
from html import unescape
from typing import Any, Dict, List, TypedDict, Union
from collections import defaultdict
from agent_actions import udf_tool


class ConvertHtmlJsonToThinkificInput(TypedDict, total=False):
    """Input schema for convert_html_json_to_thinkific function."""
    question: str
    explanation: str
    options: List[Any]
    answer_letter: str
    answer_indices: List[int]
    question_type: str
    batch_name: str
    content: dict
    source_guid: str
    target_id: str
    node_id: str
    lineage: List[Any]


@udf_tool()
def convert_html_json_to_thinkific(json_data):
    """
    Convert the specific HTML-based JSON format to Thinkific format and save as Excel files.
    This version handles multiple batches properly for parallel agent processing.
    
    :param json_data: list, JSON data containing questions with HTML content
    :return: list of dictionaries, each containing batch_name and processed data
    """
    
    # Group data by batch_name
    batches = defaultdict(list)
    
    for item in json_data:
        content = item.get('content', {})
        batch_name = content.get('batch_name', 'default_batch')
        batches[batch_name].append(item)
    
    # Process each batch separately
    results = []
    
    for batch_name, batch_data in batches.items():
        # Prepare the transformed data for this batch
        transformed_data = []
        
        for data in batch_data:
            data_content = data['content']
            
            # Clean Unicode control characters from text fields
            question_text = re.sub(r'[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]', '', 
                                 data_content.get("question", ""))
            explanation_text = re.sub(r'[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]', '', 
                                    data_content.get("explanation", ""))
            question_type = data_content.get("question_type", "SA")
            
            transformed_row = {
                "QuestionType": question_type,
                "QuestionText": question_text,
                "Explanation": explanation_text
            }
            
            # Add choices
            options = data_content.get("options", [])
            for i, choice in enumerate(options, start=1):
                # Clean Unicode control characters from choices too
                clean_choice = re.sub(r'[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]', '', choice)
                transformed_row[f"Choice{i}"] = clean_choice
            
            transformed_data.append(transformed_row)
        
        # Save the transformed data into the Thinkific template format
        transformed_df = pd.DataFrame(transformed_data)
        
        # Create output path for this specific batch
        # Get the template path relative to this file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        thinkific_template_path = os.path.join(current_dir, "thinkific_quiz_question_import_template.xlsx")

        # Output to target directory
        output_dir = os.path.join(os.path.dirname(current_dir), "..", "agent_workflow", "run_thinkific_gen", "agent_io", "target", "converted_thinkific")
        output_path = os.path.join(output_dir, f"{batch_name}.xlsx")
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            try:
                # Try to preserve the original formatting of the Thinkific template
                template_workbook = pd.read_excel(thinkific_template_path, engine='openpyxl', sheet_name=None)
                for sheet_name, sheet_df in template_workbook.items():
                    sheet_df.to_excel(writer, index=False, sheet_name=sheet_name)

                workbook = writer.book
                first_sheet_name = workbook.sheetnames[0]
                worksheet = workbook[first_sheet_name]

                # Clear all template data rows (keep only headers)
                for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row):
                    for cell in row:
                        cell.value = None

                # Write the transformed data to the worksheet
                for r_idx, row in enumerate(transformed_df.to_numpy(), 1):
                    for c_idx, value in enumerate(row, 1):
                        if pd.notna(value):
                            worksheet.cell(row=r_idx + 1, column=c_idx, value=value)
                            
            except Exception as e:
                print(f"An error occurred while preserving template formatting for batch {batch_name}: {e}")
                # Fallback: Save without formatting if an error occurs
                transformed_df.to_excel(writer, index=False)
        
        # Add batch result to results list
        batch_result = {
            'batch_name': batch_name,
            'output_path': output_path,
            'questions_processed': len(transformed_data),
            'data': batch_data  # Return original data for this batch
        }
        results.append(batch_result)
        
        print(f"Batch '{batch_name}': {len(transformed_data)} questions processed. File saved to {output_path}")
    
    # Return results suitable for parallel processing
    # Each item in the list represents a separate batch that can be processed independently
    return results


def convert_html_json_to_thinkific_single_batch(batch_data, batch_name, output_directory=None):
    """
    Process a single batch of data. This version is optimized for parallel execution
    where each agent processes one batch.
    
    :param batch_data: list, JSON data for a single batch
    :param batch_name: str, name of the batch
    :param output_directory: str, optional output directory (defaults to hardcoded path)
    :return: dict containing batch processing results
    """
    
    # Prepare the transformed data
    transformed_data = []
    
    for data in batch_data:
        data_content = data['content']
        
        # Clean Unicode control characters from text fields
        question_text = re.sub(r'[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]', '',
                             data_content.get("question", ""))
        explanation_text = re.sub(r'[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]', '',
                                data_content.get("explanation", ""))
        question_type = data_content.get("question_type", "SA")

        transformed_row = {
            "QuestionType": question_type,
            "QuestionText": question_text,
            "Explanation": explanation_text
        }

        # Add choices
        options = data_content.get("options", [])
        for i, choice in enumerate(options, start=1):
            # Clean Unicode control characters from choices too
            clean_choice = re.sub(r'[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]', '', choice)
            transformed_row[f"Choice{i}"] = clean_choice
        
        transformed_data.append(transformed_row)
    
    # Save the transformed data into the Thinkific template format
    transformed_df = pd.DataFrame(transformed_data)
    
    # Get the template path relative to this file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    thinkific_template_path = os.path.join(current_dir, "thinkific_quiz_question_import_template.xlsx")

    # Determine output path
    if output_directory:
        output_path = os.path.join(output_directory, f"{batch_name}.xlsx")
    else:
        output_dir = os.path.join(os.path.dirname(current_dir), "..", "agent_workflow", "run_thinkific_gen", "agent_io", "target", "converted_thinkific")
        output_path = os.path.join(output_dir, f"{batch_name}.xlsx")
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        try:
            # Try to preserve the original formatting of the Thinkific template
            template_workbook = pd.read_excel(thinkific_template_path, engine='openpyxl', sheet_name=None)
            for sheet_name, sheet_df in template_workbook.items():
                sheet_df.to_excel(writer, index=False, sheet_name=sheet_name)

            workbook = writer.book
            first_sheet_name = workbook.sheetnames[0]
            worksheet = workbook[first_sheet_name]

            # Clear all template data rows (keep only headers)
            for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row):
                for cell in row:
                    cell.value = None

            # Write the transformed data to the worksheet
            for r_idx, row in enumerate(transformed_df.to_numpy(), 1):
                for c_idx, value in enumerate(row, 1):
                    if pd.notna(value):
                        worksheet.cell(row=r_idx + 1, column=c_idx, value=value)

        except Exception as e:
            print(f"An error occurred while preserving template formatting: {e}")
            # Fallback: Save without formatting if an error occurs
            transformed_df.to_excel(writer, index=False)
    
    return {
        'batch_name': batch_name,
        'output_path': output_path,
        'questions_processed': len(transformed_data),
        'status': 'success'
    }