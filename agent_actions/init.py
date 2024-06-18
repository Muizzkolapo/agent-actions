"""
Module for initializing a new Agent Actions project.
"""
import os
import argparse
import yaml

def create_directory(path):
    """
    Create a directory if it doesn't exist.

    :param path: The path of the directory to create.
    """
    if not os.path.exists(path):
        os.makedirs(path)
        print(f"Created directory: {path}")
    else:
        print(f"Directory already exists: {path}")


def create_file(path, content=""):
    """
    Create a file if it doesn't exist.

    :param path: The path of the file to create.
    :param content: The content to write to the file (default is an empty string).
    """
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Created file: {path}")
    else:
        print(f"File already exists: {path}")


def init(project_name):
    """
    Initialize a new Agent Actions project.

    :param project_name: The name of the new project.
    """
    project_dir = os.path.join(os.getcwd(), project_name)
    config_dir = os.path.join(project_dir, 'agent_config')
    schema_dir = os.path.join(project_dir, 'schema')
    io_dir = os.path.join(project_dir, 'agent_io')
    config_file = os.path.join(project_dir, 'agent_actions.yml')

    # Create project directory
    create_directory(project_dir)

    # Create directories
    create_directory(config_dir)
    create_directory(schema_dir)
    create_directory(io_dir)

    # Create empty Agent Actions configuration file
    config_data = {
        "default_agent_config": {
            "api_key": "OPENAI_API_KEY",
            "model_name": "gpt-3.5-turbo",
            "chunk_config": {
                "chunk_size": 300,
                "chunk_overlap": 10
            }
        }
    }
    create_file(config_file, yaml.dump(config_data))


def main():
    """
    Main function to parse command-line arguments and initialize the project.
    """
    parser = argparse.ArgumentParser(description="Initialize a new Agent Actions project.")
    parser.add_argument("project_name", help="The name of the new project")
    args = parser.parse_args()
    init(args.project_name)


if __name__ == "__main__":
    main()
