# Variables
PACKAGE := agent_actions
DIST_DIR := dist
BUILD_DIR := build

# Uninstall the package
uninstall: 
	pip uninstall -y $(PACKAGE) || echo "WARNING: Skipping $(PACKAGE) as it is not installed."

# Clean build artifacts
clean:
	rm -rf dist build *.egg-info

# Build the package
build: 
	python3 setup.py sdist bdist_wheel && pip3 install dist/agent_actions-0.1.0-py3-none-any.whl 

# dev build
dev: 
	pip install -e ".[dev]"
	
# Restart by uninstalling, cleaning, and rebuilding
restart: uninstall clean build

.PHONY: all install uninstall clean build restart dev


