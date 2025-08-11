#!/bin/sh
echo "Checking uv installation..."
if ! command -v uv > /dev/null 2>&1; then
    echo "uv is not installed. Do you want to install it? (y/n)"
    read -r response
    if [ "$response" = "y" ] || [ "$response" = "Y" ]; then
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
    else
        echo "uv is required to run this script. Exiting."
        exit 1
    fi
fi

echo "Checking if virtual environment exists..."
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Creating virtual environment..."
    uv venv
fi

echo "Activating virtual environment..."
. .venv/bin/activate

echo "Installing dependencies with uv..."
uv sync

# 设置环境变量
echo "Setting OPENSSL_CONF environment variable..."
export OPENSSL_CONF="${PWD}"/openssl.conf

# 运行程序
echo "Running the program..."
uv run main.py
