"""
Module for generating agent lineage and providing agent details.
"""
import os
import yaml
from flask import Flask, jsonify, render_template, request
import networkx as nx
from flask_cors import CORS

app = Flask(__name__, template_folder='agent_dags/templates', static_folder='agent_dags/static')
CORS(app)

# Ensure BASE_DIR is the current working directory of the running application
BASE_DIR = os.getcwd()
CONFIG_DIR = os.path.join(BASE_DIR, 'agent_config')
print(CONFIG_DIR)


def get_folder_structure(directory, base_path=''):
    """
    Get the folder structure of the specified directory.
    """
    structure = []
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        relative_path = os.path.join(base_path, item)
        if os.path.isdir(item_path):
            structure.append({
                'name': item,
                'path': relative_path,
                'type': 'folder',
                'children': get_folder_structure(item_path, relative_path)
            })
        elif os.path.isfile(item_path) and item.endswith('.yml'):
            structure.append({
                'name': item,
                'path': relative_path,
                'type': 'file'
            })
    return structure


def get_yaml_files(directory, base_path=''):
    """
    Get the YAML files in the specified directory.
    """
    structure = []
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        relative_path = os.path.join(base_path, item)
        if os.path.isdir(item_path):
            subdir_structure = get_yaml_files(item_path, relative_path)
            if subdir_structure:
                structure.append({
                    'name': item,
                    'path': relative_path,
                    'type': 'folder',
                    'children': subdir_structure
                })
        elif os.path.isfile(item_path) and item.endswith('.yml'):
            structure.append({
                'name': item,
                'path': relative_path,
                'type': 'file'
            })
    return structure


@app.route('/list_yaml_files', methods=['GET'])
def list_yaml_files():
    """
    List all YAML files in the CONFIG_DIR.
    """
    structure = get_yaml_files(CONFIG_DIR)
    return jsonify(structure)


def load_single_yaml_file(filename):
    """
    Load a single YAML file.
    """
    filepath = os.path.join(CONFIG_DIR, filename)
    with open(filepath, 'r', encoding='utf-8') as file:
        content = yaml.safe_load(file)
    return content


def extract_dependencies(config_data):
    """
    Extract dependencies from the configuration data.
    """
    dependencies = {}
    for agents in config_data.values():
        for agent in agents:
            agent_name = agent['agent_type']
            agent_dependencies = agent.get('dependencies', [])
            dependencies[agent_name] = agent_dependencies
    return dependencies


def build_dag(dependencies):
    """
    Build a directed acyclic graph (DAG) from the dependencies.
    """
    dag = nx.DiGraph()
    for agent, deps in dependencies.items():
        for dep in deps:
            dag.add_edge(dep, agent)
    return dag


@app.route('/list_folder_structure', methods=['GET'])
def list_folder_structure():
    """
    List the folder structure of the CONFIG_DIR.
    """
    structure = get_folder_structure(CONFIG_DIR)
    return jsonify(structure)


@app.route('/generate_agent_lineage', methods=['POST'])
def generate_agent_lineage():
    """
    Generate agent lineage based on the provided filename.
    """
    filename = request.json.get('filename')
    config_data = load_single_yaml_file(filename)

    dependencies = extract_dependencies(config_data)
    dag = build_dag(dependencies)

    edges = [{'source': u, 'target': v} for u, v in dag.edges]
    nodes = [{'id': n} for n in dag.nodes]

    return jsonify({'nodes': nodes, 'edges': edges})


@app.route('/get_agent_details', methods=['POST'])
def get_agent_details():
    """
    Get details of a specific agent based on the provided filename and agent name.
    """
    filename = request.json.get('filename')
    agent_name = request.json.get('agent_name')
    config_data = load_single_yaml_file(filename)

    for agents in config_data.values():
        for agent in agents:
            if agent['agent_type'] == agent_name:
                return jsonify(agent)
    return jsonify({'error': 'Agent not found'}), 404


@app.route('/')
def index():
    """
    Render the index template.
    """
    return render_template('index.html')


def main():
    """
    Run the Flask application.
    """
    app.run(debug=True, host='0.0.0.0', port=8000)


if __name__ == '__main__':
    main()
