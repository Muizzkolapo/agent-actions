"""Setup script for the package."""
from pathlib import Path
from setuptools import setup, find_packages


def read(fname):
    """Read the contents of a file."""
    with open(Path(__file__).parent / fname, encoding='utf-8') as file:
        return file.read()


with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name='agent_actions',
    version='0.1.0',
    packages=find_packages(),
    include_package_data=True,
    install_requires=requirements,
    extras_require={
        'dev': [
            'pytest',
            'pylint',
            'pytest-cov'
        ],
    },
    entry_points={
        'console_scripts': [
            'agent=agent_actions.cli.main:main'
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
