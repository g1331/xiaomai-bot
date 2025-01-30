@echo off
echo Checking uv installation...
where uv >nul 2>nul
if %errorlevel% neq 0 (
    set /p response=uv is not installed. Do you want to install it? ^(y/n^):
    if /I "%response%"=="Y" (
        echo Installing uv...
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ) else (
        echo uv is required to run this script. Exiting.
        exit /b 1
    )
)

echo Checking if virtual environment exists...
if not exist .venv (
    echo Virtual environment not found. Creating virtual environment...
    uv venv
)

echo Activating virtual environment...
call .venv\Scripts\activate

echo Installing dependencies with uv...
uv sync

echo Running the program...
cmd /k "uv run main.py"