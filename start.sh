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
echo "Dependencies installed."

# 设置环境变量
echo "Setting OPENSSL_CONF environment variable..."
export OPENSSL_CONF="${PWD}"/openssl.conf

# 运行程序
echo "Running the program..."
poetry run python main.py
