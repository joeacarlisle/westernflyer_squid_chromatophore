#!/bin/bash
#
# Create the synthetic demo video and analyse it.
# Make executable once with:  chmod +x chromatophore_demo.sh

cd "$(dirname "$0")/../.."

if [ -f ".venv/bin/python" ]; then
    PYTHON_EXE=".venv/bin/python"
else
    echo "[INFO] Virtual environment not found. Attempting to use global Python..."
    PYTHON_EXE="python3"
fi

"$PYTHON_EXE" main.py --demo
if [ $? -ne 0 ]; then
    echo
    echo "[ERROR] The demo failed. Please check the messages above."
    read -p "Press any key to continue..."
fi
