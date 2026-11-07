@echo off
setlocal
cd /d "%~dp0"

REM Check Pillow before launching without a console.
py -3 -c "import PIL" >nul 2>&1
if errorlevel 1 (
    echo Pillow is not installed. Installing it now...
    py -3 -m pip install pillow
    if errorlevel 1 (
        echo.
        echo Could not install Pillow. Check Python and internet access.
        pause
        exit /b 1
    )
)

REM Install Explorer drag-and-drop integration if missing.
py -3 -c "import tkinterdnd2" >nul 2>&1
if errorlevel 1 (
    echo Installing drag-and-drop support...
    py -3 -m pip install tkinterdnd2
    if errorlevel 1 (
        echo Could not install tkinterdnd2. Check Python and internet access.
        pause
        exit /b 1
    )
)

REM pyw launches the GUI without a persistent Command Prompt window.
where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw -3 "%~dp0spritesheet_assembler.py"
) else (
    REM Fallback for installations where pyw is not on PATH.
    where pythonw >nul 2>&1
    if not errorlevel 1 (
        start "" pythonw "%~dp0spritesheet_assembler.py"
    ) else (
        echo Could not find pyw.exe or pythonw.exe.
        echo Install Python for Windows and enable the Python launcher.
        pause
        exit /b 1
    )
)
exit /b 0
