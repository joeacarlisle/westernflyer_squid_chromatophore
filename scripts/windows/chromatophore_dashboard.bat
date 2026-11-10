@echo off
:: Move to the project root (up two levels from where this script is located)
pushd "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
    echo [INFO] Found virtual environment. Launching...
    set PYTHON_EXE=.venv\Scripts\python.exe
) else (
    echo [INFO] Virtual environment not found. Attempting to use global Python...
    set PYTHON_EXE=python
)

:: --static-dirs lets the browser play videos\*.mp4
%PYTHON_EXE% -m panel serve chromatophore_holoviews.py --port 5009 --static-dirs videos=videos --show

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] The dashboard failed to launch. Please check the logs above.
    pause
)
popd
