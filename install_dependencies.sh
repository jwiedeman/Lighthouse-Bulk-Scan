#!/bin/bash

# Function to install dependencies on Linux
install_linux() {
    echo "Installing dependencies on Linux..."
    
    # Update and install required system packages
    sudo apt update && sudo apt upgrade -y
    sudo apt install -y nodejs npm python3-pip
    
    # Install Lighthouse globally using npm
    npm install -g lighthouse

    # Get the path to the npm bin directory
    NPM_BIN_DIR=$(npm bin -g)

    # Add the npm bin directory to PATH
    export PATH=$PATH:$NPM_BIN_DIR

    # Verify Lighthouse installation
    lighthouse --version

    # Install required Python packages
    pip3 install pandas beautifulsoup4 requests tqdm

    echo "Dependencies installed and configured on Linux."
}

# Function to install dependencies on Windows
install_windows() {
    echo "Installing dependencies on Windows..."
    
    # Update npm
    npm install -g npm

    # Install Lighthouse globally using npm
    npm install -g lighthouse

    # Add npm global bin directory to PATH
    NPM_BIN_DIR=$(npm bin -g)
    export PATH=$PATH:$NPM_BIN_DIR

    # Verify Lighthouse installation
    lighthouse --version

    # Install required Python packages
    pip install pandas beautifulsoup4 requests tqdm

    echo "Dependencies installed and configured on Windows."
}

# Detect the operating system
OS=$(uname)

if [[ "$OS" == "Linux" ]]; then
    install_linux
elif [[ "$OS" == "MINGW64_NT"* || "$OS" == "MSYS_NT"* ]]; then
    install_windows
else
    echo "Unsupported operating system: $OS"
    exit 1
fi
