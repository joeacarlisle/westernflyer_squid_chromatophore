@echo off
:: Analyse every videos\*.mp4, or one video:  chromatophore_build.bat <video_id>
pushd "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
    set PYTHON_EXE=.venv\Scripts\python.exe
) else (
    echo [INFO] Virtual environment not found. Attempting to use global Python...
    set PYTHON_EXE=python
)

%PYTHON_EXE% main.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] The analysis failed. Please check the messages above.
    pause
)
popd
