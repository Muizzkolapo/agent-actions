"""Setup script for the package."""
import os
from setuptools import setup, find_packages


def read(fname):
    """Read the contents of a file."""
    with open(os.path.join(os.path.dirname(__file__), fname), encoding='utf-8') as file:
        return file.read()


setup(
    name='agent_actions',
    version='0.1.0',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'pyyaml',
        'openai==1.26.0',
        'langchain==0.1.15',
        'tiktoken==0.6.0',
        'langchain-openai==0.1.3',
        'flask==3.0.3',
        'flask-cors==4.0.1',
        'networkx==3.3',
        'pypdf2==3.0.1',
        'python-docx==1.1.2',
        'pandas==2.2.2',
        'openpyxl==3.1.2',
        'beautifulsoup4==4.12.3',
        'google-api-python-client==2.130.0',
        'groq',
        'grpcio==1.66.0'
    ],
    entry_points={
        'console_scripts': [
            'agent-run=agent_actions.core.runner:main',
            'agent-init=agent_actions.core.init:main',
            'agent-dags=agent_actions.docs.app:main'
        ],
    },
    package_data={
        'agent_actions': [
            'agent_actions.yml',
            'agent_config/*.yml',
            'agent_dags/templates/*.html',
            'agent_dags/static/**/*'
        ],
    },
    author='Muizz Lateef',
    author_email='lateefmuizz@gmail.com',
    description='A description of your package',
    long_description=read('README.md'),
    long_description_content_type='text/markdown',
    url='https://github.com/Muizzkolapo/agent-actions',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)
