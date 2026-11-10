#!/bin/bash
#
# Make executable once with:  chmod +x chromatophore_dashboard.sh

# Move to the project root (up two levels from where this script is located)
cd "$(dirname "$0")/../.."

if [ -f ".venv/bin/python" ]; then
    echo "[INFO] Found virtual environment. Launching..."
    PYTHON_EXE=".venv/bin/python"
else
    echo "[INFO] Virtual environment not found. Attempting to use global Python..."
    PYTHON_EXE="python3"
fi

# --static-dirs lets the browser play videos/*.mp4.  Remove --show on headless servers.
"$PYTHON_EXE" -m panel serve chromatophore_holoviews.py --port 5009 --static-dirs videos=videos --show
if [ $? -ne 0 ]; then
    echo
    echo "[ERROR] The dashboard failed to launch. Please check the logs above."
    read -p "Press any key to continue..."
fi
