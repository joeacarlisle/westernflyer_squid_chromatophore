@echo off
:: Create the synthetic demo video and analyse it.
pushd "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
    set PYTHON_EXE=.venv\Scripts\python.exe
) else (
    echo [INFO] Virtual environment not found. Attempting to use global Python...
    set PYTHON_EXE=python
)

%PYTHON_EXE% main.py --demo
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] The demo failed. Please check the messages above.
    pause
)
popd
