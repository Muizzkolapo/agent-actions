"""Module for Data Manipulation Functions."""
import logging
import copy

logger = logging.getLogger(__name__)

from agent_actions.logging_setup import setup_logging
logger = setup_logging()


class DataTransformer:
    """
    A class for data manipulation and transformation.
    """

    @staticmethod
    def update_schema_objects(data_old, data_new, keys_to_update):
        """
        Updates data based on structure comparison:
        - If the value types match for a given key, replace `data_new` value with `data_old` value.
        - If the value types differ, append the `data_old` key/value into `data_new`.

        Parameters:
            data_old (dict): Original data dictionary.
            data_new (dict): Dictionary to be updated.
            keys_to_update (list): Keys to be considered for updating.

        Returns:
            dict: Updated data_new dictionary.
        """
        updated_data = copy.deepcopy(data_new)

        for key in keys_to_update:
            if key in data_old:
                old_value = data_old[key]
                new_value = updated_data.get(key, None)

                if new_value is not None:
                    if isinstance(old_value, type(new_value)):
                        updated_data[key] = old_value
                    else:
                        updated_data[key] = [new_value, old_value]
                else:
                    updated_data[key] = old_value

        return updated_data



    @staticmethod
    def extract_objects(input_data):
        """
        Extracts the list of summaries from the input dictionary.

        Parameters:
            input_data (dict or list): Dictionary containing a list of summaries under any key.

        Returns:
            list: List of summaries.
        """
        try:
            if isinstance(input_data, list):
                for field_name, field_value in input_data[0].items():
                    if isinstance(field_value, list):
                        return field_value
            else:
                for field_name, field_value in input_data.items():
                    if isinstance(field_value, list):
                        return field_value
        except Exception as e:
            print(f"An error occurred while extracting summaries: {e}")
        return []

    @staticmethod
    def flatten_to_list_of_dicts(nested_lists):
        """
        Flattens a nested list of lists containing dictionaries into a single list of dictionaries.

        Parameters:
            nested_lists (list): A nested list where each inner list contains dictionaries.

        Returns:
            list: A flat list containing all dictionaries from the nested structure.
        """
        flattened_list = []

        for sublist in nested_lists:
            flattened_list.extend(sublist)

        return flattened_list

    @staticmethod
    def transform_structure(data):
        """
        Transforms a list of dictionaries with nested contents into a flat list of dictionaries.

        Parameters:
            data (list): List of dictionaries to transform.

        Returns:
            list: Transformed list of dictionaries.
        """
        transformed_data = []
        for data_item in data:
            for guid, contents in data_item.items():
                for content in contents:
                    transformed_data.append({
                        "guid": guid,
                        "content": content
                    })
        return transformed_data

    @staticmethod
    def ensure_list(obj):
        """
        Ensures that the input object is a list.

        Parameters:
            obj (Any): The object to ensure as a list.

        Returns:
            list: The object wrapped in a list if it wasn't already a list.
        """
        if not isinstance(obj, list):
            return [obj]
        return obj

    @staticmethod
    def get_content_by_guid(data, guid):
        """
        Retrieve the content associated with a specific GUID from a list of dictionaries.

        Parameters:
            data (list of dict): The list containing dictionaries with GUIDs as keys.
            guid (str): The GUID to search for.

        Returns:
            str: The content associated with the GUID, or a message if not found.
        """
        for item in data:
            if guid in item:
                return item[guid]
        return "GUID not found."

