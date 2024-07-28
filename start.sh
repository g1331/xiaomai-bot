#!/bin/sh
echo "Checking if virtual environment exists..."
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
. venv/bin/activate

echo "Checking if Poetry is installed..."
if ! command -v poetry > /dev/null 2>&1; then
    echo "Poetry is not installed. Installing Poetry..."
    pip install poetry
fi

echo "Installing dependencies..."
poetry install --no-root
echo "Dependencies installed. Running the program..."
poetry run OPENSSL_CONF=${PWD}/openssl.conf python main.py