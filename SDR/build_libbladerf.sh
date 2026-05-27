#!/bin/bash
# Build libbladeRF from source
# Usage: ./build_libbladerf.sh
#
# This script will:
# 1. Install required system dependencies
# 2. Initialize git submodules
# 3. Build libbladeRF
# 4. Set up udev rules for USB permissions

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLADERF_HOST="$SCRIPT_DIR/bladeRF/host"
BUILD_DIR="$BLADERF_HOST/build"

echo "[+] Building libbladeRF..."

# Step 1: Install dependencies (only if not root/sudo available)
if [ -z "$SUDO_COMMAND" ] && [ "$(id -u)" -ne 0 ]; then
    echo "[+] Note: Running as non-root. Skipping apt install."
    echo "[+] If build fails, run: sudo ./build_libbladerf.sh"
fi

# Step 2: Initialize submodules
echo "[+] Initializing git submodules..."
cd "$BLADERF_HOST"
git submodule update --init --recursive

# Step 3: Create build directory
echo "[+] Creating build directory..."
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Step 4: Configure with CMake
echo "[+] Configuring..."
cmake ..

# Step 5: Build
echo "[+] Building (this may take a few minutes)..."
make -j$(nproc)

# Step 6: Verify output
if [ -f "output/libbladeRF.so" ]; then
    echo ""
    echo "=========================================="
    echo "[✓] Build successful!"
    echo "[✓] Library: $(pwd)/output/libbladeRF.so"
    echo "[✓] CLI: $(pwd)/output/bladeRF-cli"
    echo "=========================================="
else
    echo "[-] Build failed - libbladeRF.so not found"
    exit 1
fi

# Step 7: Setup udev rules (optional, if running as root)
if [ "$(id -u)" -eq 0 ]; then
    echo ""
    echo "[+] Setting up udev rules for USB permissions..."
    if [ -f "build/misc/udev/88-nuand-bladerf2.rules" ]; then
        cp build/misc/udev/88-nuand-bladerf2.rules /etc/udev/rules.d/99-bladerf.rules
        udevadm control --reload-rules
        echo "[✓] udev rules installed"
    else
        echo "[!] udev rules file not found, skipping..."
    fi
else
    echo ""
    echo "[+] To enable USB access without root, run:"
    echo "    sudo cp $BLADERF_HOST/build/misc/udev/88-nuand-bladerf2.rules /etc/udev/rules.d/99-bladerf.rules"
    echo "    sudo udevadm control --reload-rules"
fi

echo ""
echo "[+] Setup complete!"
echo "[+] Add this to your shell profile for permanent library path:"
echo "    export LD_LIBRARY_PATH=$SCRIPT_DIR/bladeRF/host/build/output:\$LD_LIBRARY_PATH"