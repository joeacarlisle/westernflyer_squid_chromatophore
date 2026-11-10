#!/bin/bash
#
# Analyse every videos/*.mp4 (or one video:  ./chromatophore_build.sh <video_id>).
# Make executable once with:  chmod +x chromatophore_build.sh

# Move to the project root (up two levels from where this script is located)
cd "$(dirname "$0")/../.."

if [ -f ".venv/bin/python" ]; then
    PYTHON_EXE=".venv/bin/python"
else
    echo "[INFO] Virtual environment not found. Attempting to use global Python..."
    PYTHON_EXE="python3"
fi

"$PYTHON_EXE" main.py "$@"
if [ $? -ne 0 ]; then
    echo
    echo "[ERROR] The analysis failed. Please check the messages above."
    read -p "Press any key to continue..."
fi
