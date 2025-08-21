#!/bin/bash

# Production Allocation Optimizer Runner
# Runs the main.py script with input files from the inputs folder

# Get the script's directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Input file paths
PLANTS_FILE="$PROJECT_ROOT/inputs/plants-info-1.json"
ORDERS_FILE="$PROJECT_ROOT/inputs/to_be_allocated-1.json"

# Python executable (use virtual environment if available)
if [ -f "$PROJECT_ROOT/.venv/Scripts/python.exe" ]; then
    PYTHON_EXE="$PROJECT_ROOT/.venv/Scripts/python.exe"
elif [ -f "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON_EXE="$PROJECT_ROOT/.venv/bin/python"
else
    PYTHON_EXE="python"
fi

echo "Running Production Allocation Optimizer..."
echo "Plants file: $PLANTS_FILE"
echo "Orders file: $ORDERS_FILE"
echo "Python executable: $PYTHON_EXE"
echo ""

# Change to project root directory
cd "$PROJECT_ROOT"

# Run the main script
$PYTHON_EXE main.py --plants "$PLANTS_FILE" --orders "$ORDERS_FILE"